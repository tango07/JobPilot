"""
SQLite database management for job search app.
Tables: profile, credentials, jobs, applications
"""

import hashlib
import os
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

DB_PATH = Path(__file__).parent.parent / "jobsearch.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS custom_sites (
            key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            base_url TEXT NOT NULL,
            search_url TEXT NOT NULL,
            color TEXT DEFAULT '#6366f1',
            bg TEXT DEFAULT '#eef2ff',
            label TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_name TEXT DEFAULT 'Default',
            is_active INTEGER DEFAULT 0,
            full_name TEXT,
            email TEXT,
            phone TEXT,
            location TEXT,
            linkedin_url TEXT,
            github_url TEXT,
            portfolio_url TEXT,
            resume_path TEXT,
            years_experience INTEGER DEFAULT 0,
            current_title TEXT,
            desired_title TEXT,
            desired_salary TEXT,
            skills TEXT DEFAULT '[]',
            summary TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site TEXT UNIQUE NOT NULL,
            username TEXT,
            password_enc TEXT,
            extra_data TEXT DEFAULT '{}',
            is_logged_in INTEGER DEFAULT 0,
            last_login TEXT
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site TEXT NOT NULL,
            job_id TEXT,
            title TEXT,
            company TEXT,
            location TEXT,
            job_type TEXT,
            salary TEXT,
            description TEXT,
            url TEXT,
            apply_url TEXT,
            easy_apply INTEGER DEFAULT 0,
            date_posted TEXT,
            date_found TEXT,
            status TEXT DEFAULT 'new',
            UNIQUE(site, job_id)
        );

        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER REFERENCES jobs(id),
            site TEXT,
            title TEXT,
            company TEXT,
            applied_at TEXT,
            status TEXT DEFAULT 'applied',
            notes TEXT,
            response TEXT
        );

        CREATE TABLE IF NOT EXISTS saved_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            keywords TEXT NOT NULL,
            location TEXT DEFAULT '',
            sites TEXT DEFAULT '[]',
            filters TEXT DEFAULT '{}',
            created_at TEXT,
            last_run TEXT,
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            reminder_type TEXT NOT NULL DEFAULT 'follow_up',
            due_at TEXT NOT NULL,
            note TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT,
            done_at TEXT
        );

        CREATE TABLE IF NOT EXISTS job_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            sentiment TEXT NOT NULL DEFAULT 'useful',
            comment TEXT DEFAULT '',
            created_at TEXT
        );
        """)

        # ── Migrations for existing databases ──────────────────────────────────
        for col, defn in [
            ("profile_name",    "TEXT DEFAULT 'Default'"),
            ("is_active",       "INTEGER DEFAULT 0"),
            ("avatar_path",     "TEXT"),
            ("password_hash",   "TEXT"),
            ("password_salt",   "TEXT"),
            ("claude_api_key",  "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE profile ADD COLUMN {col} {defn}")
            except Exception:
                pass  # column already exists

        # Ensure at least one profile row exists and exactly one is active
        count = conn.execute("SELECT COUNT(*) FROM profile").fetchone()[0]
        if count == 0:
            conn.execute(
                "INSERT INTO profile (profile_name, is_active) VALUES ('Default', 1)"
            )
        else:
            active = conn.execute(
                "SELECT COUNT(*) FROM profile WHERE is_active=1"
            ).fetchone()[0]
            if active == 0:
                conn.execute(
                    "UPDATE profile SET is_active=1 WHERE id=(SELECT MIN(id) FROM profile)"
                )

        # ── Migrate credentials table to per-profile ──────────────────────────
        cred_cols = [r[1] for r in conn.execute("PRAGMA table_info(credentials)").fetchall()]
        if 'profile_id' not in cred_cols:
            conn.executescript("""
                ALTER TABLE credentials RENAME TO credentials_old;
                CREATE TABLE credentials (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id  INTEGER NOT NULL DEFAULT 1,
                    site        TEXT NOT NULL,
                    username    TEXT,
                    password_enc TEXT,
                    extra_data  TEXT DEFAULT '{}',
                    is_logged_in INTEGER DEFAULT 0,
                    last_login  TEXT,
                    UNIQUE(profile_id, site)
                );
                INSERT OR IGNORE INTO credentials
                    (id, profile_id, site, username, password_enc, extra_data, is_logged_in, last_login)
                SELECT id, 1, site, username, password_enc, extra_data, is_logged_in, last_login
                FROM credentials_old;
                DROP TABLE credentials_old;
            """)


# --- Profile ---

# Fields whose values are stored encrypted (Fernet). All others are plain text.
_PII_FIELDS = {
    "full_name", "email", "phone", "location",
    "linkedin_url", "github_url", "portfolio_url",
    "desired_salary", "summary", "resume_path",
}

def _safe_decrypt(value: str) -> str:
    """Decrypt a Fernet token, falling back to the raw value for unencrypted legacy data."""
    if not value:
        return value
    from encryption import decrypt
    try:
        from cryptography.fernet import InvalidToken
        result = decrypt(value)
        # decrypt() returns "" on failure — detect that and fall back to raw value
        # (Empty string is also a valid decrypted value, but only if the encrypted token
        # decrypts correctly; the actual empty-string case is handled by the `if not value` guard above)
        return result if result else value
    except Exception:
        return value  # legacy plain-text data


def _row_to_profile(row) -> Dict:
    d = dict(row)
    d["skills"] = json.loads(d.get("skills") or "[]")
    # Decrypt PII fields
    for field in _PII_FIELDS:
        if field in d and d[field]:
            d[field] = _safe_decrypt(d[field])
    return d


def get_profile() -> Optional[Dict]:
    """Return the currently active profile."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM profile WHERE is_active=1 ORDER BY id LIMIT 1"
        ).fetchone()
        return _row_to_profile(row) if row else None


def save_profile(data: Dict, profile_id: int = None) -> Dict:
    """Save data to the active profile (or a specific profile_id)."""
    from encryption import encrypt
    data = dict(data)
    if "skills" in data:
        data["skills"] = json.dumps(data.get("skills") or [])
    data["updated_at"] = datetime.utcnow().isoformat()
    # Encrypt PII fields before storing
    for field in _PII_FIELDS:
        if field in data and data[field]:
            data[field] = encrypt(str(data[field]))
    # Never overwrite multi-profile control columns via this path
    data.pop("id", None)
    data.pop("is_active", None)

    active = get_profile()
    target_id = profile_id or (active["id"] if active else None)

    with get_conn() as conn:
        if target_id:
            cols = [k for k in data if k not in ("profile_name",)]
            # allow profile_name update if explicitly passed
            if "profile_name" in data:
                cols = list(data.keys())
            sets = ", ".join(f"{c}=?" for c in cols)
            vals = [data[c] for c in cols] + [target_id]
            conn.execute(f"UPDATE profile SET {sets} WHERE id=?", vals)
        else:
            data["is_active"] = 1
            cols = list(data.keys())
            conn.execute(
                f"INSERT INTO profile ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                [data[c] for c in cols],
            )
    return get_profile()


# ── Multi-profile helpers ───────────────────────────────────────────────────

def list_profiles() -> List[Dict]:
    """Return all profiles (id, profile_name, is_active, current_title, has_password, avatar_path)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, profile_name, is_active, current_title, full_name, "
            "avatar_path, (password_hash IS NOT NULL) AS has_password "
            "FROM profile ORDER BY id"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        # full_name may be encrypted; decrypt for display
        if d.get("full_name"):
            d["full_name"] = _safe_decrypt(d["full_name"])
        result.append(d)
    return result


def create_profile(name: str) -> Dict:
    """Insert a new blank profile and return it."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO profile (profile_name, is_active) VALUES (?, 0)",
            (name,),
        )
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = conn.execute("SELECT * FROM profile WHERE id=?", (new_id,)).fetchone()
        return _row_to_profile(row)


def activate_profile(profile_id: int) -> Optional[Dict]:
    """Set profile_id as active, deactivate all others."""
    with get_conn() as conn:
        conn.execute("UPDATE profile SET is_active=0")
        conn.execute("UPDATE profile SET is_active=1 WHERE id=?", (profile_id,))
        row = conn.execute("SELECT * FROM profile WHERE id=?", (profile_id,)).fetchone()
        return _row_to_profile(row) if row else None


def delete_profile(profile_id: int) -> bool:
    """Delete a profile. Cannot delete the last remaining profile."""
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM profile").fetchone()[0]
        if total <= 1:
            return False  # Refuse to delete the last profile
        was_active = conn.execute(
            "SELECT is_active FROM profile WHERE id=?", (profile_id,)
        ).fetchone()
        conn.execute("DELETE FROM profile WHERE id=?", (profile_id,))
        # If we deleted the active one, activate the lowest remaining id
        if was_active and was_active[0]:
            conn.execute(
                "UPDATE profile SET is_active=1 WHERE id=(SELECT MIN(id) FROM profile)"
            )
        return True


# --- Credentials ---

def _active_id() -> int:
    """Return the active profile's ID (falls back to 1)."""
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM profile WHERE is_active=1 LIMIT 1").fetchone()
        return row[0] if row else 1


# ── Password helpers ────────────────────────────────────────────────────────

def _hash_pw(password: str, salt: bytes = None):
    """PBKDF2-SHA256 hash. Returns (hash_hex, salt_hex)."""
    if salt is None:
        salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 200_000)
    return h.hex(), salt.hex()


def set_profile_password(profile_id: int, password: str) -> None:
    """Set or remove a profile's password. Pass empty string to remove."""
    if not password:
        with get_conn() as conn:
            conn.execute(
                "UPDATE profile SET password_hash=NULL, password_salt=NULL WHERE id=?",
                (profile_id,)
            )
        return
    h, s = _hash_pw(password)
    with get_conn() as conn:
        conn.execute(
            "UPDATE profile SET password_hash=?, password_salt=? WHERE id=?",
            (h, s, profile_id)
        )


def verify_profile_password(profile_id: int, password: str) -> bool:
    """Return True if password matches or profile has no password."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT password_hash, password_salt FROM profile WHERE id=?", (profile_id,)
        ).fetchone()
    if not row or not row["password_hash"]:
        return True  # no password set — always allow
    salt = bytes.fromhex(row["password_salt"])
    check, _ = _hash_pw(password, salt)
    return check == row["password_hash"]


# ── Per-profile Claude API key ──────────────────────────────────────────────

def get_profile_claude_key(profile_id: int = None) -> str:
    """Return the decrypted Claude API key for a profile."""
    pid = profile_id if profile_id is not None else _active_id()
    from encryption import decrypt
    with get_conn() as conn:
        row = conn.execute(
            "SELECT claude_api_key FROM profile WHERE id=?", (pid,)
        ).fetchone()
    if row and row["claude_api_key"]:
        return decrypt(row["claude_api_key"])
    return ""


def set_profile_claude_key(key: str, profile_id: int = None) -> None:
    """Encrypt and save the Claude API key for a profile."""
    pid = profile_id if profile_id is not None else _active_id()
    from encryption import encrypt
    enc = encrypt(key.strip()) if key and key.strip() else None
    with get_conn() as conn:
        conn.execute(
            "UPDATE profile SET claude_api_key=? WHERE id=?", (enc, pid)
        )


def get_credential(site: str, profile_id: int = None) -> Optional[Dict]:
    pid = profile_id if profile_id is not None else _active_id()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM credentials WHERE profile_id=? AND site=?", (pid, site)
        ).fetchone()
        if row:
            d = dict(row)
            d["extra_data"] = json.loads(d.get("extra_data") or "{}")
            return d
        return None


def save_credential(site: str, username: str, password_enc: str,
                    extra_data: Dict = None, profile_id: int = None) -> None:
    pid = profile_id if profile_id is not None else _active_id()
    extra = json.dumps(extra_data or {})
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO credentials (profile_id, site, username, password_enc, extra_data)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(profile_id, site) DO UPDATE SET
                username=excluded.username,
                password_enc=excluded.password_enc,
                extra_data=excluded.extra_data
        """, (pid, site, username, password_enc, extra))


def set_logged_in(site: str, logged_in: bool, profile_id: int = None) -> None:
    pid = profile_id if profile_id is not None else _active_id()
    ts = datetime.utcnow().isoformat() if logged_in else None
    with get_conn() as conn:
        conn.execute(
            "UPDATE credentials SET is_logged_in=?, last_login=? WHERE profile_id=? AND site=?",
            (1 if logged_in else 0, ts, pid, site)
        )


def all_credentials(profile_id: int = None) -> List[Dict]:
    pid = profile_id if profile_id is not None else _active_id()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT site, username, is_logged_in, last_login FROM credentials WHERE profile_id=?",
            (pid,)
        ).fetchall()
        return [dict(r) for r in rows]


# --- Jobs ---

def upsert_job(data: Dict) -> int:
    init_db()
    data["date_found"] = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO jobs (site, job_id, title, company, location, job_type,
                salary, description, url, apply_url, easy_apply, date_posted, date_found, status)
            VALUES (:site, :job_id, :title, :company, :location, :job_type,
                :salary, :description, :url, :apply_url, :easy_apply, :date_posted, :date_found, :status)
            ON CONFLICT(site, job_id) DO UPDATE SET
                title=excluded.title, company=excluded.company,
                location=excluded.location, salary=excluded.salary,
                easy_apply=excluded.easy_apply, date_found=excluded.date_found
        """, data)
        row = conn.execute("SELECT id FROM jobs WHERE site=? AND job_id=?",
                           (data["site"], data["job_id"])).fetchone()
        return row["id"]


def get_jobs(site: str = None, status: str = None, limit: int = 100, offset: int = 0) -> List[Dict]:
    init_db()
    query = "SELECT * FROM jobs WHERE 1=1"
    params = []
    if site:
        query += " AND site=?"
        params.append(site)
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY date_found DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def update_job_status(job_id: int, status: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))


def count_jobs(site: str = None) -> int:
    query = "SELECT COUNT(*) FROM jobs"
    params = []
    if site:
        query += " WHERE site=?"
        params.append(site)
    with get_conn() as conn:
        return conn.execute(query, params).fetchone()[0]


# --- Applications ---

def create_application(job_id: int, site: str, title: str, company: str, notes: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO applications (job_id, site, title, company, applied_at, status, notes)
            VALUES (?, ?, ?, ?, ?, 'applied', ?)
        """, (job_id, site, title, company, datetime.utcnow().isoformat(), notes))
        return cur.lastrowid


def get_applications(status: str = None, limit: int = 100) -> List[Dict]:
    query = "SELECT * FROM applications"
    params = []
    if status:
        query += " WHERE status=?"
        params.append(status)
    query += " ORDER BY applied_at DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def update_application_status(app_id: int, status: str, response: str = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE applications SET status=?, response=? WHERE id=?",
            (status, response, app_id)
        )


def count_applications(status: str = None) -> int:
    query = "SELECT COUNT(*) FROM applications"
    params = []
    if status:
        query += " WHERE status=?"
        params.append(status)
    with get_conn() as conn:
        return conn.execute(query, params).fetchone()[0]


# --- Saved searches ---

def create_saved_search(name: str, keywords: str, location: str = '', sites: List[str] = None,
                       filters: Dict[str, Any] = None) -> Dict[str, Any]:
    init_db()
    created = datetime.utcnow().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO saved_searches (name, keywords, location, sites, filters, created_at, last_run, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                name.strip() or "Saved Search",
                keywords.strip(),
                location.strip(),
                json.dumps(sites or []),
                json.dumps(filters or {}),
                created,
                created,
            ),
        )
        row = conn.execute("SELECT * FROM saved_searches WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)


def list_saved_searches() -> List[Dict[str, Any]]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM saved_searches ORDER BY created_at DESC"
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["sites"] = json.loads(d.get("sites") or "[]")
        d["filters"] = json.loads(d.get("filters") or "{}")
        result.append(d)
    return result


def update_saved_search(search_id: int, **kwargs) -> Optional[Dict[str, Any]]:
    init_db()
    if not kwargs:
        return None
    with get_conn() as conn:
        updates = []
        values = []
        for key, value in kwargs.items():
            if key in {"sites", "filters"}:
                value = json.dumps(value)
            updates.append(f"{key}=?")
            values.append(value)
        values.append(search_id)
        conn.execute(f"UPDATE saved_searches SET {', '.join(updates)} WHERE id=?", values)
        row = conn.execute("SELECT * FROM saved_searches WHERE id=?", (search_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["sites"] = json.loads(d.get("sites") or "[]")
        d["filters"] = json.loads(d.get("filters") or "{}")
        return d


def delete_saved_search(search_id: int) -> bool:
    init_db()
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM saved_searches WHERE id=?", (search_id,))
        return cur.rowcount > 0


# --- Reminders ---

def create_reminder(job_id: int, reminder_type: str, due_at: str, note: str = '') -> Dict[str, Any]:
    init_db()
    created = datetime.utcnow().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO reminders (job_id, reminder_type, due_at, note, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (job_id, reminder_type, due_at, note, created),
        )
        row = conn.execute("SELECT * FROM reminders WHERE id=?", (cur.lastrowid,)).fetchone()
        result = dict(row)
        result["type"] = result.get("reminder_type")
        return result


def list_reminders(status: str = None, job_id: int = None) -> List[Dict[str, Any]]:
    init_db()
    query = "SELECT * FROM reminders WHERE 1=1"
    params = []
    if status:
        query += " AND status=?"
        params.append(status)
    if job_id is not None:
        query += " AND job_id=?"
        params.append(job_id)
    query += " ORDER BY due_at ASC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["type"] = d.get("reminder_type")
            result.append(d)
        return result


def mark_reminder_done(reminder_id: int) -> Dict[str, Any]:
    init_db()
    done_at = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE reminders SET status='done', done_at=? WHERE id=?",
            (done_at, reminder_id),
        )
        row = conn.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
    if row:
        return {"id": row["id"], "done": True, "status": row["status"], "done_at": row["done_at"]}
    return {"id": reminder_id, "done": False}


# --- Job feedback ---

def create_feedback(job_id: int, sentiment: str, comment: str = '') -> Dict[str, Any]:
    init_db()
    created = datetime.utcnow().isoformat()
    sentiment = (sentiment or 'useful').strip() or 'useful'
    comment = (comment or '').strip()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO job_feedback (job_id, sentiment, comment, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (job_id, sentiment, comment, created),
        )
        row = conn.execute("SELECT * FROM job_feedback WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)


def list_feedback(job_id: int = None) -> List[Dict[str, Any]]:
    init_db()
    query = "SELECT * FROM job_feedback"
    params = []
    if job_id is not None:
        query += " WHERE job_id=?"
        params.append(job_id)
    query += " ORDER BY created_at DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def feedback_summary() -> Dict[str, Any]:
    init_db()
    with get_conn() as conn:
        overall = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN sentiment='useful' THEN 1 ELSE 0 END) AS useful,
                   SUM(CASE WHEN sentiment='neutral' THEN 1 ELSE 0 END) AS neutral,
                   SUM(CASE WHEN sentiment='not_useful' THEN 1 ELSE 0 END) AS not_useful
            FROM job_feedback
            """
        ).fetchone()
        by_site = conn.execute(
            """
            SELECT COALESCE(j.site, 'unknown') AS site,
                   COUNT(*) AS total,
                   SUM(CASE WHEN f.sentiment='useful' THEN 1 ELSE 0 END) AS useful,
                   SUM(CASE WHEN f.sentiment='neutral' THEN 1 ELSE 0 END) AS neutral,
                   SUM(CASE WHEN f.sentiment='not_useful' THEN 1 ELSE 0 END) AS not_useful
            FROM job_feedback f
            LEFT JOIN jobs j ON j.id=f.job_id
            GROUP BY COALESCE(j.site, 'unknown')
            ORDER BY total DESC, site ASC
            """
        ).fetchall()

    def normalize(row) -> Dict[str, Any]:
        result = dict(row)
        total = result.get("total") or 0
        result["useful_rate"] = round((result.get("useful") or 0) / total * 100) if total else 0
        return result

    return {
        "overall": normalize(overall),
        "by_site": [normalize(row) for row in by_site],
    }


# --- Maintenance ---

def clear_all_jobs() -> int:
    """Delete every job and its applications. Returns number of jobs deleted."""
    with get_conn() as conn:
        conn.execute("DELETE FROM applications")
        return conn.execute("DELETE FROM jobs").rowcount


def cleanup_old_jobs(days: int = 10) -> int:
    """
    Delete jobs (and their applications) whose date_found is older than `days` days.
    Also deletes jobs that have a date_posted clearly older than `days` days.
    Returns the number of rows deleted.
    """
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        # Remove orphan applications first (FK safety)
        conn.execute("""
            DELETE FROM applications WHERE job_id IN (
                SELECT id FROM jobs
                WHERE (date_found  != '' AND date_found  IS NOT NULL AND date_found  < ?)
                   OR (date_posted != '' AND date_posted IS NOT NULL AND date_posted < ?)
            )
        """, (cutoff, cutoff))
        cur = conn.execute("""
            DELETE FROM jobs
            WHERE (date_found  != '' AND date_found  IS NOT NULL AND date_found  < ?)
               OR (date_posted != '' AND date_posted IS NOT NULL AND date_posted < ?)
        """, (cutoff, cutoff))
        return cur.rowcount


# --- Custom Sites ---

def get_custom_sites() -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM custom_sites ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def upsert_custom_site(key: str, name: str, base_url: str, search_url: str,
                       color: str, bg: str, label: str) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO custom_sites (key, name, base_url, search_url, color, bg, label)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                name=excluded.name, base_url=excluded.base_url,
                search_url=excluded.search_url, color=excluded.color,
                bg=excluded.bg, label=excluded.label
        """, (key, name, base_url, search_url, color, bg, label))


def delete_custom_site(key: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM custom_sites WHERE key=?", (key,))
