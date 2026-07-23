"""StudySpring: a simple study dashboard built with Streamlit."""

import csv
import gc
import math
import os
import random
import shutil
import tempfile
import time
from datetime import date
from io import BytesIO, StringIO
from pathlib import Path

import streamlit as st
from pypdf import PdfReader

from database import (
    create_course,
    create_flashcard,
    create_quiz_question,
    create_quiz_questions,
    create_study_note,
    append_study_note_content,
    course_quiz_stats,
    course_attempt_history,
    course_topic_stats,
    delete_course,
    delete_study_note,
    get_study_note,
    get_study_note_excerpt,
    get_study_note_preview,
    initialize_database,
    list_courses,
    list_flashcards,
    list_quiz_questions,
    list_recent_quiz_sessions,
    list_study_notes,
    record_quiz_attempt,
    record_quiz_session,
    rename_study_note,
    replace_study_note_content,
    update_study_note_organization,
    update_study_note,
    update_study_note_metadata,
    update_course,
)
from gemini_client import (
    DEFAULT_MODEL,
    extract_text_from_image,
    generate_question_batch,
    grade_short_answer,
    plan_question_batches,
)
from course_starters import COURSE_STARTERS
from pdf_import import (
    is_ocr_quota_error,
    is_unreadable_ocr_error,
    iter_pdf_pages,
    iter_pdf_pages_from_path,
    pdf_page_count,
    pdf_page_count_from_path,
)


MAX_SELECTED_SCANNED_PDF_PAGES = 120
# Keep the complete prompt plan comfortably below the memory and latency
# envelope of Render's free instance.  It is split into coherent batches later.
MAX_AI_SOURCE_CHARACTERS = 36_000
MAX_NOTE_EDITOR_CHARACTERS = 120_000
APP_VERSION = "2026.07.23.4"
# Render's free instances have limited memory. A larger file can be held more
# than once while Streamlit and PyMuPDF inspect it, which can restart the app.
MAX_TEXTBOOK_UPLOAD_MB = int(os.getenv("TEXTBOOK_UPLOAD_MAX_MB", "40"))
MAX_AUTOMATIC_SCANNED_TEXTBOOK_PAGES = int(
    os.getenv("AUTOMATIC_SCANNED_TEXTBOOK_MAX_PAGES", "120")
)
# Gemini's free tier permits 15 requests/minute. Stay below that rate so a
# scanned PDF is completed page-by-page instead of losing pages to quota skips.
OCR_REQUEST_INTERVAL_SECONDS = float(os.getenv("OCR_REQUEST_INTERVAL_SECONDS", "5"))
OCR_QUOTA_RETRY_SECONDS = int(os.getenv("OCR_QUOTA_RETRY_SECONDS", "65"))
MAX_OCR_QUOTA_RETRIES = 3
PDF_SCAN_BATCH_SIZE = 6


st.set_page_config(page_title="StudySpring", page_icon="🌱", layout="wide")
st.markdown(
    """
    <style>
      [data-testid="stSidebar"] { min-width: 23rem; }
      [data-testid="stSidebar"] > div:first-child {
        height: 100vh;
        overflow-y: auto;
        padding-bottom: 3rem;
      }
      /* Keep the starter-course menu tall enough to show many choices at once. */
      [role="listbox"] {
        max-height: 72vh !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)
initialize_database()


def gemini_api_key() -> str | None:
    """Read a private key from Streamlit secrets or the local environment."""
    try:
        secret_value = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        # A missing or malformed secrets file should not take down the whole app.
        secret_value = None
    return secret_value or os.getenv("GEMINI_API_KEY")


def is_gemini_quota_error(error: Exception) -> bool:
    """Recognize provider limits without exposing the provider's raw response."""
    message = str(error).lower()
    return "resource_exhausted" in message or "quota exceeded" in message or " 429" in message


def course_label(course: dict[str, object]) -> str:
    """Format a short label for Streamlit's course picker."""
    return f"{course['name']} · {course['subject']}"


def extract_pdf_text(file_bytes: bytes) -> str:
    """Extract readable text from a text-based PDF upload."""
    reader = PdfReader(BytesIO(file_bytes))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()


def validate_upload_size(uploaded_file, label: str, maximum_mb: int = MAX_TEXTBOOK_UPLOAD_MB) -> None:
    """Reject unsafe uploads before copying their bytes into application memory."""
    size = int(getattr(uploaded_file, "size", 0) or 0)
    maximum_bytes = maximum_mb * 1024 * 1024
    if size > maximum_bytes:
        raise ValueError(
            f"{label} is {size / 1024 / 1024:.0f} MB. This hosted version safely accepts "
            f"files up to {maximum_mb} MB. Split or compress the PDF into smaller files, then import one at a time."
        )


def save_uploaded_pdf_to_temp(uploaded_file) -> Path:
    """Keep one uploaded PDF on disk during a multi-batch scan, not in session memory."""
    with tempfile.NamedTemporaryFile(prefix="studyspring-scan-", suffix=".pdf", delete=False) as temp_file:
        uploaded_file.seek(0)
        shutil.copyfileobj(uploaded_file, temp_file, length=1024 * 1024)
        return Path(temp_file.name)


def read_pdf_pages_for_import(
    pdf_source: bytes | Path,
    first_page: int,
    last_page: int,
    api_key: str | None,
    progress,
) -> tuple[list[tuple[int, str]], list[int], str | None]:
    """Read pages independently while pacing OCR requests below Gemini's free limit."""
    total_pages = last_page - first_page + 1
    extracted: list[tuple[int, str]] = []
    skipped_pages: list[int] = []
    last_ocr_request_at = 0.0
    page_iterator = (
        iter_pdf_pages_from_path(pdf_source, first_page, last_page)
        if isinstance(pdf_source, Path)
        else iter_pdf_pages(pdf_source, first_page, last_page)
    )
    for completed, page in enumerate(page_iterator, start=1):
        progress.progress(
            (completed - 1) / total_pages,
            text=f"Reading page {page.number} of {last_page}...",
        )
        if page.image_bytes is None:
            extracted.append((page.number, page.text))
            continue
        if not api_key:
            skipped_pages.append(page.number)
            extracted.append((page.number, f"[Page {page.number} was skipped because AI OCR is not set up.]"))
            continue
        wait_seconds = OCR_REQUEST_INTERVAL_SECONDS - (time.monotonic() - last_ocr_request_at)
        if wait_seconds > 0:
            progress.progress(
                (completed - 1) / total_pages,
                text=f"Waiting briefly before reading page {page.number} to stay within the AI limit...",
            )
            time.sleep(wait_seconds)
        for quota_attempt in range(MAX_OCR_QUOTA_RETRIES + 1):
            try:
                last_ocr_request_at = time.monotonic()
                text = extract_text_from_image(api_key, page.image_bytes, "image/png")
                break
            except Exception as error:
                if is_ocr_quota_error(error) and quota_attempt < MAX_OCR_QUOTA_RETRIES:
                    progress.progress(
                        (completed - 1) / total_pages,
                        text=f"AI limit reached on page {page.number}; waiting {OCR_QUOTA_RETRY_SECONDS} seconds, then retrying...",
                    )
                    time.sleep(OCR_QUOTA_RETRY_SECONDS)
                    continue
                if is_ocr_quota_error(error):
                    raise RuntimeError(
                        f"Page {page.number} is still waiting for the AI request limit after "
                        f"{MAX_OCR_QUOTA_RETRIES} retries. Please try again shortly."
                    ) from error
                if not is_unreadable_ocr_error(error):
                    raise RuntimeError(f"Page {page.number} could not be read: {error}") from error
                skipped_pages.append(page.number)
                extracted.append((page.number, f"[Page {page.number} was skipped because it contains no readable text.]"))
                text = None
                break
        if text is not None:
            extracted.append((page.number, text))
    progress.progress(1.0, text="Organizing extracted text...")
    return extracted, skipped_pages, None


def prepare_ai_source(selected_notes: list[dict[str, object]], labeler) -> tuple[str, bool]:
    """Keep AI prompts bounded without keeping every saved note in memory."""
    if not selected_notes:
        return "", False
    total_source_length = sum(int(note.get("content_length", len(str(note.get("content", ""))))) for note in selected_notes)
    allowance = max(2_000, MAX_AI_SOURCE_CHARACTERS // len(selected_notes))
    sampled = []
    for note in selected_notes:
        content = str(note.get("content", ""))
        if not content:
            # SQLite extracts only the small parts we will actually send to
            # Gemini.  Do not load a whole scanned textbook for every widget
            # rerun just to build a bounded quiz prompt.
            content = get_study_note_excerpt(int(note["id"]), allowance, piece_count=6)
        if int(note.get("content_length", len(content))) > allowance:
            content += "\n[Additional material is stored in StudySpring.]"
        sampled.append(f"--- {labeler(note)} ---\n{content}")
    return "\n\n".join(sampled)[:MAX_AI_SOURCE_CHARACTERS], total_source_length > MAX_AI_SOURCE_CHARACTERS


def make_progress_csv(attempts: list[dict[str, object]]) -> str:
    """Create a CSV the student can download without sending data elsewhere."""
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "attempted_at",
            "topic",
            "question",
            "selected_answer",
            "correct_answer",
            "is_correct",
        ],
    )
    writer.writeheader()
    writer.writerows(attempts)
    return output.getvalue()


st.title("🌱 StudySpring")
st.subheader("Turn your notes into a clearer study plan.")
deployed_commit = os.getenv("RENDER_GIT_COMMIT", "local")[:7]
st.caption(f"Version {APP_VERSION} · build {deployed_commit}")

import_status = st.session_state.pop("import_status", None)
if import_status:
    if import_status.get("warning"):
        st.warning(import_status["message"])
    else:
        st.success(import_status["message"])

with st.sidebar:
    st.header("🌱 StudySpring")
    st.caption("Your private study workspace")
    st.divider()
    st.subheader("Your courses")

    with st.form("create_course_form", clear_on_submit=True):
        course_name = st.text_input("Course name", placeholder="e.g. Grade 11 Biology")
        subject = st.text_input("Subject", placeholder="e.g. Science")
        exam_date = st.date_input("Exam date (optional)", value=None)
        submitted = st.form_submit_button("Add course", width="stretch")

    if submitted:
        try:
            date_value = exam_date.isoformat() if exam_date else None
            create_course(course_name, subject, date_value)
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Course added!")
            st.rerun()

    st.divider()
    st.subheader("Ontario course starters")
    st.caption("Add a course roadmap with organized units and a free learning-resource link.")
    starter_choice = st.selectbox("Choose a starter course", list(COURSE_STARTERS))
    starter = COURSE_STARTERS[starter_choice]
    if st.button("Add starter course", width="stretch"):
        try:
            course_id = create_course(
                starter["name"], starter["subject"], None, is_preinstalled=True
            )
            for number, (unit_name, overview) in enumerate(starter["units"], start=1):
                create_study_note(
                    course_id,
                    f"Unit {number}: {unit_name}",
                    f"Course roadmap\n\n{overview}\n\n"
                    f"For deeper study, use [{starter['resource_label']}]({starter['resource_url']}) "
                    "alongside your teacher's materials and textbook.",
                    unit=f"Unit {number}: {unit_name}",
                    lesson="Course roadmap",
                    source_group="lesson",
                )
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Starter course added with its unit roadmap!")
            st.rerun()

# SQLite returns special row objects. Streamlit dropdowns work best with
# ordinary dictionaries, so convert the rows before presenting course options.
courses = [dict(course) for course in list_courses()]

if not courses:
    st.info("Create your first course in the sidebar to start building a study plan.")
    st.stop()

selected_course = st.selectbox("Choose a course", courses, format_func=course_label)

st.markdown(f"## {selected_course['name']}")
st.caption(f"Subject: {selected_course['subject']}")

days_remaining = None
if selected_course["exam_date"]:
    st.caption(f"Exam date: {selected_course['exam_date']}")

with st.expander("Course settings"):
    existing_exam_date = (
        date.fromisoformat(selected_course["exam_date"])
        if selected_course["exam_date"]
        else None
    )
    with st.form("update_course_form"):
        updated_name = st.text_input("Course name", value=selected_course["name"])
        updated_subject = st.text_input("Subject", value=selected_course["subject"])
        updated_exam_date = st.date_input("Exam date (optional)", value=existing_exam_date)
        saved_course = st.form_submit_button("Save course changes", width="stretch")

    if saved_course:
        try:
            update_course(
                selected_course["id"],
                updated_name,
                updated_subject,
                updated_exam_date.isoformat() if updated_exam_date else None,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Course updated!")
            st.rerun()

    if selected_course.get("is_preinstalled"):
        st.info("This is a protected preloaded course pack. You can add your own study material, but the course pack cannot be deleted.")
    else:
        st.divider()
        delete_confirmation = st.checkbox(
            "I understand this permanently deletes this course and its study data.",
            key=f"delete_confirmation_{selected_course['id']}",
        )
        if st.button("Delete this course", type="secondary", disabled=not delete_confirmation):
            delete_course(selected_course["id"])
            st.rerun()

left_column, middle_column, right_column = st.columns(3)
study_notes = list_study_notes(selected_course["id"], include_content=False)
flashcards = list_flashcards(selected_course["id"])
quiz_questions = list_quiz_questions(selected_course["id"])
attempt_count, average_score = course_quiz_stats(selected_course["id"])
topic_stats = course_topic_stats(selected_course["id"])
attempt_history = course_attempt_history(selected_course["id"])
recent_quiz_sessions = list_recent_quiz_sessions(selected_course["id"])

left_column.metric("Study notes", len(study_notes))
middle_column.metric("Flashcards", len(flashcards))
right_column.metric(
    "Average score", f"{average_score:.0f}%" if average_score is not None else "—"
)

if selected_course["exam_date"]:
    days_remaining = (date.fromisoformat(selected_course["exam_date"]) - date.today()).days
    if days_remaining >= 0:
        st.info(f"📅 **{days_remaining} day(s) until your exam.** A little review today goes a long way.")
    else:
        st.caption("This course’s exam date has passed. You can update it by creating a new course for the next term.")

st.subheader("Today’s study plan")
plan_items = []
if topic_stats and topic_stats[0]["accuracy"] < 70:
    plan_items.append(
        f"Review **{topic_stats[0]['topic']}** first; it is currently your lowest-scoring topic."
    )
if flashcards:
    if selected_course["exam_date"] and days_remaining > 0:
        cards_per_day = max(3, math.ceil(len(flashcards) / days_remaining))
        plan_items.append(f"Review at least **{cards_per_day} flashcard(s)** today.")
    else:
        plan_items.append(f"Review **{min(10, len(flashcards))} flashcard(s)** today.")
if quiz_questions:
    plan_items.append("Take a practice quiz and read every answer explanation afterward.")
if study_notes and not quiz_questions:
    plan_items.append("Turn one note into a few practice questions or flashcards.")
if not plan_items:
    plan_items.append("Start by adding a course note, then create a few flashcards or a practice question.")

for plan_item in plan_items:
    st.write(f"- {plan_item}")

if topic_stats:
    weak_topics = [topic for topic in topic_stats if topic["accuracy"] < 70]
    if weak_topics:
        st.warning("**Suggested review topics:**")
        for topic in weak_topics:
            st.write(
                f"- **{topic['topic']}**: {topic['accuracy']}% accuracy across {topic['attempts']} answer(s)."
            )
    else:
        st.success("Great work — your recorded topic scores are 70% or higher.")
elif study_notes:
    st.info("**Suggested next step:** add a few practice questions from your notes to start tracking progress.")

st.divider()
st.subheader("Study notes")
st.write("Add class notes, key facts, or a chapter summary. Quizzes will use these notes later.")

with st.expander("Add study material", expanded=not study_notes):
    new_note_source_group = "lesson"
    st.caption("Add your own notes, teacher handouts, slides, lesson text, or learning-platform material here.")
    material_type = st.selectbox(
        "What are you adding?",
        [
            "Paste text",
            "PDF with selectable text",
            "Photo or handwritten scan",
            "Pages from a scanned PDF",
            "Scanned PDF",
        ],
    )
    new_note_unit = ""
    new_note_chapter = ""
    new_note_lesson = ""
    new_note_topic = ""
    organization_left, organization_middle, organization_right = st.columns(3)
    new_note_unit = organization_left.text_input(
        "Unit (optional)", placeholder="e.g. Unit 2: Skeletal system"
    )
    new_note_lesson = organization_right.text_input(
        "Lesson (optional)", placeholder="e.g. Bone structure"
    )
    new_note_chapter = organization_middle.text_input(
        "Chapter (optional)", placeholder="e.g. Chapter 3"
    )
    new_note_topic = st.text_input(
        "Topic for practice quizzes (recommended)",
        placeholder="e.g. Mitosis, Quadratic functions, Supply and demand",
        help="Use one clear topic name. Material with the same topic can be practised together.",
    )

    if material_type == "Paste text":
        st.caption("Paste copied text from the material selected above.")
        with st.form("create_note_form", clear_on_submit=True):
            note_title = st.text_input(
                "Title",
                placeholder="e.g. Cell division chapter",
            )
            note_content = st.text_area("Text", placeholder="Paste the text here...", height=180)
            saved_note = st.form_submit_button("Save material", width="stretch")
        if saved_note:
            try:
                create_study_note(selected_course["id"], note_title, note_content, new_note_unit, new_note_lesson, new_note_chapter, new_note_source_group, new_note_topic)
            except ValueError as error:
                st.error(str(error))
            else:
                st.success("Material saved!")
                st.rerun()

    elif material_type == "PDF with selectable text":
        st.caption("Use this when you can highlight and copy words from the PDF.")
        with st.form("upload_pdf_form", clear_on_submit=True):
            uploaded_pdf = st.file_uploader("Choose a PDF", type=["pdf"])
            save_pdf = st.form_submit_button("Extract and save PDF", width="stretch")
        if save_pdf:
            try:
                if uploaded_pdf is None:
                    raise ValueError("Choose a PDF before saving.")
                pdf_text = extract_pdf_text(uploaded_pdf.getvalue())
                if not pdf_text:
                    raise ValueError("No text was found. Choose 'Pages from a scanned PDF' instead.")
                create_study_note(selected_course["id"], uploaded_pdf.name.removesuffix(".pdf"), pdf_text, new_note_unit, new_note_lesson, new_note_chapter, new_note_source_group, new_note_topic)
            except Exception as error:
                st.error(f"We could not read that PDF: {error}")
            else:
                st.success("PDF notes saved!")
                st.rerun()

    elif material_type == "Photo or handwritten scan":
        st.caption("Use a clear JPG, PNG, or WEBP photo. Gemini turns it into editable text.")
        with st.form("upload_image_form", clear_on_submit=True):
            uploaded_image = st.file_uploader("Choose a scan or photo", type=["jpg", "jpeg", "png", "webp"])
            save_image = st.form_submit_button("Read image and save notes", width="stretch")
        if save_image:
            api_key = gemini_api_key()
            try:
                if uploaded_image is None:
                    raise ValueError("Choose an image before saving.")
                if not api_key:
                    raise ValueError("Add GEMINI_API_KEY to Streamlit secrets before using scans.")
                if uploaded_image.size > 10 * 1024 * 1024:
                    raise ValueError("Choose an image smaller than 10 MB.")
                image_text = extract_text_from_image(api_key, uploaded_image.getvalue(), uploaded_image.type or "image/jpeg")
                create_study_note(selected_course["id"], uploaded_image.name.rsplit(".", 1)[0], image_text, new_note_unit, new_note_lesson, new_note_chapter, new_note_source_group, new_note_topic)
            except Exception as error:
                st.error(f"We could not read that image: {error}")
            else:
                st.success("Scanned note saved as editable text!")
                st.rerun()

    elif material_type == "Pages from a scanned PDF":
        st.caption(
            f"Choose up to {MAX_SELECTED_SCANNED_PDF_PAGES} pages. Readable pages stay local; "
            "only scanned pages are sent to Gemini one at a time."
        )
        with st.form("upload_scanned_pdf_form", clear_on_submit=True):
            scanned_pdf = st.file_uploader("Choose a scanned PDF", type=["pdf"], key="scanned_pdf")
            first_page = st.number_input("First page", min_value=1, value=1, step=1)
            last_page = st.number_input("Last page", min_value=1, value=1, step=1)
            save_scanned_pdf = st.form_submit_button("Read selected PDF pages", width="stretch")
        if save_scanned_pdf:
            api_key = gemini_api_key()
            page_count = int(last_page) - int(first_page) + 1
            try:
                if scanned_pdf is None:
                    raise ValueError("Choose a scanned PDF before continuing.")
                if not 1 <= page_count <= MAX_SELECTED_SCANNED_PDF_PAGES:
                    raise ValueError(f"Choose between 1 and {MAX_SELECTED_SCANNED_PDF_PAGES} pages.")
                progress = st.progress(0, text="Reading scanned PDF pages...")
                pages, skipped_pages, ocr_pause_reason = read_pdf_pages_for_import(
                    scanned_pdf.getvalue(), int(first_page), int(last_page), api_key, progress
                )
                create_study_note(
                    selected_course["id"],
                    f"{scanned_pdf.name.rsplit('.', 1)[0]} pages {first_page}-{last_page}",
                    "\n\n".join(text for _, text in pages),
                    new_note_unit,
                    new_note_lesson,
                    new_note_chapter,
                    new_note_source_group,
                    new_note_topic,
                )
            except Exception as error:
                st.error(f"We could not read those PDF pages: {error}")
            else:
                message = "Scanned PDF pages saved as editable notes!"
                if skipped_pages:
                    message = (
                        f"Saved the readable pages. Skipped image-only or unreadable page(s): "
                        f"{', '.join(map(str, skipped_pages))}."
                    )
                    if ocr_pause_reason:
                        message += f" {ocr_pause_reason}"
                st.session_state["import_status"] = {"message": message, "warning": bool(skipped_pages)}
                st.rerun()

    else:
        st.caption(
            f"Scanned PDFs can be up to {MAX_TEXTBOOK_UPLOAD_MB} MB and "
            f"{MAX_AUTOMATIC_SCANNED_TEXTBOOK_PAGES} pages. The entire import is saved as one study note."
        )
        with st.form("scan_entire_pdf_form", clear_on_submit=True):
            entire_pdf = st.file_uploader("Choose a scanned PDF", type=["pdf"], key="entire_pdf")
            confirmed = st.checkbox("I understand scanned pages are read one at a time and large scans can take several minutes.")
            start_full_scan = st.form_submit_button("Scan and save PDF", width="stretch")
        scan_job_key = f"pdf_scan_job_{selected_course['id']}"
        if start_full_scan:
            try:
                if not confirmed:
                    raise ValueError("Check the confirmation box before starting the scan.")
                if entire_pdf is None:
                    raise ValueError("Choose a scanned PDF before continuing.")
                validate_upload_size(entire_pdf, "This PDF")
                pdf_path = save_uploaded_pdf_to_temp(entire_pdf)
                total_pages = pdf_page_count_from_path(pdf_path)
                if total_pages > MAX_AUTOMATIC_SCANNED_TEXTBOOK_PAGES:
                    pdf_path.unlink(missing_ok=True)
                    raise ValueError(
                        f"This PDF has {total_pages} pages. The hosted scanner safely handles up to "
                        f"{MAX_AUTOMATIC_SCANNED_TEXTBOOK_PAGES} pages at a time."
                    )
                final_title = entire_pdf.name.rsplit('.', 1)[0]
                note_id = create_study_note(
                    selected_course["id"],
                    f"{final_title} (importing)",
                    "[Import in progress — pages will appear here as they are read.]",
                    new_note_unit,
                    new_note_lesson,
                    new_note_chapter,
                    new_note_source_group,
                    new_note_topic,
                )
                st.session_state[scan_job_key] = {
                    "path": str(pdf_path),
                    "title": final_title,
                    "note_id": note_id,
                    "total_pages": total_pages,
                    "next_page": 1,
                    "skipped_pages": [],
                }
                st.rerun()
            except Exception as error:
                st.error(f"We could not start that PDF scan: {error}")

        scan_job = st.session_state.get(scan_job_key)
        if scan_job:
            batch_first = int(scan_job["next_page"])
            batch_last = min(
                batch_first + PDF_SCAN_BATCH_SIZE - 1, int(scan_job["total_pages"])
            )
            progress = st.progress(
                (batch_first - 1) / int(scan_job["total_pages"]),
                text=f"Reading pages {batch_first}-{batch_last} of {scan_job['total_pages']}...",
            )
            try:
                pages, skipped_pages, _ = read_pdf_pages_for_import(
                    Path(str(scan_job["path"])), batch_first, batch_last, gemini_api_key(), progress
                )
                batch_text = "\n\n".join(text for _, text in pages)
                if batch_first == 1:
                    replace_study_note_content(int(scan_job["note_id"]), batch_text)
                else:
                    append_study_note_content(int(scan_job["note_id"]), batch_text)
                scan_job["next_page"] = batch_last + 1
                scan_job["skipped_pages"].extend(skipped_pages)
            except Exception as error:
                st.error(
                    f"The scan paused at page {batch_first}. The pages already completed are saved in "
                    "the same note. Use Continue scan after the connection or AI limit settles. "
                    f"Details: {error}"
                )
                if st.button("Continue scan", key=f"continue_scan_{selected_course['id']}"):
                    st.rerun()
            else:
                if int(scan_job["next_page"]) <= int(scan_job["total_pages"]):
                    st.session_state[scan_job_key] = scan_job
                    st.rerun()
                else:
                    rename_study_note(int(scan_job["note_id"]), str(scan_job["title"]))
                    Path(str(scan_job["path"])).unlink(missing_ok=True)
                    skipped = scan_job["skipped_pages"]
                    message = f"Finished reading {scan_job['total_pages']} pages into one saved study note!"
                    if skipped:
                        message += f" Pages without readable text: {', '.join(map(str, skipped))}."
                    st.session_state.pop(scan_job_key, None)
                    st.session_state["import_status"] = {"message": message, "warning": bool(skipped)}
                    st.rerun()

if len(study_notes) >= 2:
    with st.expander("Combine study material"):
        st.caption("Combine two or more notes into one organized note. The original notes stay unless you choose to remove them.")
        note_by_id = {note["id"]: note for note in study_notes}
        selected_note_ids = st.multiselect(
            "Notes to combine",
            list(note_by_id),
            format_func=lambda note_id: note_by_id[note_id]["title"],
        )
        with st.form("combine_study_notes_form", clear_on_submit=True):
            combined_title = st.text_input("Combined note title", placeholder="e.g. Unit 1 complete notes")
            combine_left, combine_middle, combine_right = st.columns(3)
            combined_unit = combine_left.text_input("Unit")
            combined_chapter = combine_middle.text_input("Chapter")
            combined_lesson = combine_right.text_input("Lesson")
            remove_originals = st.checkbox("Remove the original notes after combining them")
            combine_notes = st.form_submit_button("Combine selected notes", width="stretch")
        if combine_notes:
            try:
                if len(selected_note_ids) < 2:
                    raise ValueError("Choose at least two notes to combine.")
                combined_content = "\n\n".join(
                    f"--- {note_by_id[note_id]['title']} ---\n{get_study_note(note_id)['content']}"
                    for note_id in selected_note_ids
                )
                create_study_note(
                    selected_course["id"],
                    combined_title,
                    combined_content,
                    combined_unit,
                    combined_lesson,
                    combined_chapter,
                    "lesson",
                )
                if remove_originals:
                    for note_id in selected_note_ids:
                        delete_study_note(note_id)
            except ValueError as error:
                st.error(str(error))
            else:
                st.success("Study material combined!")
                st.rerun()

if study_notes:
    available_units = sorted({note["unit"] for note in study_notes if note["unit"]})
    available_chapters = sorted({note["chapter"] for note in study_notes if note["chapter"]})
    filter_left, filter_right = st.columns(2)
    unit_filter = filter_left.selectbox("View notes by unit", ["All units", "Unsorted"] + available_units)
    chapter_filter = filter_right.selectbox("View notes by chapter", ["All chapters", "Unsorted"] + available_chapters)
    visible_notes = [
        note for note in study_notes
        if (unit_filter == "All units" or (unit_filter == "Unsorted" and not note["unit"]) or note["unit"] == unit_filter)
        and (chapter_filter == "All chapters" or (chapter_filter == "Unsorted" and not note["chapter"]) or note["chapter"] == chapter_filter)
    ]
    visible_notes.sort(key=lambda note: (note["unit"], note["chapter"], note["lesson"], note["title"]))
    selected_note_id = None
    if visible_notes:
        selected_note_id = st.selectbox(
            "Open study material",
            [note["id"] for note in visible_notes],
            format_func=lambda note_id: next(note["title"] for note in visible_notes if note["id"] == note_id),
        )
    else:
        st.info("No study material matches these filters.")
    for note in visible_notes:
        if note["id"] != selected_note_id:
            continue
        note_is_large = int(note["content_length"]) > MAX_NOTE_EDITOR_CHARACTERS
        if note_is_large:
            # This screen reruns whenever a quiz control changes. Avoid loading
            # an entire imported textbook just because it is selected for viewing.
            opened_note = dict(note)
            opened_note["content"] = get_study_note_preview(int(note["id"]))
        else:
            opened_note = get_study_note(int(note["id"]))
            if opened_note is None:
                continue
        note = opened_note
        location = " · ".join(item for item in [note["unit"], note["chapter"], note["lesson"]] if item)
        note_heading = f"{location} — {note['title']}" if location else note["title"]
        with st.expander(note_heading):
            if note_is_large:
                st.caption(
                    "This large imported note is shown as a preview to keep the hosted app stable. "
                    "Its complete text remains saved for AI generation."
                )
                st.text(note["content"] + "\n\n[Preview ends here]")
            else:
                st.write(note["content"])
            st.caption("Edit the title, content, or organization below.")
            with st.form(f"edit_note_{note['id']}"):
                updated_title = st.text_input("Note title", value=note["title"], key=f"note_title_{note['id']}")
                if not note_is_large:
                    updated_content = st.text_area("Note content", value=note["content"], height=180, key=f"note_content_{note['id']}")
                else:
                    updated_content = ""
                    st.info("Full-text editing is unavailable for this large imported note. You can still rename and organize it.")
                organization_left, organization_middle, organization_right = st.columns(3)
                updated_unit = organization_left.text_input("Unit", value=note["unit"], key=f"note_unit_{note['id']}")
                updated_chapter = organization_middle.text_input("Chapter", value=note["chapter"], key=f"note_chapter_{note['id']}")
                updated_lesson = organization_right.text_input("Lesson", value=note["lesson"], key=f"note_lesson_{note['id']}")
                updated_topic = st.text_input(
                    "Topic for practice quizzes", value=note["topic"], key=f"note_topic_{note['id']}"
                )
                save_note = st.form_submit_button("Save note changes")
            if save_note:
                try:
                    if note_is_large:
                        update_study_note_metadata(
                            note["id"], updated_title, updated_unit, updated_chapter, updated_lesson, updated_topic
                        )
                    else:
                        update_study_note(
                            note["id"], updated_title, updated_content,
                            updated_unit, updated_chapter, updated_lesson,
                            "lesson", updated_topic,
                        )
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.rerun()

            delete_confirmation = st.checkbox(
                "I understand this permanently removes this study material.",
                key=f"delete_note_confirmation_{note['id']}",
            )
            if st.button("Remove note", key=f"delete_note_{note['id']}", disabled=not delete_confirmation):
                delete_study_note(note["id"])
                st.rerun()

st.divider()
st.subheader("Flashcards")
st.write("Create quick review cards for definitions, concepts, formulas, or vocabulary.")

with st.expander("Create a flashcard", expanded=not flashcards):
    with st.form("create_flashcard_form", clear_on_submit=True):
        flashcard_front = st.text_area("Front (prompt)", placeholder="e.g. What is the purpose of mitosis?")
        flashcard_back = st.text_area("Back (answer)", placeholder="e.g. Growth and repair by making identical cells.")
        saved_flashcard = st.form_submit_button("Save flashcard", width="stretch")

    if saved_flashcard:
        try:
            create_flashcard(selected_course["id"], flashcard_front, flashcard_back)
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Flashcard saved!")
            st.rerun()

if flashcards:
    flashcard_index_key = f"flashcard_index_{selected_course['id']}"
    current_index = st.session_state.get(flashcard_index_key, 0) % len(flashcards)
    current_card = flashcards[current_index]
    st.caption(f"Card {current_index + 1} of {len(flashcards)}")
    st.markdown(f"### {current_card['front']}")
    with st.expander("Show answer"):
        st.write(current_card["back"])

    previous_column, next_column = st.columns(2)
    if previous_column.button("← Previous card", width="stretch"):
        st.session_state[flashcard_index_key] = (current_index - 1) % len(flashcards)
        st.rerun()
    if next_column.button("Next card →", width="stretch"):
        st.session_state[flashcard_index_key] = (current_index + 1) % len(flashcards)
        st.rerun()

st.divider()
st.subheader("Practice quiz")
st.write("Create questions now, then practise them in the quiz below.")

if study_notes:
    with st.expander("Practice a topic with AI", expanded=True):
        st.caption(
            "Choose one saved topic. StudySpring uses only material in that topic, then saves your results so it can spot weak areas."
        )
        api_key = gemini_api_key()
        if api_key:
            note_options = [dict(note) for note in study_notes]
            def ai_note_label(note: dict[str, object]) -> str:
                location = " · ".join(
                    str(item) for item in [note.get("unit"), note.get("lesson")] if item
                )
                return f"{location} — {note['title']}" if location else str(note["title"])

            def note_topic(note: dict[str, object]) -> str:
                return str(note.get("topic") or note.get("lesson") or note["title"])

            saved_topics = sorted({note_topic(note) for note in note_options})
            chosen_topic = st.selectbox(
                "Topic to practise",
                saved_topics,
                help="Add topic labels while importing material to make this list more precise.",
            )
            selected_notes = [note for note in note_options if note_topic(note) == chosen_topic]
            st.caption(f"Using {len(selected_notes)} saved material item(s) for **{chosen_topic}**.")

            active_question_job = st.session_state.get(f"ai_question_job_{selected_course['id']}")
            if active_question_job:
                # The prepared chunks are already checkpointed in session state.
                # Do not reload a long PDF note during each automatic batch rerun.
                source_text, source_was_limited = "", False
            else:
                source_text, source_was_limited = prepare_ai_source(selected_notes, ai_note_label)
            if selected_notes and not active_question_job:
                st.caption(f"Topic material: {len(source_text):,} characters.")
            if source_was_limited:
                st.info(
                    "This material is larger than one safe AI request. StudySpring is using a "
                    "balanced sample from across this topic. Add more specific topic labels to "
                    "make future quizzes even more focused."
                )
            source_length = len(source_text)
            if source_length <= 4_000:
                recommended_minimum, recommended_maximum = 3, 5
            elif source_length <= 15_000:
                recommended_minimum, recommended_maximum = 5, 8
            elif source_length <= 50_000:
                recommended_minimum, recommended_maximum = 8, 15
            else:
                recommended_minimum, recommended_maximum = 15, 25
            st.caption(
                f"Recommended for this material: **{recommended_minimum}-{recommended_maximum} questions**. "
                "This is a suggestion, not a requirement."
            )
            question_count = st.number_input(
                "Questions in this topic quiz",
                min_value=0,
                max_value=recommended_maximum,
                value=(recommended_minimum + recommended_maximum) // 2,
                step=1,
                help="Choose a safe amount for this one topic. The quiz will be ready as soon as generation finishes.",
            )
            if question_count > 8:
                st.caption(
                    "Larger sets are generated in smaller safe AI requests. This can take a little longer, "
                    "but avoids one oversized request failing."
                )
            question_job_key = f"ai_question_job_{selected_course['id']}"
            question_job = st.session_state.get(question_job_key)
            if question_job:
                batch_index = int(question_job["next_batch"])
                planned_batches = question_job["batches"]
                source_chunk, batch_size = planned_batches[batch_index]
                try:
                    with st.spinner(
                        f"Creating question batch {batch_index + 1} of {len(planned_batches)}..."
                    ):
                        wait_seconds = float(question_job.get("next_request_after", 0)) - time.monotonic()
                        if wait_seconds > 0:
                            time.sleep(wait_seconds)
                        batch_questions = generate_question_batch(
                            api_key, source_chunk, batch_size, str(question_job["topic"])
                        )
                        create_quiz_questions(selected_course["id"], batch_questions)
                    question_job["saved_count"] += len(batch_questions)
                    question_job["next_batch"] = batch_index + 1
                    question_job["next_request_after"] = time.monotonic() + 6
                    del batch_questions
                    gc.collect()
                except Exception as error:
                    if is_gemini_quota_error(error):
                        # Repeating a request while the project quota is exhausted
                        # cannot succeed and can keep the app in a failed rerun loop.
                        st.session_state.pop(question_job_key, None)
                        st.warning(
                            f"Saved {question_job['saved_count']} question(s). Gemini has reached its "
                            "temporary limit, so generation was stopped safely. Try again after the limit resets."
                        )
                    else:
                        st.warning(
                            f"Saved {question_job['saved_count']} question(s). The next small AI batch paused. "
                            "You can continue without losing the questions already saved."
                        )
                        with st.expander("Technical details"):
                            st.code(str(error))
                        if st.button("Continue question generation", width="stretch"):
                            st.rerun()
                else:
                    if question_job["next_batch"] < len(planned_batches):
                        st.session_state[question_job_key] = question_job
                        st.rerun()
                    else:
                        st.session_state.pop(question_job_key, None)
                        st.success(f"Your {question_job['saved_count']}-question {question_job['topic']} quiz is ready below!")
                        st.session_state["open_practice_quiz"] = True
                        st.session_state["preferred_quiz_topic"] = str(question_job["topic"])
                        st.rerun()
            elif st.button("Generate AI questions", width="stretch", disabled=question_count == 0):
                try:
                    if not selected_notes:
                        raise ValueError("Choose at least one study note first.")
                    st.session_state[question_job_key] = {
                        "batches": plan_question_batches(source_text, question_count),
                        "next_batch": 0,
                        "saved_count": 0,
                        "next_request_after": 0,
                        "topic": chosen_topic,
                    }
                    st.rerun()
                except Exception as error:
                    st.error(f"We could not start question generation: {error}")
        else:
            st.warning("AI generation is not set up yet.")
            st.caption(
                "Add your private Gemini API key as GEMINI_API_KEY in Streamlit secrets, "
                "then restart StudySpring. Never paste it into notes or commit it to GitHub."
            )

with st.expander("Create a practice question", expanded=not quiz_questions):
    with st.form("create_question_form", clear_on_submit=True):
        question_type = st.selectbox(
            "Question type",
            ["Multiple choice", "Short answer"],
            help="Short-answer questions are useful for application, thinking, and communication practice.",
        )
        achievement_category = st.selectbox(
            "Ontario achievement category",
            ["Knowledge & Understanding", "Thinking", "Communication", "Application"],
        )
        question_marks = st.number_input("Marks", min_value=1, max_value=20, value=1, step=1)
        question_topic = st.text_input("Topic", placeholder="e.g. Mitosis")
        question_text = st.text_area("Question", placeholder="e.g. What is the purpose of mitosis?")
        option_one = option_two = option_three = option_four = ""
        correct_choice_number = 1
        sample_answer = ""
        if question_type == "Multiple choice":
            option_one = st.text_input("Answer choice 1")
            option_two = st.text_input("Answer choice 2")
            option_three = st.text_input("Answer choice 3")
            option_four = st.text_input("Answer choice 4")
            correct_choice_number = st.selectbox(
                "Which choice is correct?", [1, 2, 3, 4], format_func=lambda number: f"Choice {number}"
            )
        else:
            sample_answer = st.text_area(
                "Sample answer / marking guide",
                placeholder="List the ideas a strong answer should include. Students will see this after finishing the test.",
            )
        explanation = st.text_area(
            "Feedback note (optional)",
            placeholder="Add a short explanation students will see after finishing.",
        )
        saved_question = st.form_submit_button("Save practice question", width="stretch")

    if saved_question:
        options = [option_one, option_two, option_three, option_four]
        try:
            create_quiz_question(
                selected_course["id"],
                question_topic,
                question_text,
                options,
                options[correct_choice_number - 1].strip(),
                explanation,
                "multiple_choice" if question_type == "Multiple choice" else "short_answer",
                achievement_category,
                int(question_marks),
                sample_answer,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Practice question saved!")
            st.rerun()

multiple_choice_test_questions = [
    question for question in quiz_questions
    if question.get("question_type", "multiple_choice") == "multiple_choice"
]
short_answer_test_questions = [
    question for question in quiz_questions
    if question.get("question_type") == "short_answer"
]

# Short-answer practice is separate from the multiple-choice quiz and uses AI feedback.
if short_answer_test_questions:
    with st.expander("Practise short answers with AI marking", expanded=False):
        st.caption(
            "Write a response, then Gemini marks it against the saved marking guide. "
            "This is practice feedback, not an official teacher mark."
        )
        maximum_short_answer_count = min(10, len(short_answer_test_questions))
        if maximum_short_answer_count == 1:
            short_answer_count = 1
            st.caption("This selection currently has 1 saved short-answer question.")
        else:
            short_answer_count = st.slider(
                "Short-answer questions to practise",
                min_value=1,
                max_value=maximum_short_answer_count,
                value=min(3, maximum_short_answer_count),
                key="short_answer_practice_count",
            )
        active_short_answers = short_answer_test_questions[:short_answer_count]
        with st.form("take_short_answer_practice_form"):
            short_responses: dict[int, str] = {}
            for number, question in enumerate(active_short_answers, start=1):
                st.markdown(f"**{number}. {question['question']}**")
                st.caption(
                    f"{question.get('achievement_category', 'Knowledge & Understanding')} "
                    f"· {question.get('marks', 1)} mark(s) · {question['topic']}"
                )
                short_responses[question["id"]] = st.text_area(
                    "Your response", key=f"short_answer_response_{question['id']}", height=150
                )
            submitted_short_answers = st.form_submit_button("Get AI feedback", width="stretch")

        if submitted_short_answers:
            api_key = gemini_api_key()
            if not api_key:
                st.error("Add GEMINI_API_KEY to Streamlit secrets before using AI marking.")
            elif any(not response.strip() for response in short_responses.values()):
                st.error("Write a response for every question before asking for feedback.")
            else:
                try:
                    results = []
                    with st.spinner("Marking your practice responses..."):
                        for question in active_short_answers:
                            result = grade_short_answer(
                                api_key,
                                question["question"],
                                short_responses[question["id"]],
                                str(question.get("sample_answer") or question["correct_answer"]),
                                str(question.get("achievement_category", "Knowledge & Understanding")),
                                int(question.get("marks", 1)),
                            )
                            results.append((question, result))
                    st.session_state["latest_short_answer_result"] = results
                    st.rerun()
                except Exception as error:
                    st.error(f"We could not mark those responses: {error}")

    if "latest_short_answer_result" in st.session_state:
        results = st.session_state.pop("latest_short_answer_result")
        earned_marks = sum(int(result[1]["score"]) for result in results)
        possible_marks = sum(int(question.get("marks", 1)) for question, _ in results)
        st.success(f"AI practice feedback complete: {earned_marks}/{possible_marks} marks.")
        with st.expander("Review AI feedback", expanded=True):
            for question, result in results:
                st.markdown(f"**{question['question']}**")
                st.caption(f"{result['score']}/{question.get('marks', 1)} marks · {question.get('achievement_category')}")
                st.write(result["feedback"])
                if result["strengths"]:
                    st.write("Strengths: " + "; ".join(result["strengths"]))
                if result["next_step"]:
                    st.write("Next step: " + result["next_step"])

# Regular quizzes remain automatically marked multiple-choice practice.
quiz_questions = multiple_choice_test_questions

if not quiz_questions:
    st.info("Add at least one practice question to start a quiz.")
else:
    if "latest_quiz_result" in st.session_state:
        score, total, feedback = st.session_state.pop("latest_quiz_result")
        st.success(f"Quiz complete: {score}/{total} correct.")
        with st.expander("Review this quiz", expanded=False):
            for item in feedback:
                status = "✅ Correct" if item["correct"] else "❌ Review this one"
                st.markdown(f"**{status}: {item['question']}**")
                st.write(f"Your answer: {item['selected_answer']}")
                if not item["correct"]:
                    st.write(f"Correct answer: {item['correct_answer']}")
                if item["explanation"]:
                    st.caption(item["explanation"])

    if recent_quiz_sessions:
        with st.expander(f"Recent quizzes ({len(recent_quiz_sessions)})", expanded=False):
            for session in recent_quiz_sessions:
                topics = ", ".join(session["topics"]) or "Mixed topics"
                st.write(
                    f"**{session['score']}/{session['total_questions']}** · {topics} · {session['completed_at']}"
                )

with st.expander(
        "Practice saved topic questions",
        expanded=bool(st.session_state.pop("open_practice_quiz", False)),
    ):
        all_topics = sorted({str(question["topic"]) for question in quiz_questions})
        quiz_style = st.radio(
        "Practice mode",
            ["Adaptive review", "Choose a topic"],
            horizontal=True,
            help="Adaptive review puts your lowest-scoring topics first.",
        )
        if quiz_style == "Choose a topic":
            preferred_topic = st.session_state.pop("preferred_quiz_topic", None)
            selected_index = all_topics.index(preferred_topic) if preferred_topic in all_topics else 0
            requested_topic = st.selectbox("Topic", all_topics, index=selected_index)
            quiz_candidates = [
                question for question in quiz_questions if question["topic"] == requested_topic
            ]
            st.caption(f"This quiz uses only {requested_topic} questions.")
        else:
            accuracy_by_topic = {item["topic"]: item["accuracy"] for item in topic_stats}
            quiz_candidates = sorted(
                quiz_questions,
                key=lambda question: (
                    accuracy_by_topic.get(question["topic"], 50),
                    question["topic"],
                    question["id"],
                ),
            )
            if topic_stats:
                weak_topic_names = [
                    str(item["topic"]) for item in topic_stats if item["accuracy"] < 70
                ]
                if weak_topic_names:
                    st.caption(
                        "Adaptive review prioritizes your weak topics first: **"
                        + ", ".join(weak_topic_names)
                        + "**."
                    )
                else:
                    st.caption("Adaptive review balances your topics because your recorded scores are 70% or higher.")
            else:
                st.caption("Answer a few quizzes first; then adaptive review will learn your weaker topics.")

        maximum_quiz_size = min(15, len(quiz_candidates))
        if maximum_quiz_size == 0:
            quiz_size = 0
            st.info(
                "There are no multiple-choice questions for this selection yet. "
                "Generate some questions or choose a different topic."
            )
        elif maximum_quiz_size == 1:
            quiz_size = 1
            st.caption("This selection currently has 1 saved question.")
        else:
            quiz_size = st.slider(
                "Questions in this practice quiz",
                min_value=1,
                max_value=maximum_quiz_size,
                value=min(5, maximum_quiz_size),
            )
        active_quiz_questions = quiz_candidates[:quiz_size]

        with st.form("take_quiz_form"):
            selected_answers: dict[int, str] = {}
            for number, question in enumerate(active_quiz_questions, start=1):
                st.markdown(f"**{number}. {question['question']}**")
                st.caption(f"Topic: {question['topic']}")
                selected_answers[question["id"]] = st.radio(
                    "Choose an answer",
                    question["options"],
                    index=None,
                    key=f"quiz_answer_{question['id']}",
                )
            submitted_quiz = st.form_submit_button(
                "Submit quiz", width="stretch", disabled=not active_quiz_questions
            )

        if submitted_quiz:
            if any(answer is None for answer in selected_answers.values()):
                st.error("Answer every question before submitting the quiz.")
            else:
                score = 0
                feedback = []
                questions_by_id = {question["id"]: question for question in active_quiz_questions}
                for question_id, selected_answer in selected_answers.items():
                    question = questions_by_id[question_id]
                    correct = selected_answer == question["correct_answer"]
                    record_quiz_attempt(question_id, selected_answer, correct)
                    score += int(correct)
                    feedback.append(
                        {
                            "question": question["question"],
                            "selected_answer": selected_answer,
                            "correct_answer": question["correct_answer"],
                            "correct": correct,
                            "explanation": question.get("explanation", ""),
                        }
                    )
                record_quiz_session(
                    selected_course["id"],
                    score,
                    len(active_quiz_questions),
                    [str(question["topic"]) for question in active_quiz_questions],
                )
                st.session_state["latest_quiz_result"] = (score, len(active_quiz_questions), feedback)
                st.rerun()

if topic_stats:
    st.subheader("Topic progress")
    st.write("These scores show which topics you should revisit before your next quiz.")
    st.dataframe(
        [
            {
                "Topic": topic["topic"],
                "Answers recorded": topic["attempts"],
                "Accuracy": f"{topic['accuracy']}%",
            }
            for topic in topic_stats
        ],
        width="stretch",
        hide_index=True,
    )

if attempt_history:
    st.download_button(
        "Download progress report (CSV)",
        data=make_progress_csv(attempt_history),
        file_name=f"{selected_course['name'].replace(' ', '_').lower()}_progress.csv",
        mime="text/csv",
    )

st.divider()
with st.expander("About StudySpring and your privacy"):
    st.write(
        "On a personal computer, StudySpring stores courses, notes, flashcards, and quiz progress "
        "in a local SQLite database. On the hosted site, durable storage must be configured by the "
        "site owner; do not rely on a free-hosted session as your only copy of important study work. "
        "AI question generation is done through Google Gemini."
    )
