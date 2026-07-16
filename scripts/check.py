"""Run StudySpring's cross-platform local validation commands."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
STEPS = [
    (
        "Compilation",
        [
            PYTHON,
            "-m",
            "compileall",
            "-q",
            "app.py",
            "database.py",
            "components",
            "pages",
            "services",
        ],
    ),
    ("Ruff lint", [PYTHON, "-m", "ruff", "check", "."]),
    ("Ruff formatting", [PYTHON, "-m", "ruff", "format", "--check", "."]),
    ("Pyright", [PYTHON, "-m", "pyright"]),
    ("Tests", [PYTHON, "-m", "pytest"]),
    (
        "Course Pack validation",
        [PYTHON, "tools/course_pack.py", "validate", "course_packs/ontario/mhf4u/manifest.json"],
    ),
]


def main() -> int:
    for label, command in STEPS:
        print(f"\n== {label} ==")
        if subprocess.run(command, cwd=ROOT).returncode:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
