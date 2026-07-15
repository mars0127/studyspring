"""SQLite helpers for StudySpring's saved course data."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


DATABASE_PATH = Path(__file__).with_name("studyspring.db")


@contextmanager
def get_connection() -> sqlite3.Connection:
    """Yield a database connection, then commit and close it safely."""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize_database() -> None:
    """Create the tables needed by the first version of StudySpring."""
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS courses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                subject TEXT NOT NULL,
                exam_date TEXT,
                is_preinstalled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        course_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(courses)").fetchall()
        }
        if "is_preinstalled" not in course_columns:
            connection.execute(
                "ALTER TABLE courses ADD COLUMN is_preinstalled INTEGER NOT NULL DEFAULT 0"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS quiz_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id INTEGER NOT NULL,
                topic TEXT NOT NULL,
                question TEXT NOT NULL,
                options_json TEXT NOT NULL,
                correct_answer TEXT NOT NULL,
                explanation TEXT NOT NULL DEFAULT '',
                question_type TEXT NOT NULL DEFAULT 'multiple_choice',
                achievement_category TEXT NOT NULL DEFAULT 'Knowledge & Understanding',
                marks INTEGER NOT NULL DEFAULT 1,
                sample_answer TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (course_id) REFERENCES courses(id)
            )
            """
        )
        # Older local databases may have been created before explanations existed.
        question_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(quiz_questions)").fetchall()
        }
        if "explanation" not in question_columns:
            connection.execute(
                "ALTER TABLE quiz_questions ADD COLUMN explanation TEXT NOT NULL DEFAULT ''"
            )
        if "question_type" not in question_columns:
            connection.execute("ALTER TABLE quiz_questions ADD COLUMN question_type TEXT NOT NULL DEFAULT 'multiple_choice'")
        if "achievement_category" not in question_columns:
            connection.execute("ALTER TABLE quiz_questions ADD COLUMN achievement_category TEXT NOT NULL DEFAULT 'Knowledge & Understanding'")
        if "marks" not in question_columns:
            connection.execute("ALTER TABLE quiz_questions ADD COLUMN marks INTEGER NOT NULL DEFAULT 1")
        if "sample_answer" not in question_columns:
            connection.execute("ALTER TABLE quiz_questions ADD COLUMN sample_answer TEXT NOT NULL DEFAULT ''")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL,
                selected_answer TEXT NOT NULL,
                is_correct INTEGER NOT NULL,
                attempted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (question_id) REFERENCES quiz_questions(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS quiz_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id INTEGER NOT NULL,
                score INTEGER NOT NULL,
                total_questions INTEGER NOT NULL,
                topics_json TEXT NOT NULL DEFAULT '[]',
                completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (course_id) REFERENCES courses(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS study_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                unit TEXT NOT NULL DEFAULT '',
                chapter TEXT NOT NULL DEFAULT '',
                lesson TEXT NOT NULL DEFAULT '',
                source_group TEXT NOT NULL DEFAULT 'lesson',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (course_id) REFERENCES courses(id)
            )
            """
        )
        note_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(study_notes)").fetchall()
        }
        if "unit" not in note_columns:
            connection.execute("ALTER TABLE study_notes ADD COLUMN unit TEXT NOT NULL DEFAULT ''")
        if "chapter" not in note_columns:
            connection.execute("ALTER TABLE study_notes ADD COLUMN chapter TEXT NOT NULL DEFAULT ''")
        if "lesson" not in note_columns:
            connection.execute("ALTER TABLE study_notes ADD COLUMN lesson TEXT NOT NULL DEFAULT ''")
        if "source_group" not in note_columns:
            connection.execute(
                "ALTER TABLE study_notes ADD COLUMN source_group TEXT NOT NULL DEFAULT 'lesson'"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS flashcards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id INTEGER NOT NULL,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (course_id) REFERENCES courses(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pdf_import_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id INTEGER NOT NULL,
                document_hash TEXT NOT NULL,
                filename TEXT NOT NULL,
                first_page INTEGER NOT NULL,
                last_page INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(course_id, document_hash, first_page, last_page),
                FOREIGN KEY (course_id) REFERENCES courses(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pdf_import_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                page_number INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                extraction_method TEXT NOT NULL DEFAULT '',
                extracted_text TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(job_id, page_number),
                FOREIGN KEY (job_id) REFERENCES pdf_import_jobs(id)
            )
            """
        )


def record_quiz_session(
    course_id: int, score: int, total_questions: int, topics: list[str]
) -> None:
    """Save a compact record of a completed quiz for the recent-quiz list."""
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO quiz_sessions (course_id, score, total_questions, topics_json)
            VALUES (?, ?, ?, ?)
            """,
            (course_id, score, total_questions, json.dumps(sorted(set(topics)))),
        )


def list_recent_quiz_sessions(course_id: int, limit: int = 8) -> list[dict[str, object]]:
    """Return recent completed quiz summaries, newest first."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT score, total_questions, topics_json, completed_at
            FROM quiz_sessions
            WHERE course_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (course_id, limit),
        ).fetchall()
    return [
        {
            "score": row["score"],
            "total_questions": row["total_questions"],
            "topics": json.loads(row["topics_json"]),
            "completed_at": row["completed_at"],
        }
        for row in rows
    ]


def create_course(
    name: str, subject: str, exam_date: str | None, is_preinstalled: bool = False
) -> int:
    """Save one course after validating its required fields."""
    clean_name = name.strip()
    clean_subject = subject.strip()

    if not clean_name or not clean_subject:
        raise ValueError("Course name and subject are required.")

    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO courses (name, subject, exam_date, is_preinstalled) VALUES (?, ?, ?, ?)",
            (clean_name, clean_subject, exam_date, int(is_preinstalled)),
        )
        return int(cursor.lastrowid)


def update_course(course_id: int, name: str, subject: str, exam_date: str | None) -> None:
    """Update the name, subject, and optional exam date for one course."""
    clean_name = name.strip()
    clean_subject = subject.strip()
    if not clean_name or not clean_subject:
        raise ValueError("Course name and subject are required.")

    with get_connection() as connection:
        connection.execute(
            "UPDATE courses SET name = ?, subject = ?, exam_date = ? WHERE id = ?",
            (clean_name, clean_subject, exam_date, course_id),
        )


def delete_course(course_id: int) -> None:
    """Delete a course and all of its locally stored study data."""
    with get_connection() as connection:
        course = connection.execute(
            "SELECT is_preinstalled FROM courses WHERE id = ?", (course_id,)
        ).fetchone()
        if course and course["is_preinstalled"]:
            raise ValueError("Preloaded course packs cannot be deleted.")
        connection.execute(
            """
            DELETE FROM quiz_attempts
            WHERE question_id IN (SELECT id FROM quiz_questions WHERE course_id = ?)
            """,
            (course_id,),
        )
        connection.execute("DELETE FROM quiz_questions WHERE course_id = ?", (course_id,))
        connection.execute("DELETE FROM study_notes WHERE course_id = ?", (course_id,))
        connection.execute("DELETE FROM flashcards WHERE course_id = ?", (course_id,))
        connection.execute("DELETE FROM courses WHERE id = ?", (course_id,))


def list_courses() -> list[sqlite3.Row]:
    """Return courses in the order the student created them."""
    with get_connection() as connection:
        return connection.execute(
            "SELECT id, name, subject, exam_date, is_preinstalled FROM courses ORDER BY id DESC"
        ).fetchall()


def create_or_resume_pdf_import_job(
    course_id: int, document_hash: str, filename: str, first_page: int, last_page: int
) -> int:
    """Create a checkpointed import job, or resume an identical incomplete job."""
    with get_connection() as connection:
        existing = connection.execute(
            """SELECT id FROM pdf_import_jobs
               WHERE course_id = ? AND document_hash = ? AND first_page = ? AND last_page = ?""",
            (course_id, document_hash, first_page, last_page),
        ).fetchone()
        if existing:
            return int(existing["id"])
        cursor = connection.execute(
            """INSERT INTO pdf_import_jobs (course_id, document_hash, filename, first_page, last_page)
               VALUES (?, ?, ?, ?, ?)""",
            (course_id, document_hash, filename, first_page, last_page),
        )
        job_id = int(cursor.lastrowid)
        connection.executemany(
            "INSERT INTO pdf_import_pages (job_id, page_number) VALUES (?, ?)",
            [(job_id, page_number) for page_number in range(first_page, last_page + 1)],
        )
        return job_id


def list_pdf_import_pages(job_id: int) -> list[dict[str, object]]:
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT page_number, status, extraction_method, extracted_text, error_message
               FROM pdf_import_pages WHERE job_id = ? ORDER BY page_number""",
            (job_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def save_pdf_import_page(
    job_id: int, page_number: int, status: str, extraction_method: str = "", text: str = "", error_message: str = ""
) -> None:
    """Persist each page immediately so an interrupted import remains recoverable."""
    if status not in {"pending", "processing", "completed", "failed", "skipped"}:
        raise ValueError("Unsupported PDF import status.")
    with get_connection() as connection:
        connection.execute(
            """UPDATE pdf_import_pages
               SET status = ?, extraction_method = ?, extracted_text = ?, error_message = ?,
                   updated_at = CURRENT_TIMESTAMP
               WHERE job_id = ? AND page_number = ?""",
            (status, extraction_method, text, error_message[:500], job_id, page_number),
        )
        connection.execute(
            """UPDATE pdf_import_jobs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (status, job_id),
        )


def complete_pdf_import_job(job_id: int) -> None:
    with get_connection() as connection:
        failed = connection.execute(
            "SELECT COUNT(*) AS count FROM pdf_import_pages WHERE job_id = ? AND status = 'failed'",
            (job_id,),
        ).fetchone()["count"]
        connection.execute(
            "UPDATE pdf_import_jobs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            ("partial" if failed else "completed", job_id),
        )


def create_study_note(
    course_id: int, title: str, content: str, unit: str = "", lesson: str = "", chapter: str = "", source_group: str = "lesson"
) -> None:
    """Save study material for a particular course."""
    clean_title = title.strip()
    clean_content = content.strip()

    if not clean_title or not clean_content:
        raise ValueError("A note title and note content are required.")

    with get_connection() as connection:
        connection.execute(
            "INSERT INTO study_notes (course_id, title, content, unit, lesson, chapter, source_group) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (course_id, clean_title, clean_content, unit.strip(), lesson.strip(), chapter.strip(), source_group),
        )


def list_study_notes(course_id: int) -> list[sqlite3.Row]:
    """Return the saved notes for one course, newest first."""
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, title, content, unit, chapter, lesson, source_group, created_at
            FROM study_notes
            WHERE course_id = ?
            ORDER BY id DESC
            """,
            (course_id,),
        ).fetchall()


def update_study_note_organization(note_id: int, unit: str, chapter: str, lesson: str) -> None:
    """Move a note into a unit, chapter, and lesson without changing its content."""
    with get_connection() as connection:
        connection.execute(
            "UPDATE study_notes SET unit = ?, chapter = ?, lesson = ? WHERE id = ?",
            (unit.strip(), chapter.strip(), lesson.strip(), note_id),
        )


def update_study_note(
    note_id: int, title: str, content: str, unit: str, chapter: str, lesson: str, source_group: str
) -> None:
    """Edit a saved note and its organization details."""
    clean_title = title.strip()
    clean_content = content.strip()
    if not clean_title or not clean_content:
        raise ValueError("A note title and note content are required.")
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE study_notes
            SET title = ?, content = ?, unit = ?, chapter = ?, lesson = ?, source_group = ?
            WHERE id = ?
            """,
            (clean_title, clean_content, unit.strip(), chapter.strip(), lesson.strip(), source_group, note_id),
        )


def delete_study_note(note_id: int) -> None:
    """Permanently remove one study note."""
    with get_connection() as connection:
        connection.execute("DELETE FROM study_notes WHERE id = ?", (note_id,))


def create_quiz_question(
    course_id: int,
    topic: str,
    question: str,
    options: list[str],
    correct_answer: str,
    explanation: str = "",
    question_type: str = "multiple_choice",
    achievement_category: str = "Knowledge & Understanding",
    marks: int = 1,
    sample_answer: str = "",
) -> None:
    """Save a multiple-choice or short-answer question for a course."""
    clean_topic = topic.strip()
    clean_question = question.strip()
    clean_options = [option.strip() for option in options]

    if not clean_topic or not clean_question:
        raise ValueError("A topic and question are required.")
    if question_type == "multiple_choice":
        if len(clean_options) != 4 or any(not option for option in clean_options):
            raise ValueError("All four answer choices are required.")
        if correct_answer not in clean_options:
            raise ValueError("Choose one of the answer choices as the correct answer.")
    elif question_type == "short_answer":
        if not sample_answer.strip():
            raise ValueError("Add a sample answer or marking guide for a short-answer question.")
        clean_options = []
        correct_answer = sample_answer.strip()
    else:
        raise ValueError("Choose a supported question type.")
    if marks < 1:
        raise ValueError("A question must be worth at least one mark.")

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO quiz_questions
                (course_id, topic, question, options_json, correct_answer, explanation,
                 question_type, achievement_category, marks, sample_answer)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course_id,
                clean_topic,
                clean_question,
                json.dumps(clean_options),
                correct_answer,
                explanation.strip(),
                question_type,
                achievement_category,
                marks,
                sample_answer.strip(),
            ),
        )


def list_quiz_questions(course_id: int) -> list[dict[str, object]]:
    """Return quiz questions with their answer choices unpacked as a list."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, topic, question, options_json, correct_answer, explanation,
                   question_type, achievement_category, marks, sample_answer
            FROM quiz_questions
            WHERE course_id = ?
            ORDER BY id DESC
            """,
            (course_id,),
        ).fetchall()

    questions = []
    for row in rows:
        question = dict(row)
        question["options"] = json.loads(question.pop("options_json"))
        questions.append(question)
    return questions


def record_quiz_attempt(question_id: int, selected_answer: str, is_correct: bool) -> None:
    """Store one submitted quiz answer."""
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO quiz_attempts (question_id, selected_answer, is_correct)
            VALUES (?, ?, ?)
            """,
            (question_id, selected_answer, int(is_correct)),
        )


def course_quiz_stats(course_id: int) -> tuple[int, float | None]:
    """Return the number of attempted questions and the average percentage."""
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(quiz_attempts.id) AS attempts,
                   AVG(quiz_attempts.is_correct) AS accuracy
            FROM quiz_attempts
            JOIN quiz_questions ON quiz_questions.id = quiz_attempts.question_id
            WHERE quiz_questions.course_id = ?
            """,
            (course_id,),
        ).fetchone()

    accuracy = float(row["accuracy"]) * 100 if row["accuracy"] is not None else None
    return int(row["attempts"]), accuracy


def course_topic_stats(course_id: int) -> list[dict[str, object]]:
    """Return per-topic attempt counts and accuracy for one course."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT quiz_questions.topic AS topic,
                   COUNT(quiz_attempts.id) AS attempts,
                   AVG(quiz_attempts.is_correct) AS accuracy
            FROM quiz_questions
            JOIN quiz_attempts ON quiz_attempts.question_id = quiz_questions.id
            WHERE quiz_questions.course_id = ?
            GROUP BY quiz_questions.topic
            ORDER BY accuracy ASC, attempts DESC, quiz_questions.topic ASC
            """,
            (course_id,),
        ).fetchall()

    return [
        {
            "topic": row["topic"],
            "attempts": int(row["attempts"]),
            "accuracy": round(float(row["accuracy"]) * 100),
        }
        for row in rows
    ]


def course_attempt_history(course_id: int) -> list[dict[str, object]]:
    """Return a course's answer history for a student-owned progress export."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT quiz_attempts.attempted_at AS attempted_at,
                   quiz_questions.topic AS topic,
                   quiz_questions.question AS question,
                   quiz_attempts.selected_answer AS selected_answer,
                   quiz_questions.correct_answer AS correct_answer,
                   quiz_attempts.is_correct AS is_correct
            FROM quiz_attempts
            JOIN quiz_questions ON quiz_questions.id = quiz_attempts.question_id
            WHERE quiz_questions.course_id = ?
            ORDER BY quiz_attempts.id DESC
            """,
            (course_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def create_flashcard(course_id: int, front: str, back: str) -> None:
    """Save a question-and-answer flashcard for a course."""
    clean_front = front.strip()
    clean_back = back.strip()
    if not clean_front or not clean_back:
        raise ValueError("Both sides of a flashcard are required.")

    with get_connection() as connection:
        connection.execute(
            "INSERT INTO flashcards (course_id, front, back) VALUES (?, ?, ?)",
            (course_id, clean_front, clean_back),
        )


def list_flashcards(course_id: int) -> list[dict[str, object]]:
    """Return a course's flashcards as ordinary dictionaries for Streamlit."""
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT id, front, back FROM flashcards WHERE course_id = ? ORDER BY id DESC",
            (course_id,),
        ).fetchall()
    return [dict(row) for row in rows]
