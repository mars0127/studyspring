# StudySpring

StudySpring is a beginner-friendly study dashboard. Students can create courses, save typed notes or text-based PDFs, practise with multiple-choice quizzes, and see which topics need more review.

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

The same optional Gemini connection can read JPG, PNG, and WEBP scans of notes and save the extracted text as a study note. Use clear, upright images smaller than 10 MB, and check the extracted text before relying on it for studying. For a scanned PDF textbook, choose a range of up to 100 pages at a time; StudySpring automatically turns the pages into images and sends them to Gemini in smaller batches. You can also choose a full-PDF scan: it processes five-page batches internally without further clicks, then saves one complete study note when the scan finishes.

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
python -m unittest discover -s tests
```

The next build step is creating the first working Streamlit screen.

## Privacy and sharing

By default, StudySpring keeps study data in `studyspring.db` on the same computer as the app. Do not upload confidential material to a public deployment unless you add authentication, a privacy policy, and secure server-side storage.

The optional Gemini integration sends the selected note to Google's AI service only when you generate questions. For a public deployment, configure the same API key as a private deployment secret; never put it in frontend code or a public repository.
