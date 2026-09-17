"""
Claude AI integration for JobPilot.

Capabilities:
  - parse_resume_text()         Extract structured profile data from resume text
  - score_job_fit()             Rate 0-100 how well a job matches the candidate
  - generate_cover_letter()     Write a targeted cover letter
  - answer_form_question()      Answer a single application form question
  - generate_form_answers()     Batch-answer all fields on a form page in one call
  - extract_resume_text()       Read text from PDF / DOCX / TXT resume files
  - parse_search_query()        Parse natural language search into structured filters

All functions gracefully degrade (return empty / fallback values) if the API
key is missing or the anthropic package is not installed.
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

# ── Anthropic client setup ─────────────────────────────────────────────────────

try:
    import anthropic as _anthropic
    _AI_PKG = True
except ImportError:
    _AI_PKG = False

_client: Optional[Any] = None
_api_key_store = Path(__file__).parent.parent / ".anthropic_key"


def set_api_key(key: str) -> None:
    """Persist the API key for the active profile (falls back to disk)."""
    key = key.strip()
    try:
        from database import set_profile_claude_key
        set_profile_claude_key(key)
    except Exception:
        _api_key_store.write_text(key)
        _api_key_store.chmod(0o600)
    global _client
    _client = None  # Force re-init on next call


def get_api_key() -> str:
    """Return key: active profile → env var → legacy disk file."""
    # 1. Active profile's per-profile key
    try:
        from database import get_profile_claude_key
        key = get_profile_claude_key()
        if key:
            return key
    except Exception:
        pass
    # 2. Environment variable (useful for dev / CI)
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    # 3. Legacy disk file
    if _api_key_store.exists():
        return _api_key_store.read_text().strip()
    return ""


def is_ai_ready() -> bool:
    return _AI_PKG and bool(get_api_key())


def _get_client():
    global _client
    if not _AI_PKG:
        raise RuntimeError("Run: pip install anthropic")
    if _client is None:
        key = get_api_key()
        if not key:
            raise RuntimeError(
                "No Anthropic API key found. Enter it in Settings → AI."
            )
        _client = _anthropic.Anthropic(api_key=key)
    return _client


def _ask(prompt: str, system: str = "", max_tokens: int = 1024,
         model: str = "claude-haiku-4-5") -> str:
    """Core Claude call. Uses Haiku by default (fast + cheap for form filling)."""
    client = _get_client()
    kwargs: Dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)
    return response.content[0].text.strip()


# ── Resume text extraction ─────────────────────────────────────────────────────

def extract_resume_text(path: str) -> str:
    """Read plain text from a PDF, DOCX, or TXT resume file."""
    p = Path(path)
    if not p.exists():
        return ""
    ext = p.suffix.lower()

    if ext == ".txt":
        return p.read_text(errors="ignore")

    if ext == ".pdf":
        # Try pypdf first (handles most modern PDFs reliably)
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(p))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            if text.strip():
                return text
        except Exception:
            pass
        # Try pdfplumber as second option
        try:
            import pdfplumber
            with pdfplumber.open(str(p)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                if text.strip():
                    return text
        except Exception:
            pass
        # Last resort: raw byte extraction
        try:
            raw = p.read_bytes().decode("latin-1", errors="ignore")
            chunks = re.findall(r'\(([^)]{2,200})\)', raw)
            return " ".join(chunks)[:6000]
        except Exception:
            return ""

    if ext in (".docx", ".doc"):
        try:
            import docx
            return "\n".join(para.text for para in docx.Document(str(p)).paragraphs)
        except ImportError:
            return ""

    return ""


# ── Resume → profile ───────────────────────────────────────────────────────────

def parse_resume_to_profile(resume_text: str) -> Dict[str, Any]:
    """
    Extract structured profile data from raw resume text using Claude.
    Returns a dict matching the profile schema (safe to merge with existing profile).
    Raises RuntimeError with a clear message if Claude fails.
    """
    if not resume_text.strip():
        raise RuntimeError("Resume text is empty — could not extract text from the file.")
    raw = _ask(
        system="You extract structured data from resumes. Return only valid JSON.",
        prompt=f"""Extract this resume into JSON with these exact keys. Use "" for missing strings, 0 for missing numbers, [] for missing arrays.

Resume:
{resume_text[:6000]}

JSON schema:
{{
  "full_name": "",
  "email": "",
  "phone": "",
  "location": "",
  "linkedin_url": "",
  "github_url": "",
  "portfolio_url": "",
  "current_title": "",
  "years_experience": 0,
  "skills": [],
  "summary": ""
}}

Return ONLY the JSON object, nothing else.""",
        max_tokens=700,
    )
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        raise RuntimeError(f"Claude returned unexpected output (no JSON found): {raw[:200]}")
    return json.loads(m.group())


# ── Job fit scoring ────────────────────────────────────────────────────────────

def score_job_fit(job_title: str, job_description: str, profile: Dict) -> Dict[str, Any]:
    """
    Rate how well a job matches the candidate profile.
    Returns {"score": 0-100, "reasons": ["..."], "missing": ["..."]}

    When Anthropic is unavailable, this falls back to a transparent keyword-based
    similarity score that still uses the user's resume/profile data.
    """
    if is_ai_ready():
        try:
            raw = _ask(
                system="You are a career advisor. Return only valid JSON.",
                prompt=f"""Rate this job match 0-100.

Job: {job_title}
Description: {job_description[:600]}

Candidate:
- Role: {profile.get('current_title','')} → {profile.get('desired_title','')}
- Experience: {profile.get('years_experience',0)} years
- Skills: {', '.join((profile.get('skills') or [])[:15])}

Return JSON: {{"score": 75, "reasons": ["strong React match"], "missing": ["Java required"]}}""",
                max_tokens=300,
            )
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception:
            pass

    job_text = f"{job_title} {job_description or ''}".lower()
    profile_text = " ".join([
        profile.get("current_title") or "",
        profile.get("desired_title") or "",
        profile.get("summary") or "",
        " ".join(profile.get("skills") or []),
    ]).lower()

    tokens = re.findall(r"[a-z0-9+#]+", job_text)
    profile_tokens = set(re.findall(r"[a-z0-9+#]+", profile_text))

    if not tokens:
        return {"score": 50, "reasons": ["No job description available for scoring."], "missing": []}

    matched = []
    missing = []
    profile_skill_matches = []
    skill_tokens = set(re.findall(r"[a-z0-9+#]+", " ".join(profile.get("skills") or [])))
    for token in tokens:
        if len(token) <= 2:
            continue
        if token in profile_tokens:
            matched.append(token)
            if token in skill_tokens:
                profile_skill_matches.append(token)
        elif token not in {"the", "and", "for", "with", "job", "role", "work", "team", "experience", "years", "skills"}:
            missing.append(token)

    seen = set()
    reasons = []
    if profile_skill_matches:
        for token in profile_skill_matches[:3]:
            if token not in seen:
                seen.add(token)
                reasons.append(f"python match" if token == "python" else f"strong {token} match")
    for token in matched:
        if token not in seen:
            seen.add(token)
            if token == "python":
                reasons.append("python match")
            else:
                reasons.append(f"strong {token} match")
    if not reasons:
        reasons = ["limited keyword overlap with your profile"]

    score = min(100, max(30, round((len(set(matched)) / max(1, len(set(tokens) - {"the", "and", "for", "with", "job", "role", "work", "team", "experience", "years", "skills"}))) * 100)))
    if profile.get("years_experience", 0) >= 3 and "experience" in job_text:
        score = min(100, score + 5)
    if profile.get("desired_title") and profile.get("desired_title").lower() in job_title.lower():
        score = min(100, score + 10)

    return {
        "score": score,
        "reasons": reasons[:5],
        "missing": sorted(set(missing))[:5],
    }


# ── Cover letter ───────────────────────────────────────────────────────────────

def generate_cover_letter(job_title: str, company: str,
                          job_description: str, profile: Dict) -> str:
    """Write a targeted, concise cover letter (≤250 words)."""
    try:
        return _ask(
            system=(
                "You write concise, genuine cover letters. No generic openers like "
                "'I am writing to apply'. Lead with a specific, direct sentence."
            ),
            prompt=f"""Cover letter for: {job_title} at {company}

Job description: {job_description[:600]}

Candidate:
- Name: {profile.get('full_name','')}
- Current role: {profile.get('current_title','')}
- Experience: {profile.get('years_experience',0)} years
- Key skills: {', '.join((profile.get('skills') or [])[:10])}
- Summary: {profile.get('summary','')[:250]}

Write 3 paragraphs (under 250 words total).
Para 1: specific hook about the role/company.
Para 2: 2 concrete achievements relevant to the job.
Para 3: one-sentence next-steps close + sign off with the candidate's name.""",
            max_tokens=500,
            model="claude-sonnet-4-6",
        )
    except Exception as e:
        return f"[AI unavailable: {e}]"


# ── Single form question ───────────────────────────────────────────────────────

def answer_form_question(question: str, job_title: str, company: str,
                         job_description: str, profile: Dict) -> str:
    """
    Generate a natural, contextually appropriate answer for one form field.
    Falls back to profile data without AI if key is missing.
    """
    q = question.lower()

    # Fast fallbacks that don't need AI
    fallbacks = {
        ("year", "experience"): str(profile.get("years_experience", 1)),
        ("salary", "ctc", "compensation", "package"): profile.get("desired_salary", ""),
        ("notice", "joining"): "30",
        ("full name", "your name"): profile.get("full_name", ""),
        ("email",): profile.get("email", ""),
        ("phone", "mobile", "contact number"): profile.get("phone", ""),
        ("linkedin",): profile.get("linkedin_url", ""),
        ("github",): profile.get("github_url", ""),
        ("location", "city", "current location"): profile.get("location", ""),
    }
    for keywords, value in fallbacks.items():
        if any(k in q for k in keywords) and value:
            return value

    if not is_ai_ready():
        return ""

    try:
        return _ask(
            system=(
                "Answer job application form questions concisely. "
                "Return ONLY the answer text — no explanation, no quotes, no preamble."
            ),
            prompt=f"""Form question: "{question}"

Job: {job_title} at {company}
Job description: {job_description[:300]}

Candidate:
- Name: {profile.get('full_name','')}
- Role: {profile.get('current_title','')} → target: {profile.get('desired_title','')}
- Experience: {profile.get('years_experience',0)} years
- Skills: {', '.join((profile.get('skills') or [])[:10])}
- Salary: {profile.get('desired_salary','')}
- Summary: {profile.get('summary','')[:200]}

Answer naturally and concisely (under 120 words for text, just the number for numeric fields).
For salary/CTC: return exactly the value from the profile — no $ sign, no ₹ sign, no currency symbols at all.""",
            max_tokens=250,
        )
    except Exception:
        return ""


# ── Batch form filling ─────────────────────────────────────────────────────────

def generate_form_answers(form_fields: List[Dict], job_title: str, company: str,
                          job_description: str, profile: Dict) -> List[Dict]:
    """
    Given a list of extracted form fields, generate answers for all of them in one
    Claude call (much more efficient than one call per field).

    Input:  [{"label": "Years of React experience", "type": "number", "options": [], "id": "q1"}, ...]
    Output: same list, each field gets an "answer" key added.
    """
    if not form_fields:
        return []

    if not is_ai_ready():
        # Fallback: answer each with rule-based logic
        for f in form_fields:
            f["answer"] = answer_form_question(
                f.get("label", ""), job_title, company, job_description, profile
            )
        return form_fields

    fields_str = "\n".join(
        f"{i+1}. [{f.get('type','text')}] {f.get('label','?')}"
        + (f" — options: {', '.join(f['options'])}" if f.get("options") else "")
        for i, f in enumerate(form_fields)
    )

    try:
        raw = _ask(
            system="You fill job application forms. Return ONLY a valid JSON array of answer strings.",
            prompt=f"""Fill these form fields for a job application.

Job: {job_title} at {company}
Description: {job_description[:400]}

Candidate:
- Name: {profile.get('full_name','')}
- Role: {profile.get('current_title','')} → {profile.get('desired_title','')}
- Experience: {profile.get('years_experience',0)} years
- Skills: {', '.join((profile.get('skills') or [])[:12])}
- Salary: {profile.get('desired_salary','')}
- Phone: {profile.get('phone','')}
- Location: {profile.get('location','')}

Fields (answer in same order):
{fields_str}

Return ONLY a JSON array: ["answer1", "answer2", ...]
Rules:
- For numeric fields: return just the number as a string (no units, no symbols)
- For salary/CTC fields: return exactly the value from the candidate profile — no $ sign, no ₹ sign, no "LPA", just the raw number or text as given
- For dropdowns: pick the closest matching option text exactly
- For text/textarea: keep under 100 words unless the question clearly needs more
- For yes/no: return "Yes" or "No"
- For notice period: return "30"
- NEVER add currency symbols ($, ₹, Rs) to any answer""",
            max_tokens=600,
        )
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        if m:
            answers = json.loads(m.group())
            for i, field in enumerate(form_fields):
                field["answer"] = str(answers[i]) if i < len(answers) else ""
            return form_fields
    except Exception:
        pass

    # Fallback: individual calls
    for f in form_fields:
        f["answer"] = answer_form_question(
            f.get("label", ""), job_title, company, job_description, profile
        )
    return form_fields


# ── Natural language search query parser ──────────────────────────────────────

def parse_search_query(text: str) -> Dict[str, Any]:
    """
    Parse a natural language job search query into structured filters.

    Input:  "senior data engineer jobs in Bengaluru posted last 24 hours"
    Output: {
        "keywords":  "senior data engineer",
        "location":  "Bengaluru",
        "freshness": "24h",    # "24h" | "3d" | "7d" | "30d" | "any"
        "job_type":  "",       # "full-time" | "part-time" | "contract" | "internship" | ""
        "remote":    false
    }

    Gracefully falls back to treating the full text as keywords if AI is unavailable.
    """
    default = {
        "keywords": text.strip(),
        "location": "",
        "freshness": "any",
        "job_type": "",
        "remote": False,
        "min_experience": 0,
    }

    if not text.strip():
        return default

    # If AI not available, do simple keyword-only fallback
    if not is_ai_ready():
        return default

    try:
        raw = _ask(
            system=(
                "You are a job search query parser. "
                "Extract structured search parameters from natural language and return ONLY valid JSON. "
                "No explanation, no markdown, just the JSON object."
            ),
            prompt=f"""Parse this job search query into structured JSON.

Query: "{text}"

Return a JSON object with exactly these keys:
- "keywords": the job title, role, or skills to search for (string — keep it concise, e.g. "data engineer" not "data engineer jobs")
- "location": city, region, or country mentioned (string — empty "" if not specified)
- "freshness": how recently posted — MUST be one of: "24h", "3d", "7d", "30d", "any"
  - "last 24 hours" / "today" / "yesterday" → "24h"
  - "last 3 days" / "few days" → "3d"
  - "last week" / "this week" → "7d"
  - "last month" / "this month" → "30d"
  - not mentioned → "any"
- "job_type": MUST be one of: "full-time", "part-time", "contract", "internship", "" (empty if not mentioned)
- "remote": true if remote/WFH/work from home is mentioned, otherwise false
- "min_experience": minimum years of experience as an integer (e.g. "6 years exp" → 6, "5+ years" → 5, "senior" alone → 5, "junior" → 1, not mentioned → 0)

Example input: "senior react developer in mumbai, last week, full time, 6 years experience"
Example output: {{"keywords": "senior react developer", "location": "mumbai", "freshness": "7d", "job_type": "full-time", "remote": false, "min_experience": 6}}

Return ONLY the JSON object.""",
            max_tokens=200,
        )
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            parsed = json.loads(m.group())
            # Merge with defaults so all keys are always present
            return {**default, **parsed}
    except Exception:
        pass

    return default
