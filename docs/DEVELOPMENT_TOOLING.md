# Development tooling

| Tool | Purpose | Compatibility | Added now | Owner setup | Future migration | Privacy / cost | Rollback |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GitHub Issues / Projects | Repository planning | Compatible | Templates only | Enable in GitHub | No | Free; do not add student data | Remove templates |
| Figma / VS Code | Design and editing | Compatible | Docs only | Owner account | No | Files follow owner sharing rules | Remove docs |
| Ruff | Linting, imports, formatting | Compatible | Yes | Install dev requirements | No | Local/free | Remove config |
| Pyright / pytest / pre-commit | Types, tests, local checks | Compatible | Yes | Install dev requirements | No | Local/free | Remove config |
| Playwright | Browser regression tests | Compatible later | Deferred | Browser install | No | Free; no student fixtures | Remove suite |
| GitHub Actions | CI | Compatible | Yes | GitHub Actions enabled | No | Free tier limits | Delete workflow |
| Sentry / PostHog | Optional monitoring | Prepared later | No | DSN/project required | No | Never send notes/text; free tiers | Remove env/config |
| Tesseract / EasyOCR / PaddleOCR | Local OCR | Evaluate only | No | System/model install | No | Tesseract is the lightest candidate; Render risk | Remove adapter |
| Supabase | Future durable storage/auth | Future | No | Owner project required | Future | Student data/privacy review required | Keep SQLite |
| Lucide / Storybook / shadcn / Tailwind / React / Next / Radix | Future frontend tooling | Not for Streamlit | No | Future migration | Yes | Mostly open source | No runtime impact |
| LlamaIndex / LangChain | AI orchestration | Not needed | No | N/A | Possibly future | Adds complexity/cost risk | Do not adopt |
| Linear | Project management | External alternative | No | Owner account | No | External project data | Use GitHub Projects |

## Local commands (Windows)

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\pyright.exe
.\.venv\Scripts\pytest.exe
.\.venv\Scripts\python.exe tools\course_pack.py validate course_packs\ontario\mhf4u\manifest.json
```

Sentry, PostHog, and local OCR stay opt-in. They must never receive note text, textbook text, answers, API keys, or private filenames.
