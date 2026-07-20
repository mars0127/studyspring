# Textbook import architecture

The student sees one textbook with editable chapters or units. Page jobs, temporary files, OCR batches, and checkpoints are internal details.

Structure detection priority: PDF bookmarks; readable table-of-contents pages; chapter/unit heading heuristics; finally equal-sized fallback chunks. Each proposed section records a title, page range, confidence, method, and status. Students may accept, rename, adjust, merge, split, or exclude sections before processing.

Each page uses embedded text when usable. Only unreadable pages are rendered one at a time and sent to the optional Gemini OCR path. Each page is saved before the next; a completed section is automatically saved under its parent textbook. On quota exhaustion, the job pauses with a clear retry/re-upload instruction.
