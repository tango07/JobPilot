# JobPilot

JobPilot is a Python-based job search assistant that helps you discover jobs, track applications, manage saved searches, and speed up application workflows using AI assistance.

## Features

- Multi-site job scraping across LinkedIn, Naukri, Indeed, Glassdoor, and Instahyre
- Per-profile setup and personal resume storage
- Encrypted credential handling
- Saved searches and reminders
- Job pipeline tracking
- AI-powered resume parsing and job-fit scoring
- Match feedback capture with usefulness summaries by job site
- Browser-based job application assistance

## Tech stack

- Python 3.9+
- FastAPI
- SQLite
- Playwright
- Anthropic API support
- Static frontend served from the frontend folder

## Repository layout

- backend/app.py — FastAPI API entrypoint
- backend/database.py — SQLite helpers and schema
- backend/encryption.py — secret handling and encryption
- backend/ai.py — Anthropic AI helpers
- backend/scrapers/ — site-specific scrapers
- frontend/index.html — web UI
- tests/ — regression tests

## Local setup

1. Clone the repository
2. Create a virtual environment
3. Install dependencies
4. Install Playwright Chromium
5. Start the app

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python backend/app.py
```

Or use the helper scripts:

```bash
./setup.sh
./run.sh
```

## Environment variables

For production or shared environments, set a secret for encryption:

```bash
export JOBPILOT_SECRET_KEY="your-long-random-secret"
```

The app will also fall back to a local `.secret.key` file if no environment variable is set.

## Secret rotation and reset

This project keeps secrets out of the git repo. The local files `.secret.key` and `.anthropic_key` are ignored by git and should remain on your machine only.

### Rotate the app encryption key

If you want to rotate the stored encryption key:

```bash
export JOBPILOT_SECRET_KEY="new-random-secret"
rm -f .secret.key
```

Then restart the app. This will generate a new local key and encrypt future credentials with it. Note: rotating the key invalidates previously encrypted values, so existing saved site credentials will need to be re-entered.

### Reset app secrets

Use this only if you want to clear local app secrets and start over:

```bash
rm -f .secret.key .anthropic_key
rm -f jobsearch.db
```

This clears the local encryption key, saved AI key, and the SQLite job/profile database. Use it carefully because it removes persisted job data and profile state.

### Secret review status

The repository does not contain plaintext credentials in tracked source files. Secrets are stored only in local ignored files such as `.secret.key`, `.anthropic_key`, and the SQLite database created on first run. The app encrypts credential values before writing them to the database, and the checked-in code does not embed usernames, passwords, or API keys.

## Default run URL

The app serves its UI at:

```text
http://127.0.0.1:8765
```

## Notes

- The project stores local job and profile data in `jobsearch.db`
- Sensitive values are encrypted before storage
- Some AI features require an Anthropic API key

## Roadmap

Current product foundations include CI checks, defensive secret handling,
resume-to-job match scoring, and beta feedback collection with usefulness
summaries in the Applications tracker.

The next improvement area is export and reporting for job pipelines.
