# JobPilot AI Agent Instructions

## Project overview
JobPilot is a Python-based job search and application automation app. The backend is a FastAPI service in `backend/`, the frontend is static HTML/JS in `frontend/`, and the project stores credentials, job data, and profile data in a local SQLite database.

## Where to work
- Backend app entrypoint: `backend/app.py`
- AI helpers: `backend/ai.py`
- Database and profile logic: `backend/database.py`
- Encryption utilities: `backend/encryption.py`
- Scrapers: `backend/scrapers/`
- Frontend: `frontend/index.html`
- Environment setup: `setup.sh`, `run.sh`, `requirements.txt`

## Working rules
- Keep changes focused and repo-appropriate.
- Prefer small, testable edits over broad rewrites.
- Preserve the existing FastAPI + SQLite architecture unless the task clearly requires a structural change.
- Do not add unnecessary dependencies without a real need.
- Keep user-facing behavior consistent with the current UI and API patterns.

## Run and validate
Use the project virtual environment when running commands:
- Setup: `./setup.sh`
- Start app: `./run.sh`
- Alternative run: `cd backend && python app.py`
- For local dev reload: `cd backend && uvicorn app:app --reload --port 8765`

## Typical tasks
- For backend API work, inspect `backend/app.py` and then the relevant database or scraper module.
- For AI/LLM features, check `backend/ai.py` and the downstream callers before changing prompts or logic.
- For frontend updates, edit `frontend/index.html` and avoid breaking the existing API contracts.
- For scraper changes, read the base scraper and the specific site scraper before modifying selectors or request logic.

## Safety notes
- Do not expose secrets or API keys in logs, output, or code.
- Keep database and credential logic encrypted and profile-scoped.
- Preserve backwards compatibility for existing profile data and job records.

## Completion expectations
When asked to fix or change something in this repo:
1. Identify the root issue or requirement.
2. Make the smallest relevant patch.
3. Validate with the narrowest possible command or runtime check.
4. Report what changed and the evidence from the validation step.
