"""
Job Search App — FastAPI backend
Serves the web UI and provides REST + WebSocket APIs for:
  - Profile management
  - Credential storage (encrypted)
  - Job search across LinkedIn, Naukri, Indeed, Glassdoor, Instahyre
  - Automated job application
  - Application tracking
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from database import (
    init_db, get_profile, save_profile, get_credential, save_credential,
    set_logged_in, all_credentials, upsert_job, get_jobs, update_job_status,
    count_jobs, create_application, get_applications, update_application_status,
    count_applications,
    get_custom_sites, upsert_custom_site, delete_custom_site,
    cleanup_old_jobs, clear_all_jobs,
    list_profiles, create_profile, activate_profile, delete_profile,
    set_profile_password, verify_profile_password,
    get_profile_claude_key, set_profile_claude_key,
    create_saved_search, list_saved_searches, delete_saved_search,
    create_reminder, list_reminders, mark_reminder_done,
    create_feedback, list_feedback, feedback_summary,
    delete_job,
)
from encryption import encrypt, decrypt
from scrapers.base import set_headless_mode
from scrapers.linkedin import LinkedInScraper
from scrapers.naukri import NaukriScraper
from scrapers.indeed import IndeedScraper
from scrapers.glassdoor import GlassdoorScraper
from scrapers.instahyre import InstaHyreScraper
from scrapers.generic import GenericScraper
import ai as ai_module

# ── App setup ──────────────────────────────────────────────────────────────────

app = FastAPI(title="Job Search App", version="1.0.0")

FRONTEND_SOURCE_DIR = Path(__file__).parent.parent / "frontend"
FRONTEND_DIR = FRONTEND_SOURCE_DIR / "dist"
if not FRONTEND_DIR.exists():
    FRONTEND_DIR = FRONTEND_SOURCE_DIR
UPLOADS_DIR = Path(__file__).parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
AVATARS_DIR = Path(__file__).parent.parent / "avatars"
AVATARS_DIR.mkdir(exist_ok=True)

# Serve static frontend
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# WebSocket connection manager for real-time log streaming
class ConnectionManager:
    def __init__(self):
        self.connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()

def make_log_callback(action: str):
    """Create a log callback that broadcasts to WebSocket clients AND prints to terminal."""
    async def _send(msg, level="info"):
        await manager.broadcast({"type": "log", "action": action, "message": msg, "level": level})
    def _sync(msg, level="info"):
        print(f"[{level.upper()}] {msg}", flush=True)   # always visible in terminal
        asyncio.create_task(_send(msg, level))
    return _sync

# ── Cancel flag ────────────────────────────────────────────────────────────────
# A simple in-process flag. Set to True via POST /api/stop; cleared at the
# start of every new search-and-apply run.
_CANCEL = {"requested": False}

# ── Scraper registry ───────────────────────────────────────────────────────────

SCRAPERS = {
    "linkedin":   LinkedInScraper,
    "naukri":     NaukriScraper,
    "indeed":     IndeedScraper,
    "glassdoor":  GlassdoorScraper,
    "instahyre":  InstaHyreScraper,
}

# Custom sites loaded from DB at startup — key → config dict
CUSTOM_SCRAPERS: Dict[str, Dict] = {}


def get_scraper(site: str, log_cb=None):
    if site in SCRAPERS:
        return SCRAPERS[site](log_callback=log_cb)
    if site in CUSTOM_SCRAPERS:
        cfg = CUSTOM_SCRAPERS[site]
        return GenericScraper(
            site_key=site,
            display_name=cfg["name"],
            base_url=cfg["base_url"],
            search_url_template=cfg["search_url"],
            log_callback=log_cb,
        )
    raise HTTPException(status_code=400, detail=f"Unknown site: {site}")


def all_sites() -> Dict[str, str]:
    """Return all site keys (built-in + custom)."""
    keys = list(SCRAPERS.keys()) + list(CUSTOM_SCRAPERS.keys())
    return {k: k for k in keys}

# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    init_db()
    # Auto-delete jobs older than 10 days
    deleted = cleanup_old_jobs(days=10)
    if deleted:
        print(f"🗑  Cleaned up {deleted} job(s) older than 10 days")
    # Load custom sites into CUSTOM_SCRAPERS registry
    for site in get_custom_sites():
        CUSTOM_SCRAPERS[site["key"]] = site
    print(f"✓ Database initialized ({len(CUSTOM_SCRAPERS)} custom site(s) loaded)")

# ── Frontend ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(index_file.read_text())
    return HTMLResponse("<h1>Frontend not found</h1>")

# ── WebSocket for real-time logs ───────────────────────────────────────────────

@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # Keep alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ── Models ─────────────────────────────────────────────────────────────────────

class ProfileData(BaseModel):
    profile_name: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    resume_path: Optional[str] = None
    years_experience: Optional[int] = None
    current_title: Optional[str] = None
    desired_title: Optional[str] = None
    desired_salary: Optional[str] = None
    skills: Optional[List[str]] = None
    summary: Optional[str] = None

class CredentialData(BaseModel):
    username: str
    password: str

class CustomSiteData(BaseModel):
    name: str
    base_url: str
    search_url: str
    color: Optional[str] = ""
    bg: Optional[str] = ""
    label: Optional[str] = ""

class SearchParams(BaseModel):
    keywords: str
    location: str = ""
    sites: List[str] = ["linkedin", "naukri", "indeed"]
    filters: Dict[str, Any] = {}
    results_limit: int = 25  # max jobs to return per site

class ApplyParams(BaseModel):
    job_id: int

class ApplicationUpdate(BaseModel):
    status: str
    response: Optional[str] = ""

# ── Profile ────────────────────────────────────────────────────────────────────

@app.get("/api/profile")
async def api_get_profile():
    return get_profile() or {}

@app.post("/api/profile")
async def api_save_profile(data: ProfileData):
    # exclude_none so partial updates (e.g. only profile_name) don't wipe other fields
    saved = save_profile(data.dict(exclude_none=True))
    return saved

# ── Multi-profile endpoints ────────────────────────────────────────────────────

class ProfileCreateData(BaseModel):
    name: str

@app.get("/api/profiles")
async def api_list_profiles():
    return list_profiles()

@app.post("/api/profiles")
async def api_create_profile(data: ProfileCreateData):
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="Profile name cannot be empty")
    return create_profile(data.name.strip())

@app.post("/api/profiles/{profile_id}/activate")
async def api_activate_profile(profile_id: int):
    profile = activate_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile

@app.delete("/api/profiles/{profile_id}")
async def api_delete_profile(profile_id: int):
    ok = delete_profile(profile_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Cannot delete the last profile")
    return {"ok": True}

@app.post("/api/profiles/{profile_id}/avatar")
async def api_upload_avatar(profile_id: int, file: UploadFile = File(...)):
    """Upload a profile picture for the given profile."""
    suffix = Path(file.filename or "avatar.jpg").suffix.lower() or ".jpg"
    if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        raise HTTPException(status_code=400, detail="Unsupported image type")
    dest = AVATARS_DIR / f"{profile_id}{suffix}"
    # Remove any old avatar with a different extension
    for old in AVATARS_DIR.glob(f"{profile_id}.*"):
        old.unlink(missing_ok=True)
    dest.write_bytes(await file.read())
    avatar_url = f"/api/profiles/{profile_id}/avatar"
    # Persist the path in the DB
    from database import get_conn
    with get_conn() as conn:
        conn.execute("UPDATE profile SET avatar_path=? WHERE id=?", (str(dest), profile_id))
    return {"avatar_url": avatar_url}

@app.get("/api/profiles/{profile_id}/avatar")
async def api_get_avatar(profile_id: int):
    """Serve the profile picture for the given profile."""
    for f in AVATARS_DIR.glob(f"{profile_id}.*"):
        return FileResponse(str(f))
    raise HTTPException(status_code=404, detail="No avatar set")

class PasswordData(BaseModel):
    password: str = ""        # current / new password (empty = remove)
    current_password: str = ""  # required when changing an existing password

class VerifyPasswordData(BaseModel):
    password: str

@app.post("/api/profiles/{profile_id}/set-password")
async def api_set_password(profile_id: int, data: PasswordData):
    """Set, change, or remove a profile's password."""
    # If profile already has a password, require current_password
    if not verify_profile_password(profile_id, data.current_password):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    set_profile_password(profile_id, data.password)
    return {"ok": True, "has_password": bool(data.password)}

@app.post("/api/profiles/{profile_id}/verify-password")
async def api_verify_password(profile_id: int, data: VerifyPasswordData):
    """Verify a password before switching to this profile."""
    ok = verify_profile_password(profile_id, data.password)
    if not ok:
        raise HTTPException(status_code=403, detail="Incorrect password")
    return {"ok": True}

@app.post("/api/upload-resume")
async def upload_resume(file: UploadFile = File(...)):
    dest = UPLOADS_DIR / file.filename
    content = await file.read()
    dest.write_bytes(content)
    return {"path": str(dest), "filename": file.filename}

# ── Credentials ────────────────────────────────────────────────────────────────

@app.get("/api/credentials")
async def api_list_credentials():
    creds = all_credentials()
    return creds

@app.post("/api/credentials/{site}")
async def api_save_credential(site: str, data: CredentialData):
    if site not in SCRAPERS:
        raise HTTPException(status_code=400, detail=f"Unknown site: {site}")
    enc_password = encrypt(data.password)
    save_credential(site, data.username, enc_password)
    return {"status": "saved", "site": site}

@app.delete("/api/credentials/{site}")
async def api_delete_credential(site: str):
    from database import get_conn
    with get_conn() as conn:
        conn.execute("DELETE FROM credentials WHERE site=?", (site,))
    return {"status": "deleted"}

# ── Custom Sites ──────────────────────────────────────────────────────────────

import re as _re

def _make_site_key(name: str) -> str:
    """Convert a display name to a safe lowercase key, e.g. 'Wellfound' → 'wellfound'."""
    key = _re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", "_"))[:24]
    return key or "custom"

PALETTE = [
    ("#1D4ED8", "#DBEAFE"), ("#065F46", "#D1FAE5"), ("#92400E", "#FEF3C7"),
    ("#5B21B6", "#EDE9FE"), ("#9D174D", "#FCE7F3"), ("#1E3A5F", "#E0F2FE"),
    ("#7C2D12", "#FED7AA"), ("#134E4A", "#CCFBF1"),
]

@app.get("/api/sites/custom")
def api_get_custom_sites():
    return get_custom_sites()

@app.post("/api/sites/custom")
def api_add_custom_site(data: CustomSiteData):
    key = _make_site_key(data.name)
    # Avoid colliding with built-in sites
    if key in SCRAPERS:
        key = f"custom_{key}"
    # Pick color from palette based on existing count
    existing = get_custom_sites()
    idx = len(existing) % len(PALETTE)
    color = data.color or PALETTE[idx][0]
    bg = data.bg or PALETTE[idx][1]
    # Auto-generate 2-letter label from name words
    words = data.name.strip().split()
    label = (words[0][0] + (words[1][0] if len(words) > 1 else words[0][1])).upper() if words else "??"
    label = data.label or label
    upsert_custom_site(key, data.name, data.base_url.rstrip("/"), data.search_url, color, bg, label)
    # Register in live CUSTOM_SCRAPERS
    CUSTOM_SCRAPERS[key] = {
        "key": key, "name": data.name, "base_url": data.base_url.rstrip("/"),
        "search_url": data.search_url, "color": color, "bg": bg, "label": label,
    }
    return {"key": key, "name": data.name, "color": color, "bg": bg, "label": label}

@app.delete("/api/sites/custom/{key}")
def api_delete_custom_site(key: str):
    delete_custom_site(key)
    CUSTOM_SCRAPERS.pop(key, None)
    return {"status": "deleted"}

@app.post("/api/sites/custom/{key}/force-connect")
def api_force_connect_custom_site(key: str):
    """Mark a custom site as connected without SSO verification (user confirms manually)."""
    if key not in CUSTOM_SCRAPERS:
        raise HTTPException(status_code=404, detail=f"Custom site '{key}' not found")
    save_credential(key, "sso", encrypt("sso"))
    set_logged_in(key, True)
    return {"status": "connected", "site": key}


@app.post("/api/login/{site}")
async def api_login(site: str):
    """Login with saved email + password credentials."""
    cred = get_credential(site)
    if not cred:
        raise HTTPException(status_code=404, detail=f"No credentials found for {site}")
    password = decrypt(cred["password_enc"])
    log_cb = make_log_callback("login")

    scraper = get_scraper(site, log_cb)
    success = await scraper.login(cred["username"], password)
    set_logged_in(site, success)
    if not success:
        raise HTTPException(status_code=401, detail=f"Login failed for {site}")
    return {"status": "logged_in", "site": site, "method": "password"}

@app.post("/api/login/{site}/sso")
async def api_sso_login(site: str):
    """
    Open the browser to the site's login page and wait for the user to
    complete Google Sign-In (or any SSO) manually. Session is saved
    automatically to the persistent browser profile.
    Runs for up to ~2 minutes waiting for successful authentication.
    """
    if site not in SCRAPERS and site not in CUSTOM_SCRAPERS:
        raise HTTPException(status_code=400, detail=f"Unknown site: {site}")
    log_cb = make_log_callback("login")
    await set_headless_mode(False)   # SSO needs a visible browser
    scraper = get_scraper(site, log_cb)
    success = await scraper.sso_login()
    set_logged_in(site, success)
    if not success:
        raise HTTPException(
            status_code=401,
            detail=f"SSO login timed out or failed for {site}. "
                   "Check that you completed sign-in in the browser window."
        )
    # Save a placeholder so GET /api/credentials shows this site as connected
    save_credential(site, "sso", encrypt("sso"))
    return {"status": "logged_in", "site": site, "method": "sso"}

# ── Job Search ─────────────────────────────────────────────────────────────────

@app.post("/api/search")
async def api_search(params: SearchParams):
    """Kick off job search across selected sites. Results are saved to DB."""
    profile = get_profile() or {}
    log_cb = make_log_callback("search")
    results_by_site = {}

    async def search_site(site: str):
        cred = get_credential(site)
        scraper = get_scraper(site, log_cb)

        # Auto-login if credentials exist but not logged in
        if cred and not cred.get("is_logged_in"):
            password = decrypt(cred["password_enc"])
            await scraper.login(cred["username"], password)
            set_logged_in(site, True)

        # Inject results_limit into filters so scrapers can read it without signature changes
        merged_filters = {**params.filters, "results_limit": max(1, min(params.results_limit, 200))}
        jobs = await scraper.search_jobs(params.keywords, params.location, merged_filters)
        saved_ids = []
        for job in jobs:
            job_id = upsert_job(job)
            saved_ids.append(job_id)

        await manager.broadcast({
            "type": "search_result",
            "site": site,
            "count": len(jobs),
            "job_ids": saved_ids,
        })
        results_by_site[site] = len(jobs)

    # Run searches SEQUENTIALLY — all scrapers share one Chromium process/profile.
    # Concurrent launch_persistent_context() calls on the same user-data-dir cause
    # Chrome to print "Opening in existing browser session" and exit immediately.
    # Sequential execution eliminates this race while keeping the live log feed.
    sites_to_search = [s for s in params.sites if s in SCRAPERS or s in CUSTOM_SCRAPERS]
    print(f"[SEARCH] sites requested: {params.sites}", flush=True)
    print(f"[SEARCH] sites to search: {sites_to_search}", flush=True)
    for site in sites_to_search:
        print(f"[SEARCH] starting {site}...", flush=True)
        try:
            await search_site(site)
            print(f"[SEARCH] {site} done → {results_by_site.get(site, 0)} jobs", flush=True)
        except Exception as exc:
            print(f"[SEARCH] {site} EXCEPTION: {exc}", flush=True)
            import traceback; traceback.print_exc()
            await manager.broadcast({
                "type": "log",
                "action": "search",
                "message": f"Search error on {site}: {exc}",
                "level": "error",
            })
            results_by_site[site] = 0

    total = sum(results_by_site.values())
    await manager.broadcast({"type": "search_done", "total": total, "by_site": results_by_site})
    return {"total": total, "by_site": results_by_site}

# ── Jobs ───────────────────────────────────────────────────────────────────────

@app.get("/api/jobs")
async def api_get_jobs(site: str = None, status: str = None, limit: int = 100, offset: int = 0):
    return get_jobs(site=site, status=status, limit=limit, offset=offset)

@app.get("/api/jobs/count")
async def api_count_jobs(site: str = None):
    return {"count": count_jobs(site=site)}

@app.post("/api/jobs/{job_id}/apply")
async def api_apply(job_id: int):
    """Apply to a specific job by its DB ID."""
    jobs = get_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    profile = get_profile()
    if not profile:
        raise HTTPException(status_code=400, detail="Please complete your profile first")

    log_cb = make_log_callback("apply")
    site = job["site"]

    cred = get_credential(site)
    scraper = get_scraper(site, log_cb)

    if cred and not cred.get("is_logged_in"):
        password = decrypt(cred["password_enc"])
        await scraper.login(cred["username"], password)
        set_logged_in(site, True)

    success = await scraper.apply_to_job(job, profile)

    if success:
        update_job_status(job_id, "applied")
        app_id = create_application(
            job_id=job_id,
            site=site,
            title=job["title"],
            company=job["company"],
        )
        await manager.broadcast({"type": "applied", "job_id": job_id, "app_id": app_id, "success": True})
        return {"status": "applied", "app_id": app_id}
    else:
        await manager.broadcast({"type": "applied", "job_id": job_id, "success": False})
        return {"status": "manual_needed", "url": job["url"]}


class SavedSearchData(BaseModel):
    name: str
    keywords: str
    location: str = ""
    sites: List[str] = []
    filters: Dict[str, Any] = {}


@app.get("/api/saved-searches")
async def api_list_saved_searches():
    return list_saved_searches()


@app.post("/api/saved-searches")
async def api_create_saved_search(data: SavedSearchData):
    if not data.keywords.strip():
        raise HTTPException(status_code=400, detail="Keywords cannot be empty")
    return create_saved_search(
        name=data.name or "Saved Search",
        keywords=data.keywords.strip(),
        location=data.location.strip(),
        sites=data.sites,
        filters=data.filters,
    )


@app.delete("/api/saved-searches/{search_id}")
async def api_delete_saved_search(search_id: int):
    ok = delete_saved_search(search_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Saved search not found")
    return {"status": "deleted"}


class ReminderData(BaseModel):
    job_id: int
    reminder_type: str = "follow_up"
    due_at: str
    note: str = ""


class FeedbackData(BaseModel):
    job_id: int
    sentiment: str = "useful"
    comment: str = ""


@app.get("/api/reminders")
async def api_list_reminders(status: str = None, job_id: int = None):
    return list_reminders(status=status, job_id=job_id)


@app.post("/api/reminders")
async def api_create_reminder(data: ReminderData):
    if not data.due_at:
        raise HTTPException(status_code=400, detail="Reminder date is required")
    return create_reminder(
        job_id=data.job_id,
        reminder_type=data.reminder_type,
        due_at=data.due_at,
        note=data.note,
    )


@app.patch("/api/reminders/{reminder_id}/done")
async def api_reminder_done(reminder_id: int):
    result = mark_reminder_done(reminder_id)
    if not result.get("done"):
        raise HTTPException(status_code=404, detail="Reminder not found")
    return result


@app.get("/api/feedback")
async def api_list_feedback(job_id: int = None):
    return list_feedback(job_id=job_id)


@app.get("/api/feedback/summary")
async def api_feedback_summary():
    return feedback_summary()


@app.post("/api/feedback")
async def api_create_feedback(data: FeedbackData):
    jobs = get_jobs()
    if not any(job["id"] == data.job_id for job in jobs):
        raise HTTPException(status_code=404, detail="Job not found")
    if data.sentiment not in {"useful", "neutral", "not_useful"}:
        raise HTTPException(status_code=400, detail="Invalid sentiment")
    return create_feedback(job_id=data.job_id, sentiment=data.sentiment, comment=data.comment)

@app.post("/api/jobs/apply-batch")
async def api_apply_batch(params: dict):
    """Apply to multiple jobs. Body: {"job_ids": [1, 2, 3]}"""
    job_ids = params.get("job_ids", [])
    results = []
    for jid in job_ids:
        try:
            result = await api_apply(jid)
            results.append({"job_id": jid, **result})
            await asyncio.sleep(2)  # Rate limit between applications
        except Exception as e:
            results.append({"job_id": jid, "status": "error", "message": str(e)})
    return {"results": results}

# ── Applications ───────────────────────────────────────────────────────────────

@app.get("/api/applications")
async def api_get_applications(status: str = None, limit: int = 100):
    return get_applications(status=status, limit=limit)

@app.get("/api/applications/count")
async def api_count_applications(status: str = None):
    return {"count": count_applications(status=status)}

@app.patch("/api/applications/{app_id}")
async def api_update_application(app_id: int, data: ApplicationUpdate):
    update_application_status(app_id, data.status, data.response)
    return {"status": "updated"}


class JobStatusUpdate(BaseModel):
    status: str


@app.patch("/api/jobs/{job_id}/status")
async def api_update_job_status(job_id: int, data: JobStatusUpdate):
    allowed = {"new", "applied", "interviewing", "offered", "rejected", "withdrawn"}
    if data.status not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid status: {data.status}")
    update_job_status(job_id, data.status)
    return {"status": "updated", "job_id": job_id, "new_status": data.status}


@app.delete("/api/jobs/{job_id}")
async def api_delete_job(job_id: int):
    if not delete_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "deleted", "job_id": job_id}

# ── Dashboard stats ────────────────────────────────────────────────────────────

@app.post("/api/stop")
async def api_stop():
    """Signal any running search-and-apply loop to stop after the current job."""
    _CANCEL["requested"] = True
    await manager.broadcast({"type": "apply_stopped", "message": "Stop requested — finishing current job then stopping."})
    return {"status": "stopping"}

@app.delete("/api/jobs/all")
async def api_clear_all_jobs():
    """Delete all jobs and their applications — fresh slate before a new search."""
    deleted = clear_all_jobs()
    jobs_count = count_jobs()
    return {"deleted": deleted, "message": f"Cleared {deleted} job(s) from the database."}

@app.get("/api/stats")
async def api_stats():
    return {
        "total_jobs": count_jobs(),
        "new_jobs": count_jobs(),
        "total_applied": count_applications(),
        "interviewing": count_applications(status="interviewing"),
        "offered": count_applications(status="offered"),
        "rejected": count_applications(status="rejected"),
        "sites": {site: count_jobs(site=site) for site in list(SCRAPERS.keys()) + list(CUSTOM_SCRAPERS.keys())},
    }

# ── AI endpoints ───────────────────────────────────────────────────────────────

class AIKeyData(BaseModel):
    key: str

class AnswerRequest(BaseModel):
    question: str
    job_title: str = ""
    company: str = ""
    job_description: str = ""

class ScoreRequest(BaseModel):
    job_id: int


class BatchScoreRequest(BaseModel):
    job_ids: List[int]

@app.get("/api/ai/status")
async def ai_status():
    profile_key = get_profile_claude_key()
    return {
        "ready": ai_module.is_ai_ready(),
        "has_key": bool(ai_module.get_api_key()),
        "profile_has_key": bool(profile_key),
        # Masked preview: "sk-ant-...abc" → show only last 6 chars
        "key_preview": ("…" + profile_key[-6:]) if profile_key else "",
    }

class ParseSearchData(BaseModel):
    query: str

@app.post("/api/ai/parse-search")
async def parse_search(data: ParseSearchData):
    """Parse a natural language search query into structured filters."""
    if not data.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    result = ai_module.parse_search_query(data.query.strip())
    return result

@app.post("/api/ai/key")
async def set_ai_key(data: AIKeyData):
    if not data.key.strip():
        raise HTTPException(status_code=400, detail="Key cannot be empty")
    ai_module.set_api_key(data.key.strip())
    return {"status": "saved"}

@app.post("/api/ai/parse-resume")
async def parse_resume():
    """Extract profile data from the resume file stored in the profile."""
    profile = get_profile()
    if not profile or not profile.get("resume_path"):
        raise HTTPException(status_code=400, detail="No resume path set in profile")
    text = ai_module.extract_resume_text(profile["resume_path"])
    if not text:
        raise HTTPException(status_code=400, detail="Could not read resume file — try re-uploading it")
    try:
        extracted = ai_module.parse_resume_to_profile(text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"extracted": extracted, "resume_text_length": len(text)}

@app.post("/api/ai/score-job/{job_id}")
async def score_job(job_id: int):
    jobs = get_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    profile = get_profile() or {}
    result = ai_module.score_job_fit(job["title"], job.get("description", ""), profile)
    return result


@app.post("/api/ai/score-jobs")
async def score_jobs(data: BatchScoreRequest):
    requested = list(dict.fromkeys(data.job_ids))[:12]
    jobs_by_id = {job["id"]: job for job in get_jobs(limit=300)}
    jobs = [jobs_by_id[job_id] for job_id in requested if job_id in jobs_by_id]
    profile = get_profile() or {}
    return {"results": ai_module.score_jobs_fit(jobs, profile)}

@app.post("/api/ai/cover-letter/{job_id}")
async def cover_letter(job_id: int):
    jobs = get_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    profile = get_profile() or {}
    letter = ai_module.generate_cover_letter(
        job["title"], job["company"], job.get("description", ""), profile
    )
    return {"cover_letter": letter}

@app.post("/api/ai/answer")
async def ai_answer(data: AnswerRequest):
    profile = get_profile() or {}
    answer = ai_module.answer_form_question(
        data.question, data.job_title, data.company, data.job_description, profile
    )
    return {"answer": answer}

# ── Auto-search (search all sites based on profile preferences) ────────────────

class AutoSearchParams(BaseModel):
    keywords: str = ""
    location: str = ""
    sites: List[str] = list(SCRAPERS.keys())

@app.post("/api/autosearch")
async def api_autosearch(params: AutoSearchParams):
    """
    Search all selected sites at once. Keywords/location default to profile preferences
    if not provided. This is the main entry point for the unified feed.
    """
    profile = get_profile() or {}
    keywords = params.keywords or profile.get("desired_title") or profile.get("current_title") or ""
    location = params.location or profile.get("location") or ""
    if not keywords:
        raise HTTPException(status_code=400, detail="Set a desired title in your profile, or enter search keywords.")

    return await api_search(SearchParams(
        keywords=keywords,
        location=location,
        sites=params.sites,
        filters={},
    ))

# ── Search + auto-apply in one shot ───────────────────────────────────────────

@app.post("/api/search-and-apply")
async def api_search_and_apply(params: AutoSearchParams):
    """
    Search selected sites for jobs, then immediately auto-apply to every new
    result. Progress is streamed over WebSocket so the UI can show live updates.
    """
    profile = get_profile() or {}
    if not profile:
        raise HTTPException(status_code=400, detail="Complete your profile before applying.")

    keywords = params.keywords or profile.get("desired_title") or profile.get("current_title") or ""
    location = params.location or profile.get("location") or ""
    if not keywords:
        raise HTTPException(status_code=400, detail="Enter a job title or set one in your profile.")

    # Clear any previous stop request
    _CANCEL["requested"] = False

    # Run headless so no browser window steals focus during automated apply
    await set_headless_mode(True)

    await manager.broadcast({"type": "log", "message": f"🔍 Searching for '{keywords}' on {len(params.sites)} site(s)…", "level": "info"})

    # ── Step 1: search ──────────────────────────────────────────────────────
    log_cb = make_log_callback("search")

    async def search_site(site: str):
        cred = get_credential(site)
        scraper = get_scraper(site, log_cb)
        if cred and not cred.get("is_logged_in"):
            pw = decrypt(cred["password_enc"])
            if pw != "sso":
                await scraper.login(cred["username"], pw)
            set_logged_in(site, True)
        jobs_found = await scraper.search_jobs(keywords, location, {})
        saved_ids = []
        for job in jobs_found:
            jid = upsert_job(job)
            saved_ids.append(jid)
        await manager.broadcast({"type": "search_result", "site": site, "count": len(jobs_found), "job_ids": saved_ids})
        return len(jobs_found)

    total_found = 0
    sites_to_search = [s for s in params.sites if s in SCRAPERS or s in CUSTOM_SCRAPERS]
    for site in sites_to_search:
        try:
            n = await search_site(site)
            total_found += n
        except Exception as exc:
            await manager.broadcast({"type": "log", "message": f"Search error on {site}: {exc}", "level": "error"})

    await manager.broadcast({"type": "search_done", "total": total_found, "by_site": {}})
    await manager.broadcast({"type": "log", "message": f"✓ Found {total_found} job(s). Starting applications…", "level": "success"})

    # ── Step 2: apply to everything just found ──────────────────────────────
    new_jobs = get_jobs(status="new")
    if not new_jobs:
        await manager.broadcast({"type": "apply_all_done", "applied": 0, "skipped": 0})
        await set_headless_mode(False)   # restore visible mode
        return {"searched": total_found, "applied": 0, "skipped": 0}

    applied = 0
    skipped = 0
    total = len(new_jobs)
    await manager.broadcast({"type": "apply_all_start", "total": total})

    try:
        for i, job in enumerate(new_jobs):
            # Check for stop request before each job
            if _CANCEL["requested"]:
                await manager.broadcast({"type": "log", "message": f"⏹ Stopped after {i} job(s).", "level": "warning"})
                await manager.broadcast({"type": "apply_all_done", "applied": applied, "skipped": skipped + (total - i), "stopped": True})
                return {"searched": total_found, "applied": applied, "skipped": skipped, "stopped": True}

            await manager.broadcast({
                "type": "apply_all_progress",
                "current": i + 1,
                "total": total,
                "job": f"{job['title']} @ {job['company']}",
            })
            try:
                result = await api_apply(job["id"])
                if result.get("status") == "applied":
                    applied += 1
                else:
                    skipped += 1
                # Close any extra browser tabs opened during apply
                try:
                    from scrapers.base import _context
                    if _context:
                        pages = _context.pages
                        if len(pages) > 1:
                            for p in pages[1:]:
                                await p.close()
                except Exception:
                    pass
                await asyncio.sleep(1.5)
            except Exception as e:
                await manager.broadcast({"type": "log", "message": f"Skipped {job['title']}: {e}", "level": "warning"})
                skipped += 1

        await manager.broadcast({"type": "apply_all_done", "applied": applied, "skipped": skipped})
        return {"searched": total_found, "applied": applied, "skipped": skipped}
    finally:
        # Always restore visible browser mode when the run ends (normally, stopped, or error)
        await set_headless_mode(False)

# ── Apply All new jobs ─────────────────────────────────────────────────────────

@app.post("/api/apply-all")
async def api_apply_all():
    """
    Apply to every job in the DB that hasn't been applied to yet.
    Streams progress via WebSocket. Returns summary when done.
    """
    new_jobs = get_jobs(status="new")
    if not new_jobs:
        await manager.broadcast({"type": "apply_all_done", "applied": 0, "skipped": 0})
        return {"applied": 0, "skipped": 0, "message": "No new jobs to apply to."}

    profile = get_profile()
    if not profile:
        raise HTTPException(status_code=400, detail="Complete your profile before applying.")

    _CANCEL["requested"] = False
    await set_headless_mode(True)  # run headless so browser doesn't steal focus

    applied = 0
    skipped = 0
    total = len(new_jobs)
    await manager.broadcast({"type": "apply_all_start", "total": total})

    try:
        for i, job in enumerate(new_jobs):
            if _CANCEL["requested"]:
                await manager.broadcast({"type": "log", "message": f"⏹ Stopped after {i} job(s).", "level": "warning"})
                await manager.broadcast({"type": "apply_all_done", "applied": applied, "skipped": skipped + (total - i), "stopped": True})
                return {"applied": applied, "skipped": skipped, "stopped": True, "total": total}

            await manager.broadcast({
                "type": "apply_all_progress",
                "current": i + 1,
                "total": total,
                "job": f"{job['title']} @ {job['company']}",
            })
            try:
                result = await api_apply(job["id"])
                if result.get("status") == "applied":
                    applied += 1
                else:
                    skipped += 1
                # Close any extra tabs opened during apply
                try:
                    from scrapers.base import _context
                    if _context:
                        pages = _context.pages
                        if len(pages) > 1:
                            for p in pages[1:]:
                                await p.close()
                except Exception:
                    pass
                await asyncio.sleep(1.5)
            except Exception as e:
                await manager.broadcast({"type": "log", "message": f"Skipped {job['title']}: {e}", "level": "warning"})
                skipped += 1

        await manager.broadcast({"type": "apply_all_done", "applied": applied, "skipped": skipped})
        return {"applied": applied, "skipped": skipped, "total": total}
    finally:
        await set_headless_mode(False)  # restore visible mode for SSO

# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=False)
