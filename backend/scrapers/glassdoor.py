"""
Glassdoor scraper — search jobs and handle apply (often external redirect).
"""

import re
from typing import List, Dict
from .base import BaseScraper, human_delay, human_type
from urllib.parse import urlencode


class GlassdoorScraper(BaseScraper):
    site_name = "glassdoor"
    base_url = "https://www.glassdoor.co.in"
    login_url = "https://www.glassdoor.co.in/profile/login_input.htm"

    async def _is_logged_in(self, page) -> bool:
        return await page.query_selector(".avatar-circle, [data-test='user-avatar'], .email-circle") is not None

    def _sso_google_selectors(self) -> list:
        return [
            "[data-test='google-oauth-btn']",
            "button[data-provider='google']",
            "[class*='googleButton']",
            "[class*='GoogleButton']",
            ".google-oauth-login",
        ]

    async def _do_login(self, username: str, password: str) -> bool:
        page = await self._get_page()
        await page.goto(self.login_url, wait_until="domcontentloaded")
        await human_delay(1500, 2500)

        # Check already logged in
        if await page.query_selector(".avatar-circle, [data-test='user-avatar']"):
            return True

        try:
            await human_type(page, "input[name='username'], input[type='email']", username)
            await human_delay(400, 800)
            continue_btn = await page.query_selector("button[type='submit'], [data-test='email-form-btn']")
            if continue_btn:
                await continue_btn.click()
                await human_delay(800, 1500)

            await human_type(page, "input[type='password'], input[name='password']", password)
            await human_delay(400, 800)
            await page.keyboard.press("Enter")
            await page.wait_for_load_state("networkidle", timeout=15000)
            await human_delay(1500, 2500)

            if "captcha" in page.url or "challenge" in page.url:
                self.log("Glassdoor requires verification. Please complete it in the browser.", "warning")
                await page.wait_for_selector(".avatar-circle, [data-test='user-avatar']", timeout=90000)

            return await page.query_selector(".avatar-circle, [data-test='user-avatar']") is not None
        except Exception as e:
            self.log(f"Glassdoor login error: {e}", "error")
            return False

    def _is_blocked(self, page_text: str) -> bool:
        """Detect Cloudflare / bot-protection walls."""
        signals = [
            "humans only",
            "ray id:",
            "cloudflare",
            "just a moment",
            "enable javascript and cookies",
            "please stand by",
            "checking your browser",
            "security check",
        ]
        lowered = page_text.lower()
        return any(s in lowered for s in signals)

    async def _do_search(self, keywords: str, location: str, filters: Dict) -> List[Dict]:
        page = await self._get_page()
        jobs = []

        params = {"sc.keyword": keywords, "locT": "N", "locId": "1"}
        url = f"{self.base_url}/Job/jobs.htm?{urlencode(params)}"

        await page.goto(url, wait_until="domcontentloaded")
        await human_delay(2500, 4000)

        # ── Bot-detection check ──────────────────────────────────────────────
        body_text = await page.evaluate("document.body.innerText")
        if self._is_blocked(body_text):
            self.log(
                "Glassdoor blocked by Cloudflare bot protection. "
                "You can open the browser, solve the challenge manually, "
                "then retry — your session will be saved.",
                "warning",
            )
            return []
        # ─────────────────────────────────────────────────────────────────────

        # Handle cookie consent
        accept_btn = await page.query_selector("button[id*='accept'], button:has-text('Accept')")
        if accept_btn:
            await accept_btn.click()
            await human_delay(500, 1000)

        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 800)")
            await human_delay(600, 1200)

        job_cards = await page.query_selector_all(
            "[data-test='job-link'], .react-job-listing, li.jl, .JobsList_jobListItem__JBBUV"
        )

        for card in job_cards[:20]:
            try:
                title_el = await card.query_selector(
                    "[data-test='job-title'], .job-title, .JobCard_jobTitle__GLyJ1, a[class*='jobTitle']"
                )
                company_el = await card.query_selector(
                    ".JobCard_employerName__Xemkv, .employer-name, [data-test='employer-short-name']"
                )
                location_el = await card.query_selector(".JobCard_location__N_iYE, .loc, [data-test='job-location']")
                salary_el = await card.query_selector(".JobCard_salaryEstimate__arV5J, .salary-estimate")

                title = await title_el.inner_text() if title_el else ""
                company = await company_el.inner_text() if company_el else ""
                location_text = await location_el.inner_text() if location_el else ""
                salary = await salary_el.inner_text() if salary_el else ""

                href = await title_el.get_attribute("href") if title_el else ""
                job_id = re.sub(r"[^a-zA-Z0-9]", "", href.split("?")[0][-20:]) if href else ""

                if not title:
                    continue

                full_url = href if href.startswith("http") else f"{self.base_url}{href}"

                jobs.append(self._make_job(
                    job_id=job_id,
                    title=title.strip(),
                    company=company.strip(),
                    location=location_text.strip(),
                    salary=salary.strip(),
                    url=full_url,
                    easy_apply=False,  # Glassdoor usually redirects externally
                ))
            except Exception:
                continue

        return jobs

    async def _do_apply(self, job: Dict, profile: Dict) -> bool:
        page = await self._get_page()
        await page.goto(job["url"], wait_until="domcontentloaded")
        await human_delay(2000, 3000)

        # Glassdoor usually opens an external link
        apply_btn = await page.query_selector(
            "button[data-test='applyButton'], a[data-test='applyButton'], "
            "button.apply-btn, [class*='applyButton']"
        )
        if apply_btn:
            self.log("Glassdoor opening external apply page — you may need to complete manually.", "warning")
            await apply_btn.click()
            await human_delay(2000, 3000)
            return False  # External applications can't be auto-filled reliably
        return False
