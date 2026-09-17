"""
LinkedIn scraper — search jobs and automate Easy Apply.
"""

import asyncio
import re
from typing import List, Dict
from .base import BaseScraper, human_delay, human_type
from urllib.parse import urlencode, quote_plus


class LinkedInScraper(BaseScraper):
    site_name = "linkedin"
    base_url = "https://www.linkedin.com"
    login_url = "https://www.linkedin.com/login"

    async def _is_logged_in(self, page) -> bool:
        url = page.url
        if any(p in url for p in ["/feed", "/mynetwork", "/jobs", "/in/"]):
            return True
        return await page.query_selector(".global-nav__me-photo, .nav-item__profile-member-photo") is not None

    def _sso_google_selectors(self) -> list:
        return [
            ".btn__google",
            "[data-litms-control-urn*='google']",
            "[data-tracking-control-name*='google']",
            "section.login__social button",
        ]

    async def _do_login(self, username: str, password: str) -> bool:
        page = await self._get_page()
        await page.goto(self.login_url, wait_until="networkidle")
        await human_delay(800, 1500)

        # Check if already logged in
        if "feed" in page.url or "mynetwork" in page.url:
            return True

        try:
            await human_type(page, "#username", username)
            await human_delay(300, 700)
            await human_type(page, "#password", password)
            await human_delay(400, 800)
            await page.click('[data-litms-control-urn="login-submit"]')
            await page.wait_for_load_state("networkidle", timeout=15000)
            await human_delay(1000, 2000)

            # Check for CAPTCHA or verification
            if "checkpoint" in page.url or "challenge" in page.url:
                self.log("LinkedIn requires verification. Please complete it in the browser window.", "warning")
                # Wait up to 60s for user to handle verification
                await page.wait_for_url("**/feed**", timeout=60000)

            return "feed" in page.url or "mynetwork" in page.url
        except Exception as e:
            self.log(f"LinkedIn login error: {e}", "error")
            return False

    async def _do_search(self, keywords: str, location: str, filters: Dict) -> List[Dict]:
        page = await self._get_page()
        jobs = []
        _limit = int(filters.get('results_limit', 25) or 25)

        params = {
            "keywords": keywords,
            "sortBy": "DD",        # Date Descending — most recently posted first
            "f_TPR": "r2592000",   # Posted within the last 30 days
        }
        if location:
            params["location"] = location
        if filters.get("job_type"):
            type_map = {"full-time": "F", "part-time": "P", "contract": "C", "internship": "I"}
            jt = type_map.get(filters["job_type"].lower(), "")
            if jt:
                params["f_JT"] = jt

        # Experience → LinkedIn seniority level (f_E)
        # 1=Internship, 2=Entry, 3=Associate, 4=Mid-Senior, 5=Director, 6=Executive
        _min_exp = int(filters.get("min_experience", 0) or 0)
        if _min_exp > 0:
            if _min_exp <= 1:
                params["f_E"] = "2"       # Entry level
            elif _min_exp <= 4:
                params["f_E"] = "3"       # Associate
            elif _min_exp <= 10:
                params["f_E"] = "4"       # Mid-Senior level
            else:
                params["f_E"] = "5"       # Director
            self.log(f"LinkedIn: experience filter f_E={params['f_E']} for {_min_exp}+ yrs", "info")

        url = f"https://www.linkedin.com/jobs/search/?{urlencode(params)}"
        self.log(f"LinkedIn search URL: {url}", "info")
        await page.goto(url, wait_until="domcontentloaded")
        await human_delay(2500, 4000)

        # Redirect to login? Bail early with a clear message.
        if "login" in page.url or "authwall" in page.url or "checkpoint" in page.url:
            self.log("LinkedIn redirected to login — please connect your account on the Job Sites page.", "error")
            return []

        self.log(f"LinkedIn page loaded: {page.url[:80]}", "info")

        # Scroll to trigger lazy-loading
        for _ in range(4):
            await page.evaluate("window.scrollBy(0, 700)")
            await human_delay(700, 1300)

        # ── Try multiple card selectors (LinkedIn updates DOM frequently) ──────
        card_selectors = [
            "li[data-occludable-job-id]",          # current (2025-2026)
            "[data-job-id]",                        # alternate current
            ".scaffold-layout__list-item",          # scaffold layout
            ".jobs-search-results__list-item",      # older
            ".job-card-container",                  # legacy
            "li.occludable-update",                 # feed-style
        ]
        job_cards = []
        used_sel = None
        for sel in card_selectors:
            try:
                cards = await page.query_selector_all(sel)
                if len(cards) >= 2:
                    job_cards = cards[:_limit]
                    used_sel = sel
                    break
            except Exception:
                continue

        if not job_cards:
            # Last resort: any <li> that contains a /jobs/view/ link
            try:
                job_cards = await page.query_selector_all("li:has(a[href*='/jobs/view/'])")
                job_cards = job_cards[:_limit]
                used_sel = "li:has(a[href*='/jobs/view/'])"
            except Exception:
                pass

        self.log(f"LinkedIn: {len(job_cards)} card(s) found via '{used_sel}'", "info")
        if not job_cards:
            self.log("LinkedIn: no job cards found — page may need login or selectors are outdated.", "warning")
            return []

        # Debug: dump first card's text so we can tune selectors
        try:
            first_text = (await job_cards[0].inner_text()).replace('\n', ' ')[:200]
            self.log(f"LinkedIn card[0] text: {first_text}", "info")
        except Exception:
            pass

        for card in job_cards:
            try:
                # Title — try link text first, then heading elements
                title = ""
                title_selectors = [
                    ".job-card-list__title--link",
                    ".job-card-list__title",
                    ".base-search-card__title",
                    "a[aria-label]",
                    "strong",
                    "h3", "h4",
                ]
                for ts in title_selectors:
                    el = await card.query_selector(ts)
                    if el:
                        t = (await el.inner_text()).strip()
                        if t:
                            title = t
                            break

                # Company
                company = ""
                for cs in [
                    ".job-card-container__company-name",
                    ".artdeco-entity-lockup__subtitle",
                    ".base-search-card__subtitle",
                    "[class*='company-name']",
                    "h4",
                ]:
                    el = await card.query_selector(cs)
                    if el:
                        c = (await el.inner_text()).strip()
                        if c:
                            company = c
                            break

                # Location
                loc_text = ""
                for ls in [
                    ".job-card-container__metadata-item",
                    ".job-search-card__location",
                    "[class*='location']",
                    ".artdeco-entity-lockup__caption",
                ]:
                    el = await card.query_selector(ls)
                    if el:
                        l = (await el.inner_text()).strip()
                        if l:
                            loc_text = l
                            break

                # Link — always look for /jobs/view/ href
                link_el = await card.query_selector("a[href*='/jobs/view/']")
                if not link_el:
                    link_el = await card.query_selector("a[href*='linkedin.com/jobs']")
                href = await link_el.get_attribute("href") if link_el else ""

                if not title and not href:
                    continue

                job_id_match = re.search(r"/jobs/view/(\d+)", href or "")
                job_id = (
                    job_id_match.group(1) if job_id_match
                    else (href or "").split("?")[0].split("/")[-1] or title[:24]
                )

                # Easy Apply detection
                easy_apply = False
                for eas in [
                    ".job-card-container__apply-method",
                    "[class*='easy-apply']",
                    "button:has-text('Easy Apply')",
                    "li-icon[type='linkedin-bug']",
                ]:
                    try:
                        el = await card.query_selector(eas)
                        if el:
                            text = (await el.inner_text()).lower()
                            if "easy apply" in text or text == "":
                                easy_apply = True
                                break
                    except Exception:
                        pass

                full_url = href if (href or "").startswith("http") else f"{self.base_url}{href}"

                # Actual posting date — try <time datetime="..."> first, then parse "X ago" text
                date_posted = ""
                for ts in ["time[datetime]", "time.job-search-card__listdate",
                           "time.job-search-card__listdate--new", "[class*='posted'] time",
                           "time", "[class*='listdate']", "[class*='date']"]:
                    try:
                        tel = await card.query_selector(ts)
                        if tel:
                            dt = await tel.get_attribute("datetime")
                            if dt:
                                date_posted = dt[:19]
                                break
                    except Exception:
                        pass

                # Fallback: parse human text like "1 week ago", "3 days ago", "just now"
                if not date_posted:
                    try:
                        card_text = await card.inner_text()
                        import re as _re
                        from datetime import datetime as _dt, timedelta as _td
                        now = _dt.utcnow()
                        m = _re.search(
                            r'(\d+)\s+(second|minute|hour|day|week|month)s?\s+ago',
                            card_text, _re.IGNORECASE
                        )
                        if m:
                            n, unit = int(m.group(1)), m.group(2).lower()
                            delta = {
                                'second': _td(seconds=n), 'minute': _td(minutes=n),
                                'hour':   _td(hours=n),   'day':    _td(days=n),
                                'week':   _td(weeks=n),   'month':  _td(days=n * 30),
                            }.get(unit)
                            if delta:
                                date_posted = (now - delta).strftime('%Y-%m-%dT%H:%M:%S')
                        elif _re.search(r'just now|moments? ago', card_text, _re.IGNORECASE):
                            date_posted = now.strftime('%Y-%m-%dT%H:%M:%S')
                    except Exception:
                        pass

                jobs.append(self._make_job(
                    job_id=job_id,
                    title=title.strip(),
                    company=company.strip(),
                    location=loc_text.strip(),
                    url=full_url,
                    easy_apply=easy_apply,
                    date_posted=date_posted,
                ))
                await human_delay(80, 200)
            except Exception as exc:
                self.log(f"LinkedIn card parse error: {exc}", "warning")
                continue

        self.log(f"LinkedIn: extracted {len(jobs)} job(s)", "success" if jobs else "warning")
        return jobs

    async def _do_apply(self, job: Dict, profile: Dict) -> bool:
        if not job.get("easy_apply"):
            self.log("This job does not have Easy Apply — opening in browser for manual apply.", "warning")
            page = await self._get_page()
            await page.goto(job["url"])
            return False

        page = await self._get_page()
        await page.goto(job["url"], wait_until="domcontentloaded")
        await human_delay(1500, 2500)

        # Click Easy Apply button
        try:
            apply_btn = await page.wait_for_selector(
                ".jobs-apply-button, button[aria-label*='Easy Apply']",
                timeout=8000
            )
            await apply_btn.click()
            await human_delay(1000, 2000)
        except Exception:
            self.log("Could not find Easy Apply button.", "error")
            return False

        # Handle the multi-step Easy Apply modal
        max_steps = 10
        for step in range(max_steps):
            await human_delay(800, 1500)

            # Upload resume if a file input appears
            resume_input = await page.query_selector("input[type='file']")
            if resume_input and profile.get("resume_path"):
                try:
                    await resume_input.set_input_files(profile["resume_path"])
                    await human_delay(500, 1000)
                except Exception:
                    pass

            # AI fills all text/select/textarea fields on this step
            await self.ai_fill_page(page, profile, job)

            # Handle yes/no radio buttons (AI can't easily interact with these)
            radio_groups = await page.query_selector_all("fieldset")
            for group in radio_groups:
                yes_radio = await group.query_selector("input[value='Yes'], input[value='true']")
                if yes_radio:
                    await yes_radio.check()
                    await human_delay(100, 300)

            # Check if there's a "Next" or "Review" or "Submit" button
            next_btn = await page.query_selector("button[aria-label='Continue to next step']")
            review_btn = await page.query_selector("button[aria-label='Review your application']")
            submit_btn = await page.query_selector("button[aria-label='Submit application']")

            if submit_btn:
                await submit_btn.click()
                await human_delay(1500, 2500)
                self.log(f"✓ Submitted Easy Apply for {job['title']}", "success")
                # Close the modal
                close_btn = await page.query_selector("button[aria-label='Dismiss']")
                if close_btn:
                    await close_btn.click()
                return True
            elif review_btn:
                await review_btn.click()
            elif next_btn:
                await next_btn.click()
            else:
                # No known button found — likely already done or stuck
                break

        self.log("Easy Apply: reached end of steps without finding Submit button.", "warning")
        return False
