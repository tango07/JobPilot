"""
Base scraper class with Playwright browser management.

Uses a PERSISTENT browser context stored in ~/.jobpilot/browser_session/.
This means:
  - First run: browser opens, you log in normally (including Google Sign-In)
  - All future runs: session cookies are reloaded automatically — no re-login needed
  - Bot detection is minimised because the browser profile looks like a real user

Key design: ONE shared Chromium process / user-data-dir for all scrapers.
An asyncio.Lock ensures only one coroutine initialises the context — preventing
the "Opening in existing browser session" crash that happens when multiple tasks
race to launch_persistent_context() with the same user-data-dir.
"""

import asyncio
import random
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Optional, Callable, Any
from playwright.async_api import async_playwright, BrowserContext, Page, Playwright

# Import AI module (sits one level up)
sys.path.insert(0, str(Path(__file__).parent.parent))
import ai as _ai

# Session data is saved here — survives across app restarts
SESSION_DIR = Path.home() / ".jobpilot" / "browser_session"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

# Shared persistent context (one browser profile for all scrapers)
_playwright: Optional[Playwright] = None
_context: Optional[BrowserContext] = None

# Lock prevents concurrent context initialisation (race → "existing browser session" crash)
_context_lock = asyncio.Lock()

# headless=True during automated runs; False for SSO/login so the user sees the browser
_headless: bool = False


async def set_headless_mode(headless: bool):
    """
    Switch between headless (background) and visible (SSO login) mode.
    Closes the current context so the next get_context() call reopens it
    with the new setting. Session cookies are persisted to disk and reloaded.
    """
    global _headless, _playwright, _context
    if _headless == headless:
        return  # nothing to do
    _headless = headless
    async with _context_lock:
        if _context is not None:
            try:
                await _context.close()
            except Exception:
                pass
            _context = None
        if _playwright is not None:
            try:
                await _playwright.stop()
            except Exception:
                pass
            _playwright = None


async def get_context() -> BrowserContext:
    """
    Return the shared persistent browser context, creating it if needed.
    The asyncio.Lock ensures only one coroutine ever calls launch_persistent_context;
    all others wait and then reuse the already-created instance.
    Cookies, localStorage, and session tokens are saved to SESSION_DIR
    and reloaded on every startup — so you only need to log in once.
    """
    global _playwright, _context

    async with _context_lock:
        # Re-check inside the lock in case another coroutine already created it
        if _context is not None:
            try:
                # Quick health check — accessing pages raises if context is closed
                _ = _context.pages
                return _context
            except Exception:
                # Context was closed externally; fall through to recreate
                _context = None
                if _playwright:
                    try:
                        await _playwright.stop()
                    except Exception:
                        pass
                    _playwright = None

        _playwright = await async_playwright().start()
        _context = await _playwright.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=_headless,      # False for SSO login, True for automated runs
            channel="chromium",      # Use the Playwright-managed Chromium build
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="Asia/Kolkata",
            java_script_enabled=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
            ignore_default_args=["--enable-automation"],
            slow_mo=50,              # Slight human-like pacing for all interactions
        )
        # Patch automation-detection fingerprints on every new page
        await _context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    { name: 'Chrome PDF Plugin' },
                    { name: 'Chrome PDF Viewer' },
                    { name: 'Native Client' }
                ]
            });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = {
                runtime: {},
                loadTimes: function(){},
                csi: function(){},
                app: {}
            };
            // Prevent iframe-based detection
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (params) =>
                params.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : originalQuery(params);
        """)
        return _context


async def close_browser():
    global _playwright, _context
    async with _context_lock:
        if _context:
            try:
                await _context.close()   # Saves session to disk automatically
            except Exception:
                pass
            _context = None
        if _playwright:
            try:
                await _playwright.stop()
            except Exception:
                pass
            _playwright = None


# Legacy alias kept for compatibility
async def get_browser():
    ctx = await get_context()
    return None, ctx


async def human_delay(min_ms: int = 500, max_ms: int = 2000):
    """Random human-like delay between actions."""
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


async def human_type(page: Page, selector: str, text: str):
    """Type text with human-like speed."""
    await page.click(selector)
    await page.fill(selector, "")
    for char in text:
        await page.type(selector, char, delay=random.uniform(50, 150))


class BaseScraper(ABC):
    """Abstract base class for all job site scrapers."""

    site_name: str = "unknown"
    base_url: str = ""
    login_url: str = ""

    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None):
        self.log = log_callback or (lambda msg, level="info": None)
        self.page: Optional[Page] = None

    async def _get_page(self) -> Page:
        """
        Get or create a browser page for this scraper.
        Gracefully recreates the context if it has been closed externally.
        """
        try:
            context = await get_context()
            if self.page is None or self.page.is_closed():
                self.page = await context.new_page()
            return self.page
        except Exception:
            # Context was closed; reset and retry once
            global _context, _playwright
            _context = None
            context = await get_context()
            self.page = await context.new_page()
            return self.page

    async def login(self, username: str, password: str) -> bool:
        """Log in to the site using email + password. Returns True on success."""
        self.log(f"Logging into {self.site_name}...", "info")
        try:
            result = await self._do_login(username, password)
            if result:
                self.log(f"✓ Logged into {self.site_name}", "success")
            else:
                self.log(f"✗ Login failed for {self.site_name}", "error")
            return result
        except Exception as e:
            self.log(f"Login error on {self.site_name}: {e}", "error")
            return False

    async def sso_login(self) -> bool:
        """
        Open the site's login page, try to click the Google Sign-In button,
        then wait up to 2 minutes for the user to complete authentication in
        the visible browser window. Session is saved automatically.
        """
        page = await self._get_page()

        self.log(f"Opening {self.site_name} login page…", "info")
        await page.goto(self.login_url, wait_until="domcontentloaded")
        await human_delay(1500, 2500)

        # Already logged in?
        if await self._is_logged_in(page):
            self.log(f"✓ Already logged into {self.site_name}", "success")
            return True

        # Attempt to click Google SSO button (generic + site-specific selectors)
        google_selectors = [
            "[data-provider='google']",
            "[data-auth-provider='google']",
            "button[class*='google' i]",
            "a[class*='google' i]",
            "[data-testid*='google' i]",
            "[aria-label*='Google' i]",
            "button:has-text('Continue with Google')",
            "button:has-text('Sign in with Google')",
            "a:has-text('Continue with Google')",
            "a:has-text('Sign in with Google')",
            ".btn-google",
            "[href*='accounts.google.com']",
        ] + self._sso_google_selectors()

        clicked = False
        for sel in google_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    self.log("Clicked 'Sign in with Google' — please complete the flow in the browser window…", "info")
                    await human_delay(1200, 2200)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            self.log(
                "Could not find Google button automatically. "
                "The login page is open — please sign in manually (Google or email) in the browser window.",
                "warning",
            )

        # Poll every 5 s for up to 2 minutes
        self.log("Waiting for sign-in to complete (up to 2 min)…", "info")
        for tick in range(24):
            await asyncio.sleep(5)
            try:
                if await self._is_logged_in(page):
                    self.log(f"✓ Successfully signed into {self.site_name}!", "success")
                    return True
                elapsed = (tick + 1) * 5
                self.log(f"Still waiting… {elapsed}s elapsed", "info")
            except Exception:
                pass  # Page might be navigating; keep waiting

        self.log("Sign-in timed out after 2 minutes. You can retry from the Job Sites page.", "error")
        return False

    # Override in each subclass to detect logged-in state
    async def _is_logged_in(self, page: Page) -> bool:
        return False

    # Override to add site-specific Google button selectors
    def _sso_google_selectors(self) -> list:
        return []

    async def search_jobs(self, keywords: str, location: str, filters: Dict) -> List[Dict]:
        """Search for jobs and return list of job dicts."""
        self.log(f"Searching {self.site_name}: '{keywords}' in '{location}'...", "info")
        try:
            jobs = await self._do_search(keywords, location, filters)
            self.log(f"✓ Found {len(jobs)} jobs on {self.site_name}", "success")
            return jobs
        except Exception as e:
            self.log(f"Search error on {self.site_name}: {e}", "error")
            return []

    async def apply_to_job(self, job: Dict, profile: Dict) -> bool:
        """Apply to a specific job. Returns True on success."""
        self.log(f"Applying to '{job['title']}' at {job['company']} ({self.site_name})...", "info")
        try:
            result = await self._do_apply(job, profile)
            if result:
                self.log(f"✓ Applied to {job['title']} at {job['company']}", "success")
            else:
                self.log(f"✗ Could not auto-apply to {job['title']} — manual action needed", "warning")
            return result
        except Exception as e:
            self.log(f"Apply error: {e}", "error")
            return False

    @abstractmethod
    async def _do_login(self, username: str, password: str) -> bool:
        pass

    @abstractmethod
    async def _do_search(self, keywords: str, location: str, filters: Dict) -> List[Dict]:
        pass

    @abstractmethod
    async def _do_apply(self, job: Dict, profile: Dict) -> bool:
        pass

    async def ai_fill_page(self, page: Page, profile: Dict, job: Dict) -> None:
        """
        Use Claude to intelligently fill ALL visible text/select/textarea inputs
        on the current page based on the candidate's profile and the job details.

        This is the key AI-powered enhancement: instead of brittle per-site selectors,
        we read whatever fields exist on screen and ask Claude to answer them.
        Works across LinkedIn Easy Apply, Naukri, Indeed, Instahyre, etc.
        """
        try:
            # Extract all unfilled, labelled form fields from the page DOM
            fields_data = await page.evaluate("""() => {
                const fields = [];
                const inputs = document.querySelectorAll(
                    'input:not([type=hidden]):not([type=submit]):not([type=button])' +
                    ':not([type=file]):not([type=checkbox]):not([type=radio]),' +
                    'textarea, select'
                );
                inputs.forEach(el => {
                    if (!el.offsetParent) return; // skip hidden elements
                    const id = el.id || '';
                    // Find label: explicit for=, aria-label, placeholder, name
                    const labelEl = id ? document.querySelector(`label[for="${id}"]`) : null;
                    const label = (
                        labelEl?.innerText ||
                        el.getAttribute('aria-label') ||
                        el.getAttribute('aria-labelledby') &&
                            document.getElementById(el.getAttribute('aria-labelledby'))?.innerText ||
                        el.getAttribute('placeholder') ||
                        el.getAttribute('name') ||
                        ''
                    ).trim();
                    if (!label) return;
                    const currentVal = el.value || '';
                    if (currentVal.length > 2) return; // already filled
                    const type = el.tagName === 'SELECT' ? 'select'
                               : el.tagName === 'TEXTAREA' ? 'textarea'
                               : (el.type || 'text');
                    const options = type === 'select'
                        ? [...el.options].map(o => o.text).filter(t => t.trim())
                        : [];
                    fields.push({ id, label, type, options });
                });
                return fields;
            }""")

            if not fields_data:
                return

            # Ask Claude to generate answers for all fields in one call
            answered = _ai.generate_form_answers(
                fields_data,
                job.get("title", ""),
                job.get("company", ""),
                job.get("description", ""),
                profile,
            )

            # Fill each field
            for field in answered:
                answer = str(field.get("answer", "")).strip()
                if not answer:
                    continue
                el_id = field.get("id", "")
                selector = f"#{el_id}" if el_id else f"[placeholder='{field['label']}']"
                try:
                    if field["type"] == "select":
                        await page.select_option(selector, label=answer)
                    elif field["type"] == "textarea":
                        await page.fill(selector, answer)
                    else:
                        await page.fill(selector, answer)
                    await human_delay(80, 200)
                except Exception:
                    pass

            self.log("AI filled form fields on this page.", "info")
        except Exception as e:
            self.log(f"AI form fill skipped: {e}", "warning")

    def _make_job(self, **kwargs) -> Dict:
        """Helper to create a normalized job dict."""
        return {
            "site": self.site_name,
            "job_id": kwargs.get("job_id", ""),
            "title": kwargs.get("title", ""),
            "company": kwargs.get("company", ""),
            "location": kwargs.get("location", ""),
            "job_type": kwargs.get("job_type", ""),
            "salary": kwargs.get("salary", ""),
            "description": kwargs.get("description", ""),
            "url": kwargs.get("url", ""),
            "apply_url": kwargs.get("apply_url", kwargs.get("url", "")),
            "easy_apply": 1 if kwargs.get("easy_apply", False) else 0,
            "date_posted": kwargs.get("date_posted", ""),
            "status": "new",
        }
