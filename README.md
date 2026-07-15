# StudySpring

StudySpring is a beginner-friendly study dashboard. Students can create courses, save typed notes or short PDFs, practise with quizzes, and see which topics need more review. It was made by Mars Sun, Kenneth Wu, and Bernard Kim.

## Version 1 goals

- Create and view courses with optional exam dates
- Paste notes or upload a text-based PDF
- Create and review saved flashcards
- Build and take multiple-choice practice quizzes
- Review answers, explanations, scores, topic-level progress, and an exam countdown
- Follow a daily study plan based on saved cards, quizzes, and topic performance
- Download a personal CSV progress report
- Edit or safely delete a course and its local study data

AI-generated quizzes are planned after this core version works. The current manual quiz builder uses the same database structure that an AI generator will use later.

## Optional cloud AI with Gemini

StudySpring can generate questions from a saved note using Google's Gemini API. Create a Gemini API key, then put it in `.streamlit/secrets.toml`:

```toml
GEMINI_API_KEY = "paste-your-key-here"
```

Keep this file private. Do not commit it to GitHub or show the key in your website. Gemini's free tier has usage limits; the selected note is sent to Google only when you request AI-generated questions.

The same optional Gemini connection can read JPG, PNG, and WEBP scans of notes and save the extracted text as a study note. Use clear, upright images smaller than 10 MB, and check the extracted text before relying on it for studying.

### Textbook PDF imports

StudySpring first inspects a textbook PDF and tells the student its page count, size, and whether sampled pages contain selectable text. It then processes a selected range of **up to 20 pages**. Readable pages are extracted directly; only pages without embedded text are sent to Gemini for transcription. Each page is checkpointed in SQLite before the next page starts, so completed pages survive a later failure and can be retried without repeating the whole range.

The original upload is not stored by the application. On Render's free service, uploads and SQLite data are temporary because the service has no persistent disk. Do not use the public deployment for confidential school records.

For an offline, scanned textbook, OCR it on your own computer first, then upload the resulting searchable PDF or paste selected text. This avoids sending a large document to an AI provider and reduces quota use.

## Planned technology

- Python
- Streamlit for the browser interface
- SQLite for saved courses, notes, and quiz attempts
- Git and GitHub for version history and sharing

## Project structure

```text
studyspring/
  app.py            # The Streamlit website entry point
  database.py       # Database setup and data helpers
  requirements.txt  # Python packages required to run the app
  README.md         # Project overview and setup instructions
  tests/            # Automated checks for saved data
```

## Getting started

1. Install Python 3.11 or newer.
2. Create a virtual environment.
3. Install packages from `requirements.txt`.
4. Run `streamlit run app.py`.

To run the automated checks:

```text
cd studyspring
python -m unittest discover -s tests
```

The next build step is creating the first working Streamlit screen.

## Privacy and sharing

By default, StudySpring keeps study data in `studyspring.db` on the same computer as the app. Do not upload confidential material to a public deployment unless you add authentication, a privacy policy, and secure server-side storage.

The optional Gemini integration sends the selected note to Google's AI service only when you generate questions. For a public deployment, configure the same API key as a private deployment secret; never put it in frontend code or a public repository.

## Environment and deployment

Copy `.env.example` when setting up local environment variables. Never commit `.env` or `.streamlit/secrets.toml`; both are ignored by Git. The Render start command is:

```text
streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```

Render's free tier has limited CPU, memory, request time, and no persistent disk. Keep textbook ranges small, configure `GEMINI_API_KEY` only in Render's private environment settings, and expect the service to sleep when unused.

### Pull-request previews

Render preview deployments are enabled in **Manual** mode. Add the `render-preview` label to a pull request when a temporary hosted review environment is needed. Render exposes `IS_PULL_REQUEST` only in those previews, and StudySpring displays a visible preview banner there. Preview data is temporary SQLite data; do not add production secrets or personal student material to a preview environment.

## Current limitations and next phase

- A public deployment has no student accounts or durable database storage.
- The optional Gemini free tier can return a quota message; wait briefly and retry with fewer pages or less text.
- Course starters are roadmaps, not full installable course packs yet.
- Course Packs are still a pilot system and do not yet include every Ontario course.
## Milestone 1 navigation and course packs

### Application shell

StudySpring now routes its primary destinations through focused page renderers in `pages/views.py`: Home, My Courses, Course Library, Imports, Learn, Progress, and Settings. Each renderer owns one purpose and is selected by centralized navigation in `app.py`. The reusable page header, status, empty-state, and navigation helpers remain in `components/`.

StudySpring now has top-level navigation for Home, My Courses, Course Library, Import Material, Study, Progress, and Settings. The current Streamlit implementation keeps study tools on the selected course dashboard while the application is being progressively separated into view modules; it does not use fragile global widget selectors.

Prebuilt courses are installed only from **Course Library**. The former Ontario starter-course menu has been removed. Students can still create a blank course for their own class.

### Course Pack format

Course Packs are version-controlled, original or openly licensed content. A lesson can be legacy Markdown during migration, but new lessons use JSON `blocks`, including headings, paragraphs, definitions, formulas, worked examples, common mistakes, practice sets, answer keys, flashcards, multiple-choice questions, short-answer questions, resource links, and callouts.

To validate a pack locally:

```powershell
.\.venv\Scripts\python.exe tools\course_pack.py validate course_packs\ontario\mhf4u\manifest.json
```

To create a local authoring scaffold (this is not exposed in the public website):

```powershell
.\.venv\Scripts\python.exe tools\course_pack.py scaffold course_packs\ontario\new-course --id ontario-new-course-v1
```

### Textbook imports

Textbooks are inspected before processing. Choose no more than the configured page range at a time. Each page is checkpointed as embedded text, Gemini OCR, failed, or skipped. Completed pages survive a failed page; students can review/correct extracted text before saving and retry a failed range after re-uploading the same PDF. Render free storage remains temporary, so long-term persistence requires a future persistent database/storage plan.
