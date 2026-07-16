"""Independent application destinations for the StudySpring shell."""

from __future__ import annotations

from datetime import date
from io import BytesIO
import os

import streamlit as st
from pypdf import PdfReader

from components.ui import empty_state, open_course, page_header, status_banner
from database import (
    cancel_pdf_import_job, course_attempt_history, course_quiz_stats, course_topic_stats,
    create_course, create_study_note, delete_course, install_course_pack, list_courses,
    list_flashcards, list_pdf_import_jobs, list_pdf_import_pages, list_quiz_questions,
    list_recent_quiz_sessions, list_study_notes, record_quiz_attempt, save_generated_material,
)
from gemini_client import GeminiRequestError, generate_study_material
from services.course_pack_service import CoursePackError, lesson_text, list_course_packs
from services.pdf_service import STANDARD_PDF_MAX_MB, PdfImportError, extract_embedded_text, inspect_pdf, validate_pdf_upload
from services.pdf_service import TEXTBOOK_PDF_MAX_MB
from services.textbook_import_service import process_next_textbook_batch, process_textbook_range, start_textbook_import


def _gemini_key() -> str | None:
    """Read the optional private key without exposing it in the interface."""
    try:
        return st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    except Exception:
        return os.getenv("GEMINI_API_KEY")


def _courses() -> list[dict[str, object]]:
    return [dict(course) for course in list_courses()]


def _selected_course() -> dict[str, object] | None:
    courses = _courses()
    if not courses:
        return None
    saved = st.session_state.get("selected_course_id")
    query_value = st.query_params.get("course")
    if query_value and str(query_value).isdigit():
        saved = int(str(query_value))
    index = next((i for i, course in enumerate(courses) if course["id"] == saved), 0)
    course = st.selectbox("Current course", courses, index=index, format_func=lambda item: f"{item['name']} · {item['subject']}")
    st.session_state["selected_course_id"] = course["id"]
    st.query_params["course"] = str(course["id"])
    return course


def render_home() -> None:
    page_header("Today", "A focused starting point for your next study session.")
    course = _selected_course()
    if not course:
        empty_state("Start with a course", "Install a course from Course Library or create a blank course in My Courses.")
        return
    notes, cards = list_study_notes(course["id"]), list_flashcards(course["id"])
    attempts, score = course_quiz_stats(course["id"])
    metrics = st.columns(3)
    metrics[0].metric("Study materials", len(notes)); metrics[1].metric("Flashcards", len(cards)); metrics[2].metric("Average score", "—" if score is None else f"{score:.0f}%")
    st.subheader("Continue studying")
    if notes:
        st.write(f"Pick up **{notes[0]['title']}** in {course['name']}.")
        if st.button("Open Learn", type="primary"):
            st.session_state["active_page"] = "Learn"; st.rerun()
    else:
        status_banner("info", "Import class material or open a Course Pack lesson to begin.")
    weak = course_topic_stats(course["id"])
    st.subheader("Your focus")
    if weak:
        item = weak[0]; st.warning(f"Review **{item['topic']}** next — {item['accuracy']}% across {item['attempts']} attempts.")
    else:
        st.caption("Complete a quiz to unlock topic recommendations.")
    if attempts:
        st.caption(f"You have recorded {attempts} practice answer(s).")


def render_courses() -> None:
    page_header("My Courses", "Create, open, and manage the courses in your study workspace.")
    with st.expander("Create blank course"):
        with st.form("shell_create_course", clear_on_submit=True):
            name = st.text_input("Course name"); subject = st.text_input("Subject"); exam = st.date_input("Exam date", value=None)
            submitted = st.form_submit_button("Create course")
        if submitted:
            try: course_id = create_course(name, subject, exam.isoformat() if exam else None)
            except ValueError as error: st.error(str(error))
            else: st.session_state["selected_course_id"] = course_id; st.success("Blank course created."); st.rerun()
    courses = _courses()
    if not courses: empty_state("No courses yet", "Create a blank course or install a Course Pack."); return
    query = st.text_input("Search your courses", placeholder="Search by name or subject")
    for course in courses:
        if query and query.lower() not in f"{course['name']} {course['subject']}".lower(): continue
        with st.container(border=True):
            left, right = st.columns([4, 1]); left.subheader(str(course["name"])); left.caption(str(course["subject"]))
            if course.get("is_preinstalled"): left.caption("StudySpring Course Pack")
            right.button("Open", key=f"open_course_{course['id']}", on_click=open_course, args=(int(course["id"]),))
            if not course.get("is_preinstalled") and st.button("Remove", key=f"remove_course_{course['id']}"):
                delete_course(course["id"]); st.rerun()


def render_library() -> None:
    page_header("Course Library", "Discover original StudySpring Course Packs.")
    try: packs = list_course_packs()
    except CoursePackError: packs = []; status_banner("error", "Course Library is unavailable. Try again later.")
    query = st.text_input("Search Course Library", placeholder="Search course, subject, or code")
    installed = {course.get("course_pack_id", "") for course in _courses()}
    for pack in packs:
        if query and query.lower() not in f"{pack['title']} {pack['subject']} {pack['course_code']}".lower(): continue
        with st.container(border=True):
            st.subheader(f"{pack['course_code']} · {pack['title']}")
            st.caption(f"{pack['curriculum']} · Grade {pack['grade']} · v{pack['version']}")
            st.write(str(pack["description"]))
            st.caption("Includes: " + ", ".join(str(unit["title"]) for unit in pack["units"]))
            if pack["id"] in installed: st.success("Installed")
            elif st.button("Install course pack", key=f"shell_install_{pack['id']}"):
                try: course_id = install_course_pack(pack, [(unit, lesson_text(pack, unit)) for unit in pack["units"]])
                except (CoursePackError, ValueError): status_banner("error", "Nothing was installed. Please try again.")
                else: st.session_state["selected_course_id"] = course_id; st.success("Course Pack installed."); st.rerun()


def render_imports() -> None:
    page_header("Imports", "Add notes and PDFs to the current course. Imported material stays editable.")
    course = _selected_course()
    if not course: empty_state("Choose a course first", "Open My Courses to create or select a course."); return
    with st.container(border=True):
        st.subheader("Paste notes")
        with st.form("shell_paste_notes", clear_on_submit=True):
            title = st.text_input("Title"); content = st.text_area("Notes", height=180); save = st.form_submit_button("Save notes")
        if save:
            try: create_study_note(course["id"], title, content, source_group="personal_note")
            except ValueError as error: st.error(str(error))
            else: st.success("Notes saved."); st.rerun()
    with st.container(border=True):
        st.subheader("Readable PDF")
        upload = st.file_uploader(f"Choose a PDF (up to {STANDARD_PDF_MAX_MB} MB)", type=["pdf"], key="shell_pdf")
        if upload and st.button("Extract readable PDF text"):
            try:
                data = upload.getvalue(); validate_pdf_upload(upload.name, data, STANDARD_PDF_MAX_MB); info = inspect_pdf(upload.name, data, STANDARD_PDF_MAX_MB)
                text = "\n\n".join(value for _, value in extract_embedded_text(data, 1, min(info.page_count, 20))).strip()
                if not text: raise PdfImportError("No readable text was found. Use a scanned-textbook import instead.")
                st.session_state["import_preview"] = {"title": upload.name.removesuffix(".pdf"), "content": text}
            except (PdfImportError, ValueError) as error: st.error(str(error))
    with st.container(border=True):
        st.subheader("Import your own material")
        st.caption("Upload a textbook once, then choose the whole book or a smaller section. StudySpring handles safe page batches internally.")
        textbook = st.file_uploader(
            f"Choose a textbook PDF (up to {TEXTBOOK_PDF_MAX_MB} MB)", type=["pdf"], key="shell_textbook_pdf"
        )
        if textbook:
            try:
                textbook_data = textbook.getvalue()
                details = inspect_pdf(textbook.name, textbook_data, TEXTBOOK_PDF_MAX_MB)
                st.caption(f"{details.page_count} pages · {details.file_size_bytes / 1024 / 1024:.1f} MB · {details.document_kind} ({details.readable_text_percentage}% readable sample)")
                mode = st.radio("What would you like to import?", ["Entire textbook", "Selected pages"], horizontal=True, key="shell_textbook_mode")
                if mode == "Entire textbook":
                    first_page, last_page = 1, details.page_count
                    st.caption(f"All {details.page_count} pages will be added to one import job.")
                else:
                    first, last = st.columns(2)
                    first_page = first.number_input("First page", min_value=1, max_value=details.page_count, value=1, key="shell_textbook_first")
                    last_page = last.number_input("Last page", min_value=1, max_value=details.page_count, value=min(details.page_count, 20), key="shell_textbook_last")
                    st.caption(f"Selected range: {int(last_page) - int(first_page) + 1} page(s).")
                if st.button("Start import", type="primary", key="shell_process_textbook"):
                    progress = st.progress(0, text="Preparing selected pages…")
                    def update(done: int, total: int, message: str) -> None:
                        progress.progress(done / total if total else 0, text=message)
                    if mode == "Entire textbook":
                        job_id, _ = start_textbook_import(course_id=int(course["id"]), filename=textbook.name, pdf_bytes=textbook_data)
                        texts, failed, finished = process_next_textbook_batch(job_id=job_id, pdf_bytes=textbook_data, api_key=_gemini_key(), progress=update)
                        if not finished:
                            status_banner("info", "The first safe batch is saved. Re-upload the same PDF later to resume; completed pages will be skipped.")
                    else:
                        texts, failed = process_textbook_range(
                            course_id=int(course["id"]), filename=textbook.name, pdf_bytes=textbook_data,
                            first_page=int(first_page), last_page=int(last_page), api_key=_gemini_key(), progress=update,
                        )
                    if texts:
                        st.session_state["import_preview"] = {"title": textbook.name.removesuffix(".pdf"), "content": "\n\n".join(texts)}
                    if failed:
                        status_banner("warning", f"Saved the pages that could be read. Page(s) {', '.join(map(str, failed))} can be retried from the processing queue.")
                    elif texts:
                        status_banner("success", "Selected pages are ready to review and save.")
            except (PdfImportError, ValueError) as error:
                status_banner("error", str(error))
    preview = st.session_state.get("import_preview")
    if preview:
        with st.form("shell_import_preview"):
            title = st.text_input("Review title", value=preview["title"]); text = st.text_area("Review extracted text", value=preview["content"], height=240); save = st.form_submit_button("Save reviewed material")
        if save:
            try: create_study_note(course["id"], title, text, source_group="imported_material")
            except ValueError as error: st.error(str(error))
            else:
                del st.session_state["import_preview"]
                st.session_state["active_page"] = "Learn"
                st.session_state["primary_navigation"] = "Learn"
                st.success("Material saved. Open Learn to create flashcards and practice.")
                st.rerun()
    st.subheader("Processing queue")
    jobs = list_pdf_import_jobs(course["id"])
    if not jobs: st.caption("No textbook jobs for this course yet.")
    for job in jobs:
        pages = list_pdf_import_pages(job["id"]); st.write(f"**{job['filename']}** · {job['status']}")
        st.caption(" · ".join(f"p{page['page_number']}: {page['status']}" for page in pages))
        if job["status"] not in {"completed", "cancelled"} and st.button("Cancel remaining pages", key=f"shell_cancel_{job['id']}"):
            cancel_pdf_import_job(job["id"]); st.rerun()


def render_learn() -> None:
    page_header("Learn", "Read lessons, review flashcards, and practise questions.")
    course = _selected_course()
    if not course: empty_state("Choose a course first", "Install a Course Pack or create a blank course."); return
    tabs = st.tabs(["Lessons", "Flashcards", "Practice"])
    with tabs[0]:
        notes = list_study_notes(course["id"])
        if not notes: empty_state("No lessons yet", "Import notes or install a Course Pack.")
        for note in notes:
            with st.expander(note["title"]):
                st.markdown(note["content"])
                if note["source_group"] != "lesson":
                    if st.button("Generate flashcards and practice", key=f"generate_note_{note['id']}"):
                        key = _gemini_key()
                        if not key:
                            status_banner("info", "Study material generation needs the optional private Gemini key. Your notes are still saved and available to study.")
                        else:
                            try:
                                material = generate_study_material(key, str(note["content"]))
                                save_generated_material(int(course["id"]), int(note["id"]), material)
                            except GeminiRequestError as error:
                                status_banner("warning", str(error))
                            except (ValueError, RuntimeError) as error:
                                status_banner("error", str(error))
                            else:
                                status_banner("success", "Flashcards and practice questions were saved to this course.")
    with tabs[1]:
        cards = list_flashcards(course["id"])
        if not cards: empty_state("No flashcards yet", "Course Packs and your own study work can add flashcards.")
        for card in cards: st.markdown(f"**{card['front']}**\n\n{card['back']}")
    with tabs[2]:
        questions = [question for question in list_quiz_questions(course["id"]) if question["question_type"] == "multiple_choice"]
        target_topic = st.session_state.get("target_review_topic")
        if target_topic:
            questions = [question for question in questions if question["topic"] == target_topic]
            st.info(f"Targeted review: {target_topic}")
        if not questions: empty_state("No practice questions yet", "Install a pack or add questions from your notes.")
        for question in questions:
            answer = st.radio(question["question"], question["options"], index=None, key=f"shell_question_{question['id']}")
            if answer and st.button("Check answer", key=f"shell_check_{question['id']}"):
                correct = answer == question["correct_answer"]; record_quiz_attempt(question["id"], answer, correct)
                status_banner("success" if correct else "warning", "Correct." if correct else f"Review: {question['correct_answer']}. {question['explanation']}")


def render_progress() -> None:
    page_header("Progress", "See what is improving and what deserves another review.")
    course = _selected_course()
    if not course: empty_state("Choose a course first", "Progress appears after you start studying."); return
    attempts, score = course_quiz_stats(course["id"]); cards = list_flashcards(course["id"]); notes = list_study_notes(course["id"])
    cols = st.columns(3); cols[0].metric("Answers", attempts); cols[1].metric("Accuracy", "—" if score is None else f"{score:.0f}%"); cols[2].metric("Flashcards", len(cards))
    st.subheader("Focus on weak topics")
    topics = course_topic_stats(course["id"])
    if topics:
        weak_topics = [item for item in topics if item["accuracy"] < 70]
        if weak_topics:
            for item in weak_topics:
                with st.container(border=True):
                    st.write(f"**{item['topic']}** — {item['accuracy']}% across {item['attempts']} answer(s)")
                    if st.button("Start targeted practice", key=f"target_{item['topic']}"):
                        st.session_state["target_review_topic"] = item["topic"]
                        st.session_state["active_page"] = "Learn"
                        st.session_state["primary_navigation"] = "Learn"
                        st.rerun()
        else:
            st.success("No weak topics right now — keep practising to maintain your progress.")
        st.subheader("Topic mastery")
        st.dataframe(topics, width="stretch", hide_index=True)
    else: st.caption("Complete a practice question to start tracking mastery.")
    st.subheader("Recent quizzes")
    sessions = list_recent_quiz_sessions(course["id"])
    if sessions:
        for session in sessions: st.write(f"{session['score']}/{session['total_questions']} · {', '.join(session['topics'])}")
    else: st.caption("No completed quizzes yet.")


def render_settings() -> None:
    page_header("Settings", "Privacy and configuration for this StudySpring workspace.")
    st.subheader("Privacy")
    st.info("StudySpring stores local data in SQLite. Render preview data is temporary. Never paste an API key into study notes.")
    st.subheader("AI features")
    st.caption("Gemini is optional. Add GEMINI_API_KEY only through private Streamlit or Render environment settings.")
    st.subheader("Imports")
    st.caption("Readable text is extracted locally. Scanned textbook pages require the configured OCR path or optional Gemini support.")


PAGES = {"Home": render_home, "My Courses": render_courses, "Course Library": render_library, "Imports": render_imports, "Learn": render_learn, "Progress": render_progress, "Settings": render_settings}

def render_page(name: str) -> None:
    PAGES[name]()
