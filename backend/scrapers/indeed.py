"""
Indeed scraper — search jobs and apply via Indeed Apply.
"""

import re
from typing import List, Dict
from .base import BaseScraper, human_delay, human_type
from urllib.parse import urlencode


class IndeedScraper(BaseScraper):
    site_name = "indeed"
    base_url = "https://in.indeed.com"  # India region
    login_url = "https://secure.indeed.com/account/login"

    async def _is_logged_in(self, page) -> bool:
        url = page.url
        if any(p in url for p in ["/jobs", "/dashboard", "/myjobs", "/account/view"]):
            return True
        return await page.query_selector("[data-testid='nav-user-avatar'], .gnav-LoggedInUser") is not None

    def _sso_google_selectors(self) -> list:
        return [
            "[data-testid='google-login']",
            "[data-tn-element='google-auth-btn']",
            "button[id*='google']",
            ".icl-SocialButton--google",
        ]

    async def _do_login(self, username: str, password: str) -> bool:
        page = await self._get_page()
        await page.goto(self.login_url, wait_until="domcontentloaded")
        await human_delay(1500, 2500)

        # Check if already signed in
        if await page.query_selector("[data-gnav-element-name='SignIn']") is None:
            return True

        try:
            email_input = await page.query_selector("input[type='email'], input[name='__email']")
            if email_input:
                await human_type(page, "input[type='email'], input[name='__email']", username)
                await human_delay(400, 800)

            continue_btn = await page.query_selector("button[type='submit'], #login-submit-button")
            if continue_btn:
                await continue_btn.click()
                await human_delay(1000, 2000)

            password_input = await page.query_selector("input[type='password']")
            if password_input:
                await human_type(page, "input[type='password']", password)
                await human_delay(400, 800)
                await page.keyboard.press("Enter")
                await page.wait_for_load_state("networkidle", timeout=15000)
                await human_delay(1500, 2500)

            # Check for verification
            if "challenge" in page.url or "captcha" in page.url:
                self.log("Indeed requires verification. Please complete it in the browser.", "warning")
                await page.wait_for_url("**/jobs**", timeout=90000)

            return "jobs" in page.url or "dashboard" in page.url or await page.query_selector("[data-testid='nav-user-avatar']") is not None
        except Exception as e:
            self.log(f"Indeed login error: {e}", "error")
            return False

    async def _do_search(self, keywords: str, location: str, filters: Dict) -> List[Dict]:
        page = await self._get_page()
        jobs = []

        params = {"q": keywords, "l": location}
        if filters.get("job_type"):
            type_map = {"full-time": "fulltime", "part-time": "parttime", "contract": "contract", "internship": "internship"}
            jt = type_map.get(filters["job_type"].lower(), "")
            if jt:
                params["jt"] = jt

        url = f"{self.base_url}/jobs?{urlencode(params)}"
        await page.goto(url, wait_until="domcontentloaded")
        await human_delay(2000, 3500)

        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 800)")
            await human_delay(600, 1200)

        job_cards = await page.query_selector_all(".job_seen_beacon, .tapItem, [data-testid='job-card']")

        for card in job_cards[:20]:
            try:
                title_el = await card.query_selector("h2.jobTitle a, [data-testid='jobTitle'] a, .jcs-JobTitle a")
                company_el = await card.query_selector("[data-testid='company-name'], .companyName")
                location_el = await card.query_selector("[data-testid='job-location'], .companyLocation")
                salary_el = await card.query_selector("[data-testid='attribute_snippet_testid'], .salary-snippet")

                title = await title_el.inner_text() if title_el else ""
                company = await company_el.inner_text() if company_el else ""
                location_text = await location_el.inner_text() if location_el else ""
                salary = await salary_el.inner_text() if salary_el else ""
                href = await title_el.get_attribute("href") if title_el else ""

                if not title:
                    continue

                job_id_match = re.search(r"jk=([a-z0-9]+)", href)
                job_id = job_id_match.group(1) if job_id_match else re.sub(r"[^a-z0-9]", "", href[:30])

                full_url = href if href.startswith("http") else f"{self.base_url}{href}"

                # Check for Indeed Apply
                indeed_apply = await card.query_selector("[data-indeed-apply-jobid], .IndeedApplyButton") is not None

                jobs.append(self._make_job(
                    job_id=job_id,
                    title=title.strip(),
                    company=company.strip(),
                    location=location_text.strip(),
                    salary=salary.strip(),
                    url=full_url,
                    easy_apply=indeed_apply,
                ))
            except Exception:
                continue

        return jobs

    async def _do_apply(self, job: Dict, profile: Dict) -> bool:
        page = await self._get_page()
        await page.goto(job["url"], wait_until="domcontentloaded")
        await human_delay(2000, 3000)

        apply_btn = await page.query_selector(
            "button[id*='apply'], .indeed-apply-button, "
            "button[data-indeed-apply], span[id='applyButtonLinkContainer'] button"
        )

        if not apply_btn:
            self.log("No Indeed Apply button found — opening page for manual apply.", "warning")
            return False

        await apply_btn.click()
        await human_delay(1500, 2500)

        # Indeed apply may open a new tab or modal
        new_pages = page.context.pages
        apply_page = new_pages[-1] if len(new_pages) > 1 else page
        self.page = apply_page

        for step in range(8):
            await human_delay(800, 1500)

            # Resume upload if field is present
            file_input = await apply_page.query_selector("input[type='file']")
            if file_input and profile.get("resume_path"):
                try:
                    await file_input.set_input_files(profile["resume_path"])
                    await human_delay(500, 1000)
                except Exception:
                    pass

            # Let Claude fill whatever fields are on this step
            await self.ai_fill_page(apply_page, profile, job)

            submit_btn = await apply_page.query_selector(
                "button:has-text('Submit'), button:has-text('Apply now'), "
                "button[type='submit'][aria-label*='ubmit']"
            )
            next_btn = await apply_page.query_selector(
                "button:has-text('Continue'), button:has-text('Next'), button:has-text('Proceed')"
            )

            if submit_btn:
                await submit_btn.click()
                await human_delay(2000, 3000)
                self.log(f"✓ Submitted Indeed application for {job['title']}", "success")
                return True
            elif next_btn:
                await next_btn.click()
            else:
                break

        return False
