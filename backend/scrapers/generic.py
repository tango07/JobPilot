"""
Generic scraper — works with any job site using common CSS patterns + AI form filling.
Used for user-added custom job sites where we don't have a dedicated scraper.
"""

import re
from typing import List, Dict, Optional, Callable
from urllib.parse import quote_plus
from .base import BaseScraper, human_delay, human_type


class GenericScraper(BaseScraper):
    """
    Best-effort scraper for arbitrary job sites.
    Uses a configurable search URL template and tries many common
    job card / apply-button CSS selectors found across ATS platforms.
    """

    # Common job card selectors used by Greenhouse, Lever, Workday, Ashby, etc.
    JOB_CARD_SELECTORS = [
        "[data-testid*='job']",
        "[class*='job-card']",
        "[class*='jobCard']",
        "[class*='job_card']",
        "[class*='JobCard']",
        "article[class*='job']",
        ".job-listing",
        ".job-item",
        ".job-result",
        "[class*='JobResult']",
        "[class*='job-result']",
        "[class*='job-posting']",
        "[class*='posting-item']",
        "li[class*='job']",
        ".listing-item",
        "[class*='position-item']",
        "[class*='opening']",
        "[data-job-id]",
        "[data-id][class*='job']",
        "[role='listitem']",
    ]

    TITLE_SELECTORS = [
        "h2 a", "h3 a", "h2", "h3",
        "[class*='title']", "[class*='position']",
        "[class*='job-name']", "[class*='role-name']",
        "a[class*='job']",
    ]

    COMPANY_SELECTORS = [
        "[class*='company']", "[class*='employer']",
        "[class*='org-name']", "[class*='organization']",
    ]

    LOCATION_SELECTORS = [
        "[class*='location']", "[class*='city']",
        "[class*='place']", "[data-testid*='location']",
    ]

    APPLY_SELECTORS = [
        "button:has-text('Easy Apply')",
        "button:has-text('Apply Now')",
        "a:has-text('Apply Now')",
        "button:has-text('Apply')",
        "a:has-text('Apply')",
        "[class*='apply-btn']",
        "[class*='applyBtn']",
        "[id*='apply']",
        "button[class*='apply']",
        "a[href*='apply']",
        "button[data-action*='apply']",
    ]

    def __init__(
        self,
        site_key: str,
        display_name: str,
        base_url: str,
        search_url_template: str,
        log_callback: Optional[Callable] = None,
    ):
        self.site_name = site_key
        self._display_name = display_name
        self.base_url = base_url.rstrip("/")
        self.login_url = base_url
        self.search_url_template = search_url_template
        super().__init__(log_callback)

    # Keywords that indicate a page is an auth/login page
    _AUTH_KEYWORDS = (
        'login', 'signin', 'sign-in', 'sign_in',
        '/auth/', 'register', 'signup', 'sign-up',
        'authenticate', 'oauth', 'sso', 'forgot-password',
    )

    async def _is_logged_in(self, page) -> bool:
        """
        URL-first detection for generic sites:
        - If current URL is on the site's domain AND doesn't contain auth keywords → logged in
        - Fall back to common UI element selectors
        """
        url = page.url.lower()

        # Definitely NOT logged in if still on an auth page
        if any(k in url for k in self._AUTH_KEYWORDS):
            return False

        # Extract base domain for matching
        base_domain = (
            self.base_url
            .replace('https://', '').replace('http://', '')
            .split('/')[0].lower()
        )

        # On the site's domain and past the login page → assume logged in
        if base_domain in url and url not in (
            self.base_url.lower(), self.base_url.lower() + '/'
        ):
            return True

        # Fallback: check common logged-in UI elements
        for sel in [
            ".user-avatar", ".profile-pic", ".profile-photo",
            "[href*='profile']", "[href*='dashboard']", "[href*='settings']",
            ".user-name", ".account-menu", ".user-menu",
            "[aria-label*='profile' i]", "[data-testid*='user-menu']",
            ".nav-user", ".header-user", "button[class*='avatar']",
            "[class*='logged-in']", "[class*='signed-in']",
        ]:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    return True
            except Exception:
                pass
        return False

    async def _do_login(self, username: str, password: str) -> bool:
        """Custom sites use SSO/manual login only — password login not supported."""
        return False

    async def _do_search(self, keywords: str, location: str, filters: Dict) -> List[Dict]:
        page = await self._get_page()

        # Build search URL from template
        url = self.search_url_template
        url = url.replace("{keywords}", quote_plus(keywords))
        url = url.replace("{location}", quote_plus(location or ""))
        # Also handle URL-encoded variants
        url = url.replace("%7Bkeywords%7D", quote_plus(keywords))
        url = url.replace("%7Blocation%7D", quote_plus(location or ""))

        self.log(f"Searching {self._display_name}: {url}", "info")
        await page.goto(url, wait_until="domcontentloaded")
        await human_delay(2000, 3500)

        # Scroll to trigger lazy-loading
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 800)")
            await human_delay(600, 1200)

        # Try each job card selector until we find cards
        job_cards = []
        for sel in self.JOB_CARD_SELECTORS:
            try:
                cards = await page.query_selector_all(sel)
                if len(cards) >= 2:
                    job_cards = cards[:20]
                    self.log(f"Found {len(cards)} cards via selector: {sel}", "info")
                    break
            except Exception:
                continue

        if not job_cards:
            self.log("Could not find job cards with known selectors — site may need a custom scraper.", "warning")
            return []

        jobs = []
        for card in job_cards:
            try:
                title_el = None
                for sel in self.TITLE_SELECTORS:
                    title_el = await card.query_selector(sel)
                    if title_el:
                        break

                company_el = None
                for sel in self.COMPANY_SELECTORS:
                    company_el = await card.query_selector(sel)
                    if company_el:
                        break

                location_el = None
                for sel in self.LOCATION_SELECTORS:
                    location_el = await card.query_selector(sel)
                    if location_el:
                        break

                # Prefer the title element's link, else any link in the card
                link_el = None
                if title_el:
                    link_el = await title_el.query_selector("a") if await title_el.get_property("tagName") != "A" else title_el
                if not link_el:
                    link_el = await card.query_selector("a[href]")

                title = (await title_el.inner_text()).strip() if title_el else ""
                company = (await company_el.inner_text()).strip() if company_el else ""
                loc_text = (await location_el.inner_text()).strip() if location_el else ""
                href = await link_el.get_attribute("href") if link_el else ""

                if not title or len(title) < 3:
                    continue

                # Resolve relative URLs
                if href and not href.startswith("http"):
                    href = f"{self.base_url}/{href.lstrip('/')}"

                job_id = re.sub(r"[^a-zA-Z0-9]", "", (href or title)[-24:])

                jobs.append(self._make_job(
                    job_id=job_id,
                    title=title,
                    company=company,
                    location=loc_text,
                    url=href or url,
                    easy_apply=True,
                ))
            except Exception:
                continue

        return jobs

    async def _do_apply(self, job: Dict, profile: Dict) -> bool:
        page = await self._get_page()
        await page.goto(job["url"], wait_until="domcontentloaded")
        await human_delay(2000, 3000)

        # Find apply button
        apply_btn = None
        for sel in self.APPLY_SELECTORS:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    apply_btn = btn
                    break
            except Exception:
                continue

        if not apply_btn:
            self.log(f"No apply button found on {job['url']}", "warning")
            return False

        await apply_btn.click()
        await human_delay(1500, 2500)

        for _ in range(8):
            await human_delay(800, 1500)

            # Upload resume if a file input appears
            file_input = await page.query_selector("input[type='file']")
            if file_input and profile.get("resume_path"):
                try:
                    await file_input.set_input_files(profile["resume_path"])
                    await human_delay(500, 1000)
                except Exception:
                    pass

            # AI fills all visible fields
            await self.ai_fill_page(page, profile, job)

            # Look for submit / next button
            submit_btn = await page.query_selector(
                "button:has-text('Submit Application'), "
                "button:has-text('Submit'), button:has-text('Apply Now'), "
                "button[type='submit'][class*='apply'], "
                "button[type='submit']:has-text('Apply')"
            )
            next_btn = await page.query_selector(
                "button:has-text('Next'), button:has-text('Continue'), "
                "button:has-text('Next Step')"
            )

            if submit_btn and await submit_btn.is_visible():
                await submit_btn.click()
                await human_delay(1500, 2500)
                return True
            elif next_btn and await next_btn.is_visible():
                await next_btn.click()
            else:
                break

        return False
