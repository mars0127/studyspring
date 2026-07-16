"""Validation and rendering helpers for structured Course Pack lesson content."""

from __future__ import annotations

from typing import Any


BLOCK_TYPES = {
    "heading", "paragraph", "definition", "formula", "worked_example",
    "common_mistake", "practice_set", "answer_key", "flashcard_set",
    "multiple_choice_set", "short_answer_set", "resource_link", "callout",
    "diagram_placeholder", "table", "warning", "tip", "vocabulary",
    "learning_objective", "estimated_time", "difficulty", "summary",
}


class ContentBlockError(ValueError):
    """A course lesson contains content that cannot be safely installed."""


def validate_blocks(blocks: Any) -> list[dict[str, Any]]:
    """Validate portable JSON lesson blocks and return a safe normalized copy."""
    if not isinstance(blocks, list) or not blocks:
        raise ContentBlockError("A lesson needs at least one content block.")
    normalized: list[dict[str, Any]] = []
    for index, block in enumerate(blocks, start=1):
        if not isinstance(block, dict) or block.get("type") not in BLOCK_TYPES:
            raise ContentBlockError(f"Block {index} has an unsupported type.")
        kind = str(block["type"])
        result = {"type": kind}
        for key in ("title", "content", "difficulty", "label", "url"):
            if key in block:
                if not isinstance(block[key], str):
                    raise ContentBlockError(f"Block {index} has an invalid {key} value.")
                result[key] = block[key].strip()
        if kind not in {"flashcard_set", "multiple_choice_set", "short_answer_set", "resource_link"}:
            if not result.get("content") and not result.get("title"):
                raise ContentBlockError(f"Block {index} needs content or a title.")
        if kind == "resource_link" and (not result.get("url") or not result.get("label")):
            raise ContentBlockError(f"Resource link block {index} needs a label and URL.")
        if kind == "flashcard_set":
            cards = block.get("cards")
            if not isinstance(cards, list) or not cards or any(
                not isinstance(card, dict) or not str(card.get("front", "")).strip() or not str(card.get("back", "")).strip()
                for card in cards
            ):
                raise ContentBlockError(f"Flashcard set {index} needs cards with a front and back.")
            result["cards"] = [{"front": str(card["front"]).strip(), "back": str(card["back"]).strip()} for card in cards]
        if kind == "multiple_choice_set":
            questions = block.get("questions")
            if not isinstance(questions, list) or not questions:
                raise ContentBlockError(f"Multiple-choice set {index} needs questions.")
            checked = []
            for question in questions:
                options = question.get("options") if isinstance(question, dict) else None
                answer = question.get("correct_answer") if isinstance(question, dict) else None
                if not isinstance(options, list) or len(options) != 4 or any(not str(item).strip() for item in options) or answer not in options or not str(question.get("question", "")).strip():
                    raise ContentBlockError(f"Multiple-choice set {index} has an invalid question.")
                checked.append({"question": str(question["question"]).strip(), "options": [str(item).strip() for item in options], "correct_answer": str(answer), "explanation": str(question.get("explanation", "")).strip(), "topic": str(question.get("topic", "Course pack")).strip()})
            result["questions"] = checked
        if kind == "short_answer_set":
            questions = block.get("questions")
            if not isinstance(questions, list) or not questions or any(not isinstance(question, dict) or not str(question.get("question", "")).strip() or not str(question.get("sample_answer", "")).strip() for question in questions):
                raise ContentBlockError(f"Short-answer set {index} needs questions with marking guides.")
            result["questions"] = [{"question": str(question["question"]).strip(), "sample_answer": str(question["sample_answer"]).strip(), "topic": str(question.get("topic", "Course pack")).strip()} for question in questions]
        normalized.append(result)
    return normalized


def blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    """Provide a readable note fallback while preserving the original structured source."""
    output: list[str] = []
    for block in blocks:
        kind, title, content = block["type"], block.get("title", ""), block.get("content", "")
        if kind == "heading": output.append(f"## {title or content}")
        elif kind == "formula": output.append(f"**Formula: {title}**\n\n`{content}`")
        elif kind == "definition": output.append(f"**{title}**\n\n{content}")
        elif kind == "worked_example": output.append(f"### Worked example: {title}\n\n{content}")
        elif kind == "common_mistake": output.append(f"> **Common mistake — {title}**\n> {content}")
        elif kind == "callout": output.append(f"> **{title}**\n> {content}")
        elif kind == "warning": output.append(f"> **Watch out — {title}**\n> {content}")
        elif kind == "tip": output.append(f"> **Study tip — {title}**\n> {content}")
        elif kind == "diagram_placeholder": output.append(f"### Visual: {title}\n\n{content}")
        elif kind == "resource_link": output.append(f"[{block['label']}]({block['url']})")
        elif kind == "flashcard_set": output.append("### Flashcards\n\n" + "\n".join(f"- **{card['front']}**: {card['back']}" for card in block["cards"]))
        elif kind.endswith("_set"):
            output.append(f"### {title or kind.replace('_', ' ').title()}\n\n{content}")
        else: output.append(content or title)
    return "\n\n".join(part for part in output if part).strip()
