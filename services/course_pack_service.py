"""Validated, version-controlled course packs for StudySpring."""

from __future__ import annotations

import json
from pathlib import Path

from services.content_blocks import ContentBlockError, blocks_to_markdown, validate_blocks


PACK_ROOT = Path(__file__).resolve().parent.parent / "course_packs"
REQUIRED_MANIFEST_FIELDS = {"id", "title", "curriculum", "jurisdiction", "grade", "course_code", "subject", "version", "license", "sources", "units"}


class CoursePackError(ValueError):
    """A pack could not be shown or installed safely."""


def list_course_packs() -> list[dict[str, object]]:
    """Return validated manifests available in the bundled library."""
    packs = []
    for manifest_path in PACK_ROOT.glob("**/manifest.json"):
        packs.append(load_course_pack(manifest_path))
    return sorted(packs, key=lambda pack: str(pack["title"]))


def load_course_pack(manifest_path: Path) -> dict[str, object]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CoursePackError("This course pack has an unreadable manifest.") from error
    missing = REQUIRED_MANIFEST_FIELDS - set(manifest)
    if missing:
        raise CoursePackError(f"This course pack is missing required information: {', '.join(sorted(missing))}.")
    if not isinstance(manifest["units"], list) or not manifest["units"]:
        raise CoursePackError("This course pack needs at least one unit.")
    for unit in manifest["units"]:
        if not isinstance(unit, dict) or not unit.get("title") or not unit.get("lesson_file"):
            raise CoursePackError("This course pack has an invalid unit.")
        lesson_path = manifest_path.parent / str(unit["lesson_file"])
        if not lesson_path.is_file():
            raise CoursePackError(f"The lesson file '{unit['lesson_file']}' is missing.")
        if lesson_path.suffix.lower() == ".json":
            try:
                lesson = json.loads(lesson_path.read_text(encoding="utf-8"))
                unit["blocks"] = validate_blocks(lesson.get("blocks"))
            except (OSError, json.JSONDecodeError, ContentBlockError) as error:
                raise CoursePackError(f"The lesson '{unit['lesson_file']}' has invalid content blocks: {error}") from error
    manifest["_manifest_path"] = str(manifest_path)
    return manifest


def lesson_text(pack: dict[str, object], unit: dict[str, object]) -> str:
    """Read legacy Markdown or adapt validated JSON blocks for saved-note compatibility."""
    if "blocks" in unit:
        return blocks_to_markdown(unit["blocks"])
    manifest_path = Path(str(pack["_manifest_path"]))
    return (manifest_path.parent / str(unit["lesson_file"])).read_text(encoding="utf-8").strip()
