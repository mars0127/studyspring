"""StudySpring: a simple study dashboard built with Streamlit."""

import csv
import math
import os
import random
from datetime import date
from io import BytesIO, StringIO

import streamlit as st
from pypdf import PdfReader

from database import (
    complete_pdf_import_job,
    cancel_pdf_import_job,
    create_course,
    create_flashcard,
    create_quiz_question,
    create_study_note,
    course_quiz_stats,
    course_attempt_history,
    course_topic_stats,
    delete_course,
    delete_study_note,
    initialize_database,
    install_course_pack,
    list_courses,
    list_flashcards,
    list_quiz_questions,
    list_recent_quiz_sessions,
    list_pdf_import_pages,
    list_pdf_import_jobs,
    list_study_notes,
    record_quiz_attempt,
    record_quiz_session,
    create_or_resume_pdf_import_job,
    save_pdf_import_page,
    update_study_note_organization,
    update_study_note,
    update_course,
)
from gemini_client import (
    DEFAULT_MODEL,
    GeminiRequestError,
    create_gemini_client,
    extract_text_from_image,
    extract_text_from_images,
    grade_short_answer,
    generate_questions,
)
from components.design import apply_design_system
from components.ui import course_card, empty_state, page_header, page_navigation, status_banner
from services.pdf_service import (
    MAX_PROCESSING_PAGES,
    STANDARD_PDF_MAX_MB,
    TEXTBOOK_PDF_MAX_MB,
    PdfImportError,
    extract_embedded_text,
    inspect_pdf,
    render_page_png,
    validate_pdf_upload,
    validate_page_range,
)
from services.course_pack_service import CoursePackError, lesson_text, list_course_packs


MAX_SELECTED_SCANNED_PDF_PAGES = MAX_PROCESSING_PAGES


st.set_page_config(page_title="StudySpring", page_icon="🌱", layout="wide")
apply_design_system()
initialize_database()


def gemini_api_key() -> str | None:
    """Read a private key from Streamlit secrets or the local environment."""
    try:
        secret_value = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        # A missing or malformed secrets file should not take down the whole app.
        secret_value = None
    return secret_value or os.getenv("GEMINI_API_KEY")


def course_label(course: dict[str, object]) -> str:
    """Format a short label for Streamlit's course picker."""
    return f"{course['name']} · {course['subject']}"


def extract_pdf_text(file_bytes: bytes) -> str:
    """Extract readable text from a text-based PDF upload."""
    reader = PdfReader(BytesIO(file_bytes))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()


def render_scanned_pdf_pages(file_bytes: bytes, first_page: int, last_page: int) -> list[bytes]:
    """Render a few selected PDF pages to PNG images for AI transcription."""
    try:
        import fitz
    except ImportError as error:
        raise RuntimeError("Scanned-PDF support is not installed. Run: pip install -r requirements.txt") from error

    document = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        if last_page > len(document):
            raise ValueError(f"This PDF has {len(document)} page(s). Choose a smaller ending page.")
        page_images = []
        for page_number in range(first_page - 1, last_page):
            page = document.load_page(page_number)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            page_images.append(pixmap.tobytes("png"))
        return page_images
    finally:
        document.close()


def scanned_pdf_page_count(file_bytes: bytes) -> int:
    """Count PDF pages without attempting text extraction."""
    import fitz

    document = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        return len(document)
    finally:
        document.close()


def transcribe_scanned_page_batch(
    api_key: str, image_batch: list[bytes], first_page: int, client=None
) -> str:
    """Read a batch, retrying one page at a time when a combined request is empty."""
    try:
        return extract_text_from_images(api_key, image_batch, client=client)
    except ValueError as error:
        if "could not find readable text" not in str(error):
            raise
        page_texts = []
        for offset, image_page in enumerate(image_batch):
            try:
                page_texts.append(extract_text_from_image(api_key, image_page, "image/png", client=client))
            except ValueError:
                page_texts.append(f"[Page {first_page + offset} could not be read.]")
        return "\n\n".join(page_texts)


def process_textbook_range(
    *,
    course_id: int,
    filename: str,
    pdf_bytes: bytes,
    first_page: int,
    last_page: int,
    api_key: str | None,
    progress,
) -> tuple[list[str], list[int]]:
    """Process a small range and save every page result before moving on."""
    inspection = inspect_pdf(filename, pdf_bytes)
    validate_page_range(first_page, last_page, inspection.page_count)
    job_id = create_or_resume_pdf_import_job(
        course_id, inspection.document_hash, filename, first_page, last_page
    )
    saved_pages = {page["page_number"]: page for page in list_pdf_import_pages(job_id)}
    scan_client = create_gemini_client(api_key) if api_key else None
    completed_text: list[str] = []
    failed_pages: list[int] = []
    page_total = last_page - first_page + 1
    for position, (page_number, embedded_text) in enumerate(
        extract_embedded_text(pdf_bytes, first_page, last_page), start=1
    ):
        existing = saved_pages.get(page_number, {})
        if existing.get("status") == "completed":
            completed_text.append(str(existing.get("extracted_text", "")))
            continue
        progress.progress(
            (position - 1) / page_total,
            text=f"Processing page {page_number} of {last_page}...",
        )
        try:
            if len(embedded_text) >= 40:
                text = embedded_text
                method = "embedded_text"
            else:
                if not api_key:
                    raise PdfImportError(
                        "These pages need AI reading. Add the private Gemini key, or OCR the PDF before uploading it."
                    )
                image_page = render_page_png(pdf_bytes, page_number)
                text = extract_text_from_image(api_key, image_page, "image/png", client=scan_client)
                method = "gemini_ocr"
            save_pdf_import_page(job_id, page_number, "completed", method, text)
            completed_text.append(text)
        except Exception as error:
            save_pdf_import_page(job_id, page_number, "failed", error_message=str(error))
            failed_pages.append(page_number)
            if isinstance(error, GeminiRequestError):
                break
    complete_pdf_import_job(job_id)
    progress.progress(1.0, text="Pages processed.")
    return completed_text, failed_pages


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
active_page = page_navigation(["Home", "My Courses", "Course Library", "Import Material", "Study", "Progress", "Settings"])

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
    st.subheader("Course Library")
    st.caption("Install an original StudySpring course pack. Your personal notes stay separate.")
    try:
        available_packs = list_course_packs()
    except CoursePackError:
        available_packs = []
        st.warning("The Course Library is temporarily unavailable.")
    for pack in available_packs:
        with st.expander(f"{pack['course_code']} · {pack['title']}"):
            st.write(str(pack["description"]))
            st.caption(f"{pack['curriculum']} · Grade {pack['grade']} · Version {pack['version']}")
            st.write("Includes: " + ", ".join(str(unit["title"]) for unit in pack["units"]))
            if st.button("Install course pack", key=f"install_pack_{pack['id']}", width="stretch"):
                try:
                    installed_course_id = install_course_pack(
                        pack, [(unit, lesson_text(pack, unit)) for unit in pack["units"]]
                    )
                except (CoursePackError, ValueError):
                    st.error("StudySpring could not install that course pack. Nothing was changed.")
                else:
                    st.success("Course pack installed. You can now add your own notes and practise from it.")
                    st.session_state["selected_course_id"] = installed_course_id
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
study_notes = list_study_notes(selected_course["id"])
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
    material_section = st.radio(
        "Material section",
        ["Student notes & teacher material / lesson", "Course textbook"],
        horizontal=True,
        help="Keep day-to-day class material separate from the textbook used for the whole course.",
    )
    new_note_source_group = "textbook" if material_section == "Course textbook" else "lesson"
    if new_note_source_group == "textbook":
        st.caption("Add pages, chapters, or the complete textbook here. It can be used by itself or together with lessons in an AI quiz.")
    else:
        st.caption("Add your own notes, teacher handouts, slides, lesson text, or learning-platform material here.")
    material_type = st.selectbox(
        "What are you adding?",
        [
            "Paste text",
            "PDF with selectable text",
            "Photo or handwritten scan",
            "Textbook PDF (inspect and process selected pages)",
        ],
    )
    new_note_unit = ""
    new_note_chapter = ""
    new_note_lesson = ""
    if new_note_source_group == "lesson":
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
    else:
        st.info(
            "Your textbook will be saved as one course-wide source. You do not need to sort a large textbook into units, chapters, or lessons."
        )

    if material_type == "Paste text":
        st.caption("Paste copied text from the material selected above.")
        with st.form("create_note_form", clear_on_submit=True):
            note_title = st.text_input(
                "Textbook name" if new_note_source_group == "textbook" else "Title",
                placeholder="e.g. Grade 12 Kinesiology textbook" if new_note_source_group == "textbook" else "e.g. Cell division chapter",
            )
            note_content = st.text_area("Text", placeholder="Paste the text here...", height=180)
            saved_note = st.form_submit_button("Save material", width="stretch")
        if saved_note:
            try:
                create_study_note(selected_course["id"], note_title, note_content, new_note_unit, new_note_lesson, new_note_chapter, new_note_source_group)
            except ValueError as error:
                st.error(str(error))
            else:
                st.success("Material saved!")
                st.rerun()

    elif material_type == "PDF with selectable text":
        st.caption(f"Use this for a short PDF with selectable text (up to {STANDARD_PDF_MAX_MB} MB).")
        with st.form("upload_pdf_form", clear_on_submit=True):
            uploaded_pdf = st.file_uploader("Choose a PDF", type=["pdf"])
            save_pdf = st.form_submit_button("Extract and save PDF", width="stretch")
        if save_pdf:
            try:
                if uploaded_pdf is None:
                    raise ValueError("Choose a PDF before saving.")
                pdf_bytes = uploaded_pdf.getvalue()
                validate_pdf_upload(uploaded_pdf.name, pdf_bytes, STANDARD_PDF_MAX_MB)
                inspection = inspect_pdf(uploaded_pdf.name, pdf_bytes, STANDARD_PDF_MAX_MB)
                validate_page_range(1, min(inspection.page_count, MAX_PROCESSING_PAGES), inspection.page_count)
                pdf_text = "\n\n".join(
                    text for _, text in extract_embedded_text(
                        pdf_bytes, 1, min(inspection.page_count, MAX_PROCESSING_PAGES)
                    )
                ).strip()
                if not pdf_text:
                    raise ValueError("No selectable text was found. Use the textbook PDF option instead.")
                create_study_note(selected_course["id"], uploaded_pdf.name.removesuffix(".pdf"), pdf_text, new_note_unit, new_note_lesson, new_note_chapter, new_note_source_group)
            except (PdfImportError, ValueError) as error:
                st.error(str(error))
            except Exception:
                st.error("StudySpring could not read that PDF. Try a different file or use the textbook PDF option.")
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
                create_study_note(selected_course["id"], uploaded_image.name.rsplit(".", 1)[0], image_text, new_note_unit, new_note_lesson, new_note_chapter, new_note_source_group)
            except Exception as error:
                st.error(f"We could not read that image: {error}")
            else:
                st.success("Scanned note saved as editable text!")
                st.rerun()

    else:
        st.caption(
            f"Upload a textbook up to {TEXTBOOK_PDF_MAX_MB} MB. StudySpring checks it first, then processes "
            f"at most {MAX_PROCESSING_PAGES} pages per request. Completed pages are saved if a later page fails."
        )
        textbook_pdf = st.file_uploader("Choose a textbook PDF", type=["pdf"], key="textbook_pdf")
        if textbook_pdf is not None:
            try:
                textbook_bytes = textbook_pdf.getvalue()
                textbook_info = inspect_pdf(textbook_pdf.name, textbook_bytes)
                info_left, info_middle, info_right = st.columns(3)
                info_left.metric("Pages", textbook_info.page_count)
                info_middle.metric("File size", f"{textbook_info.file_size_bytes / 1024 / 1024:.1f} MB")
                info_right.metric("Readable sample", f"{textbook_info.readable_text_percentage}%")
                needs_ocr = textbook_info.document_kind != "text-readable"
                st.info(
                    f"This looks {textbook_info.document_kind}. "
                    + ("Some pages may need AI reading." if needs_ocr else "Most selected pages can be read directly.")
                )
                with st.form("process_textbook_range_form"):
                    first_page = st.number_input("First page", min_value=1, max_value=textbook_info.page_count, value=1, step=1)
                    last_page = st.number_input("Last page", min_value=1, max_value=textbook_info.page_count, value=min(MAX_PROCESSING_PAGES, textbook_info.page_count), step=1)
                    save_textbook_pages = st.form_submit_button("Process selected pages", width="stretch")
                if save_textbook_pages:
                    progress = st.progress(0, text="Preparing selected pages...")
                    page_texts, failed_pages = process_textbook_range(
                        course_id=selected_course["id"], filename=textbook_pdf.name, pdf_bytes=textbook_bytes,
                        first_page=int(first_page), last_page=int(last_page), api_key=gemini_api_key(), progress=progress,
                    )
                    saved_text = "\n\n".join(text for text in page_texts if text.strip())
                    if saved_text:
                        st.session_state["textbook_preview"] = {
                            "course_id": selected_course["id"], "title": f"{textbook_pdf.name.rsplit('.', 1)[0]} pages {first_page}-{last_page}",
                            "content": saved_text,
                        }
                    if failed_pages:
                        st.warning(f"Completed pages are ready to review. Page(s) {', '.join(map(str, failed_pages))} can be retried below.")
                    elif saved_text:
                        st.success("Pages are ready for you to review and save.")
                    else:
                        st.error("No readable text was found in those pages. Try clearer pages or OCR the document first.")
                jobs = list_pdf_import_jobs(selected_course["id"])
                if jobs:
                    with st.expander("Textbook processing history", expanded=False):
                        for job in jobs:
                            pages = list_pdf_import_pages(int(job["id"]))
                            counts = {status: sum(page["status"] == status for page in pages) for status in ("completed", "failed", "pending", "skipped")}
                            st.write(f"**{job['filename']} · pages {job['first_page']}-{job['last_page']}** — {job['status']}")
                            st.caption(f"{counts['completed']} completed · {counts['failed']} failed · {counts['pending']} waiting · {counts['skipped']} skipped")
                            for page in pages:
                                st.caption(f"Page {page['page_number']}: {page['status']} · {page['extraction_method'] or 'not processed'}")
                            if job["status"] not in {"completed", "cancelled"} and st.button("Cancel remaining pages", key=f"cancel_import_{job['id']}"):
                                cancel_pdf_import_job(int(job["id"]))
                                st.rerun()
                            if counts["failed"] and textbook_pdf is not None and st.button("Retry failed pages", key=f"retry_import_{job['id']}"):
                                progress = st.progress(0, text="Retrying unfinished pages...")
                                process_textbook_range(course_id=selected_course["id"], filename=textbook_pdf.name, pdf_bytes=textbook_bytes, first_page=int(job["first_page"]), last_page=int(job["last_page"]), api_key=gemini_api_key(), progress=progress)
                                st.rerun()
                preview = st.session_state.get("textbook_preview")
                if preview and preview["course_id"] == selected_course["id"]:
                    with st.form("save_textbook_preview"):
                        st.caption("Review or correct the extracted text before saving it to this course.")
                        preview_title = st.text_input("Material title", value=str(preview["title"]))
                        corrected_text = st.text_area("Extracted text", value=str(preview["content"]), height=280)
                        save_preview = st.form_submit_button("Save reviewed textbook material", width="stretch")
                    if save_preview:
                        try:
                            create_study_note(selected_course["id"], preview_title, corrected_text, source_group="textbook")
                        except ValueError as error:
                            st.error(str(error))
                        else:
                            del st.session_state["textbook_preview"]
                            st.success("Reviewed textbook material saved.")
                            st.rerun()
            except (PdfImportError, ValueError) as error:
                st.error(str(error))
            except Exception:
                st.error("StudySpring could not process that textbook. Your completed pages, if any, were saved safely.")

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
            combined_section = st.selectbox(
                "Save combined material in",
                ["Student notes & teacher material / lesson", "Course textbook"],
            )
            remove_originals = st.checkbox("Remove the original notes after combining them")
            combine_notes = st.form_submit_button("Combine selected notes", width="stretch")
        if combine_notes:
            try:
                if len(selected_note_ids) < 2:
                    raise ValueError("Choose at least two notes to combine.")
                combined_content = "\n\n".join(
                    f"--- {note_by_id[note_id]['title']} ---\n{note_by_id[note_id]['content']}"
                    for note_id in selected_note_ids
                )
                create_study_note(
                    selected_course["id"],
                    combined_title,
                    combined_content,
                    combined_unit,
                    combined_lesson,
                    combined_chapter,
                    "textbook" if combined_section == "Course textbook" else "lesson",
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
    filter_left, filter_middle, filter_right = st.columns(3)
    section_filter = filter_left.selectbox(
        "View material section",
        ["All material", "Student notes & teacher material / lesson", "Course textbook"],
    )
    unit_filter = filter_middle.selectbox("View notes by unit", ["All units", "Unsorted"] + available_units)
    chapter_filter = filter_right.selectbox("View notes by chapter", ["All chapters", "Unsorted"] + available_chapters)
    visible_notes = [
        note for note in study_notes
        if (section_filter == "All material"
            or (section_filter == "Course textbook" and note["source_group"] == "textbook")
            or (section_filter == "Student notes & teacher material / lesson" and note["source_group"] != "textbook"))
        and (unit_filter == "All units" or (unit_filter == "Unsorted" and not note["unit"]) or note["unit"] == unit_filter)
        and (chapter_filter == "All chapters" or (chapter_filter == "Unsorted" and not note["chapter"]) or note["chapter"] == chapter_filter)
    ]
    visible_notes.sort(key=lambda note: (note["unit"], note["chapter"], note["lesson"], note["title"]))
    for note in visible_notes:
        location = " · ".join(item for item in [note["unit"], note["chapter"], note["lesson"]] if item)
        note_heading = f"{location} — {note['title']}" if location else note["title"]
        with st.expander(note_heading):
            st.write(note["content"])
            st.caption("Edit the title, content, or organization below.")
            with st.form(f"edit_note_{note['id']}"):
                updated_title = st.text_input("Note title", value=note["title"], key=f"note_title_{note['id']}")
                updated_content = st.text_area("Note content", value=note["content"], height=180, key=f"note_content_{note['id']}")
                organization_left, organization_middle, organization_right = st.columns(3)
                updated_unit = organization_left.text_input("Unit", value=note["unit"], key=f"note_unit_{note['id']}")
                updated_chapter = organization_middle.text_input("Chapter", value=note["chapter"], key=f"note_chapter_{note['id']}")
                updated_lesson = organization_right.text_input("Lesson", value=note["lesson"], key=f"note_lesson_{note['id']}")
                updated_section = st.selectbox(
                    "Material section",
                    ["Student notes & teacher material / lesson", "Course textbook"],
                    index=1 if note["source_group"] == "textbook" else 0,
                    key=f"note_section_{note['id']}",
                )
                save_note = st.form_submit_button("Save note changes")
            if save_note:
                try:
                    update_study_note(
                        note["id"], updated_title, updated_content,
                        updated_unit, updated_chapter, updated_lesson,
                        "textbook" if updated_section == "Course textbook" else "lesson",
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
    with st.expander("Generate questions from notes with AI"):
        st.caption(
            "Choose one note, several notes, or every note in this course. Only those chosen notes are sent to Google Gemini."
        )
        api_key = gemini_api_key()
        if api_key:
            note_options = [dict(note) for note in study_notes]
            def ai_note_label(note: dict[str, object]) -> str:
                location = " · ".join(
                    str(item) for item in [note.get("unit"), note.get("lesson")] if item
                )
                return f"{location} — {note['title']}" if location else str(note["title"])

            source_scope = st.radio(
                "Quiz source",
                [
                    "Student notes & teacher material / lesson",
                    "Course textbook",
                    "Combine both sections",
                    "Choose specific materials",
                ],
                horizontal=True,
            )
            lesson_notes = [note for note in note_options if note.get("source_group") != "textbook"]
            textbook_notes = [note for note in note_options if note.get("source_group") == "textbook"]
            if source_scope == "Choose specific materials":
                selected_notes = st.multiselect(
                    "Choose one or more materials",
                    note_options,
                    format_func=ai_note_label,
                    key="ai_note_selector",
                )
            elif source_scope == "Student notes & teacher material / lesson":
                selected_notes = lesson_notes
                st.info(f"This quiz will use {len(selected_notes)} saved student/teacher material item(s).")
            elif source_scope == "Course textbook":
                selected_notes = textbook_notes
                st.info(f"This quiz will use {len(selected_notes)} saved textbook item(s).")
            else:
                selected_notes = note_options
                st.info(
                    f"This quiz will combine {len(lesson_notes)} lesson item(s) with {len(textbook_notes)} textbook item(s)."
                )

            source_text = "\n\n".join(
                f"--- {ai_note_label(note)} ---\n{note['content']}"
                for note in selected_notes
            )
            if selected_notes:
                st.caption(
                    f"Selected source: {len(selected_notes)} note(s), {len(source_text):,} characters."
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
                f"Recommended for this amount of material: **{recommended_minimum}-{recommended_maximum} questions**."
            )
            question_count = st.slider(
                "How many practice questions do you want?",
                min_value=recommended_minimum,
                max_value=recommended_maximum,
                value=(recommended_minimum + recommended_maximum) // 2,
                help="Longer sources need more questions to cover the important ideas without making one quiz overwhelming.",
            )
            if st.button("Generate AI questions", width="stretch"):
                try:
                    if not selected_notes:
                        raise ValueError("Choose at least one study note first.")
                    with st.spinner("Creating practice questions from your selected study material..."):
                        generated_questions = generate_questions(
                            api_key, source_text, question_count
                        )
                        for generated_question in generated_questions:
                            create_quiz_question(
                                selected_course["id"],
                                generated_question["topic"],
                                generated_question["question"],
                                generated_question["options"],
                                generated_question["correct_answer"],
                                generated_question["explanation"],
                            )
                except Exception as error:
                    st.error(f"We could not generate questions: {error}")
                else:
                    st.success(f"Saved {len(generated_questions)} AI-generated question(s)!")
                    st.rerun()
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

assessment_questions = quiz_questions
multiple_choice_test_questions = [
    question for question in assessment_questions
    if question.get("question_type", "multiple_choice") == "multiple_choice"
]
short_answer_test_questions = [
    question for question in assessment_questions
    if question.get("question_type") == "short_answer"
]

if assessment_questions:
    with st.expander("Take a mock test", expanded=False):
        st.caption(
            "Practise a test-like mix of multiple-choice and short-answer questions. "
            "Short answers show a marking guide after you submit so you can compare your work."
        )
        test_left, test_right = st.columns(2)
        mc_count = test_left.slider(
            "Multiple-choice questions",
            min_value=0,
            max_value=min(20, len(multiple_choice_test_questions)),
            value=min(5, len(multiple_choice_test_questions)),
            key="mock_test_mc_count",
        ) if multiple_choice_test_questions else 0
        short_count = test_right.slider(
            "Short-answer questions",
            min_value=0,
            max_value=min(10, len(short_answer_test_questions)),
            value=min(2, len(short_answer_test_questions)),
            key="mock_test_short_count",
        ) if short_answer_test_questions else 0
        if not short_answer_test_questions:
            st.info("Add short-answer questions above to include Thinking, Communication, or Application practice in a mock test.")

        active_test_questions = (
            multiple_choice_test_questions[:mc_count]
            + short_answer_test_questions[:short_count]
        )
        if active_test_questions:
            with st.form("take_mock_test_form"):
                test_answers: dict[int, str | None] = {}
                for number, question in enumerate(active_test_questions, start=1):
                    st.markdown(f"**{number}. {question['question']}**")
                    st.caption(
                        f"{question.get('achievement_category', 'Knowledge & Understanding')} "
                        f"· {question.get('marks', 1)} mark(s) · {question['topic']}"
                    )
                    if question.get("question_type", "multiple_choice") == "short_answer":
                        test_answers[question["id"]] = st.text_area(
                            "Your response",
                            key=f"mock_short_answer_{question['id']}",
                            height=140,
                        )
                    else:
                        test_answers[question["id"]] = st.radio(
                            "Choose an answer",
                            question["options"],
                            index=None,
                            key=f"mock_mc_answer_{question['id']}",
                        )
                submitted_test = st.form_submit_button("Finish mock test", width="stretch")

            if submitted_test:
                if any(not answer for answer in test_answers.values()):
                    st.error("Answer every question before finishing the test.")
                else:
                    auto_score = 0
                    auto_total = 0
                    test_feedback = []
                    for question in active_test_questions:
                        response = str(test_answers[question["id"]])
                        is_short_answer = question.get("question_type") == "short_answer"
                        if is_short_answer:
                            correct = None
                        else:
                            correct = response == question["correct_answer"]
                            auto_total += int(question.get("marks", 1))
                            auto_score += int(question.get("marks", 1)) if correct else 0
                            record_quiz_attempt(question["id"], response, bool(correct))
                        test_feedback.append({
                            "question": question["question"],
                            "response": response,
                            "correct": correct,
                            "answer": question.get("sample_answer") or question["correct_answer"],
                            "category": question.get("achievement_category", "Knowledge & Understanding"),
                            "marks": question.get("marks", 1),
                            "explanation": question.get("explanation", ""),
                        })
                    if auto_total:
                        record_quiz_session(
                            selected_course["id"], auto_score, auto_total,
                            [str(question["topic"]) for question in active_test_questions],
                        )
                    st.session_state["latest_mock_test_result"] = (auto_score, auto_total, test_feedback)
                    st.rerun()

    if "latest_mock_test_result" in st.session_state:
        auto_score, auto_total, test_feedback = st.session_state.pop("latest_mock_test_result")
        if auto_total:
            st.success(f"Mock test complete: {auto_score}/{auto_total} automatically marked multiple-choice marks.")
        else:
            st.success("Mock test complete. Compare your short answers with the marking guide below.")
        with st.expander("Review mock test", expanded=True):
            for item in test_feedback:
                st.markdown(f"**{item['category']} · {item['marks']} mark(s): {item['question']}**")
                st.write(f"Your response: {item['response']}")
                if item["correct"] is False:
                    st.write(f"Correct answer: {item['answer']}")
                elif item["correct"] is None:
                    st.write(f"Sample answer / marking guide: {item['answer']}")
                if item["explanation"]:
                    st.caption(item["explanation"])

# Short-answer practice is separate from the multiple-choice quiz and uses AI feedback.
if short_answer_test_questions:
    with st.expander("Practise short answers with AI marking", expanded=False):
        st.caption(
            "Write a response, then Gemini marks it against the saved marking guide. "
            "This is practice feedback, not an official teacher mark."
        )
        short_answer_count = st.slider(
            "Short-answer questions to practise",
            min_value=1,
            max_value=min(10, len(short_answer_test_questions)),
            value=min(3, len(short_answer_test_questions)),
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

    with st.expander("Take a practice quiz", expanded=False):
        all_topics = sorted({str(question["topic"]) for question in quiz_questions})
        quiz_style = st.radio(
            "Quiz type",
            ["Adaptive review", "Choose a topic"],
            horizontal=True,
            help="Adaptive review puts your lowest-scoring topics first.",
        )
        if quiz_style == "Choose a topic":
            requested_topic = st.selectbox("Topic", all_topics)
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
        quiz_size = st.slider(
            "Questions in this quiz",
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
            submitted_quiz = st.form_submit_button("Submit quiz", width="stretch")

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
        "StudySpring stores courses, notes, flashcards, and quiz progress in a local SQLite "
        "database on this computer. The core features do not send study material anywhere. "
        "If you use AI question generation, StudySpring sends only the note you selected to "
        f"Google Gemini ({DEFAULT_MODEL}) to create questions."
    )
