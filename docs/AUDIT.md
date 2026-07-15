# StudySpring foundation audit (PR 1)

Date: 2026-07-15

## Current architecture

- A single Streamlit entry point (`app.py`, about 1,140 lines) renders the dashboard, forms, navigation, PDF handling, scan handling, quiz flows, and UI styling.
- `database.py` is a SQLite data-access layer. It creates tables at application startup and applies small, inline schema upgrades.
- `gemini_client.py` calls Gemini directly for question generation, short-answer marking, and scan transcription.
- `course_starters.py` provides small roadmap dictionaries, not installable course packs.
- The Render service starts Streamlit directly. There is no `Dockerfile` or `Procfile` in this repository.

## Baseline verification

- Local compilation: passed.
- Tests run from the project directory: 4 passing.
- The README test command is sensitive to the current folder. Running it from the parent folder fails because the project modules are not on Python's import path.
- The public URL loaded on 2026-07-15 with no browser-console errors in a clean session. Earlier dynamic-module errors are consistent with a browser retaining stale Streamlit JavaScript after a deployment.

## Confirmed bugs and risks

1. The complete scanned-PDF option synchronously renders and sends every page in one browser request. A 479-page scanned textbook can exceed Render time, memory, and Gemini quota limits.
2. Selected scanned pages are all rendered into a Python list before transcription. This is avoidable memory pressure.
3. PDF input is read into memory multiple times and has no structural validation, encrypted-file handling, safe page-range validation, or partial-progress checkpoint.
4. Error messages often append raw provider or parser exceptions to the student-facing screen.
5. Gemini retries only a small set of temporary errors. A quota response is shown as a long technical exception instead of a clear retry message.
6. Streamlit reruns can repeat long work because imports are not represented as persistent, resumable jobs.
7. SQLite lives on Render's ephemeral filesystem. Student data and import checkpoints can disappear on a restart or redeploy; this cannot be fixed reliably without persistent storage or an external database.
8. The global `[role="listbox"]` CSS selector can affect unrelated Streamlit controls after a Streamlit update.
9. The sidebar is used for both course management and navigation, which is crowded on narrow screens.
10. Existing course starters are hard-coded Python data, have no validation or licence metadata, and are not a course-pack system.

## Security and privacy

- Gemini keys are appropriately read from secrets/environment variables and are ignored by Git, but uploaded content is sent to Gemini when an AI scan or generation feature is used.
- The public app has no sign-in. Its local SQLite storage is unsuitable for private student records on Render.
- Logs must never include uploaded text, API keys, or raw provider responses.

## Refactor targets and sequence

1. Add a small PDF service with strict validation, inspection, streaming page extraction, and predictable errors.
2. Add SQLite import-job/page checkpoints so successful pages survive an interrupted import.
3. Replace the two scanned-PDF modes with a textbook workflow that inspects first and processes at most 20 selected pages.
4. Add safe Gemini error classification and bounded retries.
5. Move reusable UI styles and status messages into small modules; leave the larger page split for a follow-up once behaviour is covered by tests.
6. Establish a scoped design system and clearer top-level navigation without relying on broad CSS selectors.
7. Build the separate course-pack PR after this stability PR is reviewed.

## Rollback strategy

Each change is isolated behind the new import workflow and focused commits. Reverting the relevant commit restores the prior behaviour. Database additions are additive; old notes, quizzes, flashcards, and courses remain untouched. Render deployment should remain pinned to the previous commit until this branch is reviewed and manually tested.

## Figma status

No accessible StudySpring Figma file was available in this Codex session, so no Figma review is claimed. The UI work in this PR will use an implementation-ready calm-productivity token set and reusable Streamlit components; a connected Figma design can be compared in a later visual-review pass.
# Milestone 1 update

Resolved in the foundation branch: validated PDF inspection and bounded page processing, per-page checkpoints, cancellation without deleting completed output, retry controls, Course Pack installation, removal of the duplicate starter-course workflow, structured lesson block validation, and a local-only authoring helper.

Still intentionally deferred: a persistent hosted database for Render, a production-installed local OCR engine, user authentication, public administration, full visual regression testing, and course-pack updates/uninstall flows. The current Streamlit page remains a gradual refactor target; routing is now centralized but study sections still need extraction into dedicated modules in a following cleanup pass.
