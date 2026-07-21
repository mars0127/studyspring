# StudySpring

StudySpring is a study dashboard used for students. Students can create courses, save typed notes or text-based PDFs, practise with multiple-choice quizzes, and see which topics need more review. This tool was made by Mars Sun, Kenneth Wu and Bernard Kim. 

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

## Hosted deployment safety

The Render free tier has limited memory and no durable local disk by default. This app therefore rejects PDF uploads larger than 40 MB and scanned PDFs longer than 120 pages before processing them. Split a larger PDF into smaller files and import them separately.

For a real public deployment, attach durable storage and set `STUDYSPRING_DATABASE_PATH` to its database-file path (for example `/var/data/studyspring.db`). Without durable storage, a service restart can erase the local SQLite database, including courses and notes.
