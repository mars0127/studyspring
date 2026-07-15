"""Small client for creating StudySpring quiz questions with Google Gemini."""

from __future__ import annotations

import json
import time


# Stable multimodal model designed for high-volume extraction work.
DEFAULT_MODEL = "gemini-3.1-flash-lite"


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
    for attempt in range(6):
        try:
            return client.models.generate_content(**request_arguments)
        except Exception as error:
            error_text = str(error)
            temporary_error = (
                "503" in error_text
                or "UNAVAILABLE" in error_text
                or "WinError 10013" in error_text
            )
            if not temporary_error or attempt == 5:
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


def generate_questions(api_key: str, notes: str, question_count: int = 5) -> list[dict[str, object]]:
    """Ask Gemini for structured questions based only on the supplied notes."""
    genai, types = _gemini_modules()
    prompt = f'''Create exactly {question_count} multiple-choice study questions from the notes below.
The source may combine the student's notes with textbook excerpts, slides, and teacher resources.
Treat those sources as one study package: connect related facts across them, but use only facts supported by the source. Return JSON only, with this exact shape:
{{"questions":[{{"topic":"...","question":"...","options":["...","...","...","..."],"correct_answer":"one exact option","explanation":"short explanation"}}]}}

Notes:
{notes[:2_000_000]}
'''
    client = genai.Client(api_key=api_key)
    response = _generate_with_retries(
        client,
        model=DEFAULT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.3),
    )
    if not response.text:
        raise ValueError("Gemini returned an empty response. Please try again.")
    return parse_questions(response.text)


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
