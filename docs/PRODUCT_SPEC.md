# StudySpring Product Specification

## Purpose

StudySpring is a guided learning platform for high-school students. It helps a student decide what to study next, learn course material, practise retrieval, understand mistakes, and see progress—without requiring an AI key.

## Product principles

- Guide the next useful action; do not make students assemble their own workflow.
- Keep each screen focused, calm, readable, and accessible.
- AI accelerates feedback and content preparation but never replaces student thinking.
- Personal material stays separate from bundled Course Pack content.
- Use original, public-domain, or properly licensed material only.
- Remain practical on Render's free tier: bounded work, temporary storage awareness, and no paid infrastructure.

## Information architecture

| Destination | Student question it answers |
| --- | --- |
| Home | What should I study today? |
| My Courses | Which courses am I managing? |
| Course Library | Which complete courses can I install? |
| Imports | How do I add my own material? |
| Learn | What can I learn or practise now? |
| Progress | What am I strong or weak at? |
| Settings | How is my workspace configured? |

No destination should render another destination's primary controls.

## Course Pack model

```text
Course Pack → Units → Lessons → Content Blocks
                              ├─ Flashcards
                              ├─ Practice questions
                              ├─ Resources
                              └─ AI context (future)
```

Every Course Pack includes a versioned manifest, author, licence, source metadata, learning objectives, units, topics, and validated lesson files. A Course Pack installation must be idempotent and transactional.

### Content blocks

Supported foundation blocks: heading, paragraph, definition, formula, worked example, common mistake, practice set, answer key, flashcard set, multiple-choice set, short-answer set, resource link, and callout.

Planned compatible blocks: diagram placeholder, table, warning, tip, vocabulary, review section, video placeholder, learning objective, estimated time, difficulty, and summary. New blocks must be validated, documented, and rendered without one-off UI code.

## Educational quality standard

Every substantial lesson should include learning objectives, clear explanation, at least one worked example where relevant, common mistakes, guided or independent practice, answers or feedback, and attribution. Content must be original, accurate, age-appropriate, and useful without an AI integration.

The MHF4U pilot is the quality benchmark before adding additional courses. Do not add broad course coverage with shallow placeholder lessons.

## Learning loop

```text
Recommended lesson → Learn → Flashcards → Practice → Review mistakes → Next recommendation
```

The product should surface weak topics, recent activity, next lesson, course completion, quiz performance, and review recommendations with simple explanations.

## Course Builder

Course authoring is local-only developer tooling. It must scaffold, import/export, validate, and preview Course Packs; check unique IDs, references, answers, required metadata, licences, and source files. It must never be a publicly editable production screen.

## Technical architecture

- Python and Streamlit application shell.
- SQLite for local/temporary student data.
- JSON Course Pack manifests and lesson block files, validated by Python services.
- PyPDF/PyMuPDF for bounded document inspection and extraction.
- Optional Gemini integration for explicitly requested AI features and difficult scans.
- Render deployment from `main`; Manual PR previews via `render-preview` label.

## Non-functional requirements

- Keyboard-accessible controls and sufficient contrast.
- Responsive desktop, tablet, and narrow-browser layouts.
- No raw exceptions or secrets in the UI or logs.
- No full-document PDF rendering in memory.
- Preserve completed PDF pages after partial failure or cancellation.
- Avoid global caching of private uploads.
- Free-tier compatibility: no paid services, background workers, or required persistent disk.

## Development roadmap

1. **Foundation (PR #1):** application shell, resilient imports, Course Pack validation, MHF4U pilot, preview deployment.
2. **Learning platform:** deepen MHF4U, strengthen Learn/Home/Progress recommendations, expand local authoring tools.
3. **Content scale:** add only high-quality, licensed course packs using the proven MHF4U standard.
4. **Personalization:** spaced review, study planning, richer progress, and optional AI tutoring.

## Decision log

- Prebuilt courses use Course Packs; legacy starter courses are retired.
- MHF4U JSON content blocks are the source of truth for the pilot lesson.
- OCR/import processing is page-bounded and checkpointed.
- Preview deployments are Manual and visibly labelled; production deploys from `main` only.
- Do not merge PR #1 until its hosted preview has passed manual product review.

## Working agreement for future changes

Before making a substantial change, read this document and the relevant current implementation. Prefer a small coherent feature over a broad rewrite. Update this specification when a durable product or technical decision changes.
