"""Small, dependency-free client for a local Ollama server."""

from __future__ import annotations

import json
from urllib.error import URLError
from urllib.request import Request, urlopen


OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:3b"


def _request_json(path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{OLLAMA_BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data else "GET",
    )
    with urlopen(request, timeout=90) as response:  # Local requests can take time on a CPU.
        return json.loads(response.read().decode("utf-8"))


def is_available() -> bool:
    """Return whether a local Ollama server is available."""
    try:
        _request_json("/api/tags")
    except (URLError, TimeoutError, OSError):
        return False
    return True


def parse_questions(raw_response: str) -> list[dict[str, object]]:
    """Validate the exact JSON format StudySpring accepts from a model."""
    parsed = json.loads(raw_response)
    questions = parsed.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("The model did not return a question list.")

    valid_questions = []
    for item in questions:
        options = item.get("options") if isinstance(item, dict) else None
        required = ("topic", "question", "correct_answer")
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str) for key in required):
            continue
        if not isinstance(options, list) or len(options) != 4 or not all(
            isinstance(option, str) and option.strip() for option in options
        ):
            continue
        if item["correct_answer"] not in options:
            continue
        valid_questions.append(
            {
                "topic": item["topic"].strip(),
                "question": item["question"].strip(),
                "options": [option.strip() for option in options],
                "correct_answer": item["correct_answer"].strip(),
                "explanation": str(item.get("explanation", "")).strip(),
            }
        )

    if not valid_questions:
        raise ValueError("The model returned no valid multiple-choice questions.")
    return valid_questions


def generate_questions(notes: str, question_count: int = 5) -> list[dict[str, object]]:
    """Ask the local model for structured questions based only on supplied notes."""
    prompt = f"""Create exactly {question_count} multiple-choice study questions from the notes below.
Use only facts supported by the notes. Return JSON only, with this exact shape:
{{"questions":[{{"topic":"...","question":"...","options":["...","...","...","..."],"correct_answer":"one exact option","explanation":"short explanation"}}]}}

Notes:
{notes[:12000]}
"""
    response = _request_json(
        "/api/generate",
        {"model": DEFAULT_MODEL, "prompt": prompt, "stream": False, "format": "json"},
    )
    return parse_questions(response.get("response", ""))
