# Copilot instructions for JobPilot

## Repository context
This repository is a job search assistant that scrapes job boards, stores profile and application data, and supports AI-assisted resume and form handling.

## Stack
- Python 3.9+
- FastAPI for the API layer
- SQLite for persistence
- Playwright-based scraping for multiple job platforms
- Anthropic integration via `backend/ai.py`
- Static frontend served from `frontend/`

## Project conventions
- Keep business logic in `backend/`.
- Do not change the database schema casually; prefer compatible, additive updates.
- Favor explicit error handling with clear user-facing messages.
- Preserve the current naming patterns used in `backend/app.py`, `backend/database.py`, and the scraper modules.
- Keep AI prompts and fallback behavior defensive when API keys are missing.

## Commands
- Setup: `./setup.sh`
- Run: `./run.sh`
- Direct backend start: `cd backend && python app.py`
- Optional reload: `cd backend && uvicorn app:app --reload --port 8765`

## Implementation guidance
- When adding endpoints, follow the existing FastAPI patterns in `backend/app.py`.
- When updating scraper behavior, inspect the base scraper at `backend/scrapers/base.py` and the relevant site-specific scraper before making a fix.
- When changing storage or profile logic, verify the database helpers and any response contracts used by the frontend.
- Keep UI changes aligned with the static page structure and existing JS integration.

## Quality bar
- Prefer minimal, focused patches.
- Verify behavior with the smallest relevant check available.
- Report evidence from the validation step rather than assumptions.
- Avoid introducing noisy logging or debug output in normal operation.
