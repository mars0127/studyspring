# Future frontend migration plan

Streamlit remains appropriate while StudySpring validates its learning workflow. A migration is justified only when durable accounts/storage, background textbook processing, rich resource navigation, and custom responsive UI outweigh the cost.

Proposed future stack: Next.js + React + TypeScript, Tailwind, shadcn/ui, Radix UI, Lucide, Playwright, and a Postgres/storage service such as Supabase. Python services and Course Pack validation can remain behind an API boundary. The migration must preserve exports, keep SQLite as a local fallback, introduce authentication and privacy controls first, then move textbook jobs to durable storage/background workers. Roll back by keeping the Streamlit deployment live until feature parity and data migration are verified.
