"""Small client for creating StudySpring quiz questions with Google Gemini."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable


# Stable multimodal model designed for high-volume extraction work.
DEFAULT_MODEL = "gemini-3.1-flash-lite"
# Keeping a request small matters more on Render than the model's theoretical
# context window.  This prevents a long quiz from holding one browser request
# open while it produces a very large JSON response.
MAX_QUESTIONS_PER_REQUEST = 5
# A modest request keeps response time and transient memory low on Render's
# smallest instance.  Longer source material is spread over more short calls.
MAX_SOURCE_CHARACTERS_PER_REQUEST = 12_000
MIN_SEMANTIC_SECTION_CHARACTERS = 3_000
QUESTION_REQUEST_INTERVAL_SECONDS = 6
QUESTION_QUOTA_RETRY_SECONDS = 65
MAX_QUESTION_QUOTA_RETRIES = 2


def _gemini_modules():
    """Import Gemini only when an AI feature is used."""
    try:
        from google import genai
        from google.genai import types
    except ImportError as error:
        raise RuntimeError("Gemini is not installed. Run: pip install -r requirements.txt") from error
    return genai, types


def create_gemini_client(api_key: str):
    """Create one Gemini connection that can be reused for a larger task."""
    genai, _ = _gemini_modules()
    return genai.Client(api_key=api_key)


def _generate_with_retries(client, **request_arguments):
    """Retry temporary provider-overload errors before failing the student's request."""
    for attempt in range(3):
        try:
            return client.models.generate_content(**request_arguments)
        except Exception as error:
            error_text = str(error)
            temporary_error = (
                "503" in error_text
                or "UNAVAILABLE" in error_text
                or "WinError 10013" in error_text
            )
            if not temporary_error or attempt == 2:
                raise
            time.sleep(2**attempt)


def parse_questions(raw_response: str) -> list[dict[str, object]]:
    """Validate the JSON format StudySpring accepts from an AI model."""
    parsed = json.loads(raw_response)
    questions = parsed.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("The AI did not return a question list.")
    valid_questions = []
    for item in questions:
        options = item.get("options") if isinstance(item, dict) else None
        required = ("topic", "question", "correct_answer")
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str) for key in required):
            continue
        if not isinstance(options, list) or len(options) != 4 or not all(
            isinstance(option, str) and option.strip() for option in options
        ) or item["correct_answer"] not in options:
            continue
        valid_questions.append({
            "topic": item["topic"].strip(), "question": item["question"].strip(),
            "options": [option.strip() for option in options],
            "correct_answer": item["correct_answer"].strip(),
            "explanation": str(item.get("explanation", "")).strip(),
        })
    if not valid_questions:
        raise ValueError("The AI returned no valid multiple-choice questions.")
    return valid_questions


def _is_quota_error(error: Exception) -> bool:
    message = str(error).lower()
    return "resource_exhausted" in message or "quota exceeded" in message or " 429" in message


def _split_at_paragraph_boundaries(text: str, maximum_size: int) -> list[str]:
    """Split one long section without cutting words or formulas in half."""
    if len(text) <= maximum_size:
        return [text]
    pieces: list[str] = []
    remaining = text
    while len(remaining) > maximum_size:
        split_at = remaining.rfind("\n\n", 0, maximum_size)
        if split_at < maximum_size // 2:
            split_at = remaining.rfind("\n", 0, maximum_size)
        if split_at < maximum_size // 2:
            split_at = remaining.rfind(" ", 0, maximum_size)
        if split_at < 1:
            split_at = maximum_size
        pieces.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _semantic_sections(source: str) -> list[str]:
    """Use chapter/unit/lesson headings before falling back to paragraph chunks.

    Imported PDFs often preserve headings such as "Chapter 6" or "Unit 2".
    Keeping those sections together gives Gemini a focused, coherent source
    instead of an arbitrary slice across two unrelated lessons.
    """
    heading = re.compile(
        r"(?im)^(?=(?:chapter|unit|lesson|section|topic)\s+(?:\d+|[ivxlcdm]+)"
        r"(?:\s*[:\-]|\s*$))"
    )
    starts = [match.start() for match in heading.finditer(source)]
    if not starts or starts[0] != 0:
        starts.insert(0, 0)
    candidates = [
        source[start:end].strip()
        for start, end in zip(starts, starts[1:] + [len(source)])
        if source[start:end].strip()
    ]
    # A textbook can mention another chapter in ordinary prose.  A two-page
    # "chapter" is a strong sign that a match is not a useful structural
    # boundary, so merge short candidates into their neighbour instead of
    # generating a separate quiz slice from them.
    sections: list[str] = []
    for candidate in candidates:
        if sections and len(candidate) < MIN_SEMANTIC_SECTION_CHARACTERS:
            sections[-1] += "\n\n" + candidate
        else:
            sections.append(candidate)
    if len(sections) > 1 and len(sections[0]) < MIN_SEMANTIC_SECTION_CHARACTERS:
        sections[1] = sections[0] + "\n\n" + sections[1]
        sections.pop(0)
    return sections or [source]


def split_question_source(notes: str, request_count: int) -> list[str]:
    """Create coherent, bounded source chunks for a larger quiz.

    This preserves the full prepared source and preferentially separates it at
    real chapter, unit, lesson, or topic headings.  It is intentionally not a
    database split: students still keep one imported note and can quiz it in
    one click.
    """
    source = notes[:75_000].strip()
    if not source:
        raise ValueError("Add some study material before generating questions.")
    effective_request_count = max(
        request_count,
        (len(source) + MAX_SOURCE_CHARACTERS_PER_REQUEST - 1)
        // MAX_SOURCE_CHARACTERS_PER_REQUEST,
    )
    target_size = max(1, (len(source) + effective_request_count - 1) // effective_request_count)
    target_size = min(MAX_SOURCE_CHARACTERS_PER_REQUEST, target_size)
    pieces = [
        piece
        for section in _semantic_sections(source)
        for piece in _split_at_paragraph_boundaries(section, target_size)
        if piece
    ]

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        separator = "\n\n" if current else ""
        if current and len(current) + len(separator) + len(piece) > target_size:
            chunks.append(current)
            current = piece
        else:
            current += separator + piece
    if current:
        chunks.append(current)
    return chunks


def generate_question_batch(api_key: str, notes: str, question_count: int) -> list[dict[str, object]]:
    """Generate one small JSON question batch with a bounded response size."""
    genai, types = _gemini_modules()
    prompt = f'''Study material:
{notes}

Based only on the study material above, create exactly {question_count} multiple-choice study questions.
The source may combine the student's notes with textbook excerpts, slides, and teacher resources.
Return JSON only, with this exact shape:
{{"questions":[{{"topic":"...","question":"...","options":["...","...","...","..."],"correct_answer":"one exact option","explanation":"short explanation"}}]}}
'''
    # Close the HTTP client after every short batch.  Leaving these clients
    # open can accumulate sockets and memory in a long-lived Streamlit process.
    with genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=30_000),
    ) as client:
        response = _generate_with_retries(
            client,
            model=DEFAULT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", temperature=0.3, max_output_tokens=2048
            ),
        )
        response_text = response.text
    if not response_text:
        raise ValueError("Gemini returned an empty response. Please try again.")
    return parse_questions(response_text)


def plan_question_batches(notes: str, question_count: int) -> list[tuple[str, int]]:
    """Plan small, coherent requests without calling Gemini yet."""
    if question_count < 1:
        raise ValueError("Choose at least one question.")
    minimum_batches = (question_count + MAX_QUESTIONS_PER_REQUEST - 1) // MAX_QUESTIONS_PER_REQUEST
    source_chunks = split_question_source(notes, minimum_batches)
    batch_count = max(minimum_batches, len(source_chunks))
    source_chunks = split_question_source(notes, batch_count)
    base_count, extra = divmod(question_count, len(source_chunks))
    return [
        (source_chunk, base_count + (1 if index < extra else 0))
        for index, source_chunk in enumerate(source_chunks)
        if base_count + (1 if index < extra else 0)
    ]


def generate_questions(
    api_key: str,
    notes: str,
    question_count: int = 5,
    on_batch_complete: Callable[[list[dict[str, object]], int, int], None] | None = None,
) -> list[dict[str, object]]:
    """Generate larger quiz sets in small paced requests instead of one huge call."""
    planned_batches = plan_question_batches(notes, question_count)
    generated: list[dict[str, object]] = []
    for index, (source_chunk, batch_size) in enumerate(planned_batches):
        if index:
            time.sleep(QUESTION_REQUEST_INTERVAL_SECONDS)
        for quota_attempt in range(MAX_QUESTION_QUOTA_RETRIES + 1):
            try:
                batch_questions = generate_question_batch(api_key, source_chunk, batch_size)
                generated.extend(batch_questions)
                if on_batch_complete:
                    on_batch_complete(batch_questions, index + 1, len(planned_batches))
                break
            except Exception as error:
                if _is_quota_error(error) and quota_attempt < MAX_QUESTION_QUOTA_RETRIES:
                    time.sleep(QUESTION_QUOTA_RETRY_SECONDS)
                    continue
                if _is_quota_error(error):
                    raise RuntimeError(
                        "Gemini is still at its temporary request limit. Wait a minute, then try again."
                    ) from error
                raise
    return generated[:question_count]


def grade_short_answer(
    api_key: str,
    question: str,
    student_answer: str,
    marking_guide: str,
    achievement_category: str,
    possible_marks: int,
) -> dict[str, object]:
    """Mark one student response against the saved marking guide, not outside facts."""
    genai, types = _gemini_modules()
    prompt = f'''You are marking a student practice response, not a real school assessment.
Use only the question, student response, and marking guide below. Do not reward facts that are not supported by the marking guide.
Return JSON only in exactly this shape:
{{"score":0,"feedback":"...","strengths":["..."],"next_step":"..."}}

Question: {question}
Ontario achievement category: {achievement_category}
Possible marks: {possible_marks}
Student response: {student_answer}
Marking guide: {marking_guide}
'''
    client = genai.Client(api_key=api_key)
    response = _generate_with_retries(
        client,
        model=DEFAULT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1),
    )
    try:
        result = json.loads(response.text or "")
        score = int(result["score"])
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise ValueError("Gemini returned an unusable marking result. Please try again.") from error
    return {
        "score": max(0, min(possible_marks, score)),
        "feedback": str(result.get("feedback", "")).strip(),
        "strengths": [str(item).strip() for item in result.get("strengths", []) if str(item).strip()],
        "next_step": str(result.get("next_step", "")).strip(),
    }


def extract_text_from_image(api_key: str, image_bytes: bytes, mime_type: str, client=None) -> str:
    """Use Gemini's image understanding to turn a handwritten or scanned note into text."""
    genai, types = _gemini_modules()
    client = client or genai.Client(api_key=api_key)
    response = _generate_with_retries(
        client,
        model=DEFAULT_MODEL,
        contents=[
            "Transcribe this study-note image accurately. Return only the readable note text. "
            "Keep headings, formulas, lists, and important labels. Do not add facts or explanations.",
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        ],
        config=types.GenerateContentConfig(temperature=0),
    )
    text = (response.text or "").strip()
    if not text:
        raise ValueError("Gemini could not find readable text in that image.")
    return text


def extract_text_from_images(api_key: str, image_pages: list[bytes], client=None) -> str:
    """Transcribe a small batch of scanned PDF pages with one Gemini request."""
    if not image_pages:
        raise ValueError("No PDF pages were provided for transcription.")
    genai, types = _gemini_modules()
    client = client or genai.Client(api_key=api_key)
    contents = [
        "Transcribe these study-textbook pages accurately, in order. Return only the readable "
        "note text. Keep page headings, formulas, lists, and important labels. Do not add facts "
        "or explanations. Separate each page with a clear 'Page N' heading."
    ]
    contents.extend(
        types.Part.from_bytes(data=image_bytes, mime_type="image/png")
        for image_bytes in image_pages
    )
    response = _generate_with_retries(
        client,
        model=DEFAULT_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(temperature=0),
    )
    text = (response.text or "").strip()
    if not text:
        raise ValueError("Gemini could not find readable text in those PDF pages.")
    return text
