---
description: 'JobPilot repository specialist for FastAPI, scraping, AI, and application workflows.'
---

You are working in the JobPilot codebase, a Python job-search and application automation app.

Project structure:
- `backend/app.py` is the FastAPI application entrypoint.
- `backend/database.py` handles profiles, jobs, credentials, and app state.
- `backend/ai.py` contains AI-related prompts and helper functions.
- `backend/scrapers/` contains site-specific scraping implementations.
- `frontend/` contains the static web UI.

Follow these rules:
- Keep changes scoped to the task.
- Respect the repo's existing architecture and naming patterns.
- Prefer small fixes and compatible database changes.
- Validate with the smallest relevant command or runtime check.
- Do not add secrets to code, logs, or issue output.

Primary commands:
- `./setup.sh` to install dependencies
- `./run.sh` to start the app
- `cd backend && uvicorn app:app --reload --port 8765` for local dev reload

When helping in this repo:
- Start by checking the relevant backend module and related scraper or database code.
- Keep the user-facing behavior consistent with the current app.
- Explain the root cause and fix briefly when addressing bugs.
- Include evidence from the validation step before claiming success.
