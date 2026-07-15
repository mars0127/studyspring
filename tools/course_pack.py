"""Local-only scaffolding and validation for StudySpring Course Packs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.course_pack_service import CoursePackError, load_course_pack


def scaffold(destination: Path, pack_id: str) -> None:
    """Create a small, valid pack template. Never runs in the public app."""
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "lessons").mkdir()
    manifest = {"id": pack_id, "title": "New StudySpring course", "curriculum": "", "jurisdiction": "", "grade": "", "course_code": "", "subject": "", "description": "", "version": "0.1.0", "author": "", "license": "", "sources": [{"title": "", "organization": "", "url": "", "license": "", "accessed": ""}], "units": [{"id": "unit-01", "title": "Unit 1", "estimated_minutes": 60, "topics": [], "lesson_file": "lessons/unit-01.json"}]}
    lesson = {"title": "Unit 1", "blocks": [{"type": "heading", "content": "Unit 1"}, {"type": "paragraph", "content": "Write an original lesson here."}]}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (destination / "lessons" / "unit-01.json").write_text(json.dumps(lesson, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Local StudySpring Course Pack authoring helper")
    sub = parser.add_subparsers(dest="command", required=True)
    valid = sub.add_parser("validate"); valid.add_argument("manifest", type=Path)
    make = sub.add_parser("scaffold"); make.add_argument("directory", type=Path); make.add_argument("--id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            pack = load_course_pack(args.manifest)
            print(f"Valid: {pack['id']} ({len(pack['units'])} unit(s))")
        else:
            scaffold(args.directory, args.id); print(f"Created pack scaffold: {args.directory}")
    except (CoursePackError, FileExistsError) as error:
        print(f"Invalid: {error}"); return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
