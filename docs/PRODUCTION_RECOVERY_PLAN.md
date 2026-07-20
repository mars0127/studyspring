# Production import recovery plan

## Branch baseline

This branch starts from `origin/main`, the production baseline. PR #1 remains a source of small, reviewable ideas; it is not a merge candidate because its focused shell removed or hid effective production study workflows.

| Area | Decision | Reason |
| --- | --- | --- |
| PDF validation and inspection | Reimplement safely | Useful, independent protection against corrupt, encrypted, and unsupported PDFs. |
| Per-page checkpoints | Reimplement safely | Preserve completed extraction without replacing the production learning interface. |
| Import job concept | Reimplement safely | Enables resume and grouped textbook status. |
| Gemini error classification | Reuse concept | Keep short, safe quota and provider messages. |
| Course Packs | Defer | Valuable but not required to repair production imports. |
| PR #1 navigation shell | Discard | Manual review found it weaker than production workflows. |
| Generated-material workflow | Preserve production | Production provides the better student journey. |
| Flashcards, practice, weak topics | Preserve production | These are proven student-facing capabilities. |
| Design/tooling documentation | Defer from PR #2 | PR #2 is stacked on PR #1 and should be rebased or recreated after recovery is stable. |

## Recovery sequence

1. Add path-based PDF validation and safe temporary-file lifecycle.
2. Add a textbook inspection result: bookmarks, table-of-contents and heading heuristics, then fallback chunks.
3. Let students confirm/edit sections before expensive extraction.
4. Create one textbook job with section and page checkpoints; extract embedded text first and OCR only unreadable pages.
5. Autosave each completed section into one grouped textbook resource, while exposing the existing production study actions.
6. Verify small/mixed/large PDFs on a hosted preview before declaring large-textbook support complete.

## Non-negotiable limits

Render Free has no durable disk or background worker. Work can continue only while the request and temporary file remain available. Completed checkpoints survive only while SQLite persists; a missing file requires re-upload. No textbook is sent to Gemini as one request.
