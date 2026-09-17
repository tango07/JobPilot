"""
Naukri.com scraper — search jobs and apply using saved profile.
Updated for 2025-2026 DOM.
"""

import re
from datetime import datetime, timedelta
from typing import List, Dict
from .base import BaseScraper, human_delay, human_type
from urllib.parse import quote_plus, urlencode


class NaukriScraper(BaseScraper):
    site_name = "naukri"
    base_url = "https://www.naukri.com"
    login_url = "https://www.naukri.com/nlogin/login"

    async def _is_logged_in(self, page) -> bool:
        url = page.url
        if any(p in url for p in ["/mnjuser/", "/nlogin/home", "/jobs/"]):
            return True
        return await page.query_selector(
            ".nI-gNb-sb__icon-wrapper, .user-name, .nI-gNb-drawer__icon, "
            "[class*='userDropdown'], [class*='user-info']"
        ) is not None

    def _sso_google_selectors(self) -> list:
        return [
            ".google-login",
            "[class*='googleLogin']",
            "[class*='google-btn']",
            "button[title*='Google']",
            ".social-login button",
        ]

    async def _do_login(self, username: str, password: str) -> bool:
        page = await self._get_page()
        await page.goto(self.login_url, wait_until="domcontentloaded")
        await human_delay(1500, 2500)

        if await page.query_selector(".nI-gNb-lgn-lnk") is None:
            return True  # Already logged in

        try:
            login_link = await page.query_selector("[data-ga-track='Login_header'], .login-btn")
            if login_link:
                await login_link.click()
                await human_delay(800, 1200)

            await human_type(page, "input#usernameField", username)
            await human_delay(300, 600)
            await human_type(page, "input#passwordField", password)
            await human_delay(300, 600)
            await page.click("button[type='submit'], .loginButton")
            await page.wait_for_load_state("networkidle", timeout=15000)
            await human_delay(1500, 2500)

            otp_input = await page.query_selector("input[placeholder*='OTP']")
            if otp_input:
                self.log("Naukri requires OTP. Please enter it in the browser window.", "warning")
                await page.wait_for_selector(".nI-gNb-sb__icon-wrapper, .user-profile", timeout=60000)

            return await page.query_selector(".nI-gNb-sb__icon-wrapper, .user-name") is not None
        except Exception as e:
            self.log(f"Naukri login error: {e}", "error")
            return False

    async def _do_search(self, keywords: str, location: str, filters: Dict) -> List[Dict]:
        page = await self._get_page()
        jobs = []
        _limit = int(filters.get('results_limit', 25) or 25)

        from urllib.parse import quote_plus as _qp
        kw_slug = keywords.replace(" ", "-").lower()
        loc_slug = location.replace(" ", "-").lower() if location else ""
        # seo_key is used for the manual-API fallback (no experience in path there)
        seo_key = f"{kw_slug}-jobs{'-in-' + loc_slug if loc_slug else ''}"

        _freshness_to_age = {'24h': '1', '3d': '3', '7d': '7', '30d': '30'}
        _job_age = _freshness_to_age.get(filters.get('freshness', ''), '')
        _min_exp = int(filters.get('min_experience', 0) or 0)
        _exp_lo = max(0, _min_exp - 2) if _min_exp > 0 else 0
        _exp_hi = _min_exp + 3 if _min_exp > 0 else 0

        # Build SEO URL.  Experience goes in the PATH (Naukri's canonical format),
        # not as a ?experience= query param which Naukri silently ignores.
        if _min_exp > 0:
            exp_path = f"-{_exp_lo}-to-{_exp_hi}-years-experience"
            nav_seo_key = f"{kw_slug}{exp_path}-jobs{'-in-' + loc_slug if loc_slug else ''}"
            self.log(f"Naukri: applying experience filter {_exp_lo}-{_exp_hi} yrs (path-based)", "info")
        else:
            nav_seo_key = seo_key

        seo_url = f"https://www.naukri.com/{nav_seo_key}?sort=1"
        if _job_age:
            seo_url += f"&jobAge={_job_age}"
            self.log(f"Naukri: applying freshness filter jobAge={_job_age}", "info")

        # ── Strategy 1: Intercept the browser's own API response ─────────────
        # When the page loads, Naukri's JS makes a jobapi call with all correct
        # headers/cookies automatically. We just need to capture that response.
        captured_data = []

        async def _on_response(response):
            try:
                url = response.url
                if "jobapi" in url and response.status == 200:
                    body = await response.json()
                    if isinstance(body, dict) and "jobDetails" in body:
                        captured_data.append(body)
                        count = len(body.get("jobDetails") or [])
                        self.log(f"Naukri: captured API response with {count} job(s)", "info" if count else "warning")
            except Exception:
                pass

        page.on("response", _on_response)
        try:
            self.log(f"Naukri navigating: {seo_url}", "info")
            await page.goto(seo_url, wait_until="domcontentloaded", timeout=25000)
            await human_delay(3000, 5000)  # Wait for async API calls to complete
            self.log(f"Naukri page: {page.url[:150]}", "info")

            # Slider fallback: if experience was requested but no data yet, try the UI slider.
            # (Path-based URL should handle it, but keep this as a safety net.)
            if _min_exp > 0 and not captured_data:
                self.log(f"Naukri: path URL didn't capture data — trying experience slider for {_min_exp}+ yrs", "info")
                try:
                    # Scroll down a bit so the experience filter section is in viewport
                    await page.evaluate("window.scrollTo(0, 500)")
                    await human_delay(600, 900)

                    # Strategy A: find hidden range input anywhere on page related to experience
                    exp_set = await page.evaluate(f"""() => {{
                        // All range inputs on the page
                        const ranges = [...document.querySelectorAll('input[type="range"]')];
                        for (const r of ranges) {{
                            const section = r.closest(
                                '[class*="experiencecontainer"], [class*="Experience"], '
                                + '[class*="exp-container"], [class*="expContainer"]'
                            );
                            if (section) {{
                                r.value = '{_min_exp}';
                                r.dispatchEvent(new Event('input', {{bubbles: true}}));
                                r.dispatchEvent(new Event('change', {{bubbles: true}}));
                                return 'range:' + r.value;
                            }}
                        }}
                        return null;
                    }}""")
                    if exp_set:
                        self.log(f"Naukri: experience range input → {exp_set}", "info")
                        await human_delay(2000, 3000)
                    else:
                        # Strategy B: click the exp-container div at proportional position
                        # Try several selector variants to find the slider track
                        slider = None
                        for sel in [
                            '.exp-container',
                            '[class*="expContainer"]',
                            '[class*="experiencecontainer"] [class*="slider"]',
                            '[class*="experiencecontainer"] [class*="Slider"]',
                            '[class*="Experience"] [class*="slider"]',
                        ]:
                            slider = await page.query_selector(sel)
                            if slider and await slider.is_visible():
                                break
                            slider = None
                        if slider:
                            box = await slider.bounding_box()
                            if box and box['width'] > 0:
                                x_ratio = min(_min_exp / 30.0, 0.95)
                                await page.mouse.click(
                                    box['x'] + box['width'] * x_ratio,
                                    box['y'] + box['height'] * 0.4,
                                )
                                self.log(f"Naukri: clicked slider at {x_ratio:.0%} for {_min_exp}+ yrs", "info")
                                await human_delay(2500, 3500)
                        else:
                            # Log all class names containing "exp" for debugging
                            exp_classes = await page.evaluate("""() => {
                                return [...document.querySelectorAll('[class*="exp"], [class*="Exp"]')]
                                    .map(e => e.className).filter(Boolean).slice(0, 10);
                            }""")
                            self.log(f"Naukri: slider not found; exp-related elements: {exp_classes[:5]}", "warning")
                except Exception as slider_err:
                    self.log(f"Naukri: slider interaction error: {slider_err}", "warning")

        except Exception as nav_err:
            self.log(f"Naukri navigation error: {nav_err}", "warning")
        finally:
            page.remove_listener("response", _on_response)

        if captured_data:
            api_data = captured_data[0]
            job_list = api_data.get("jobDetails") or []
            now = datetime.utcnow()
            for j in job_list[:_limit]:
                try:
                    title   = (j.get("title") or j.get("jobTitle") or "").strip()
                    company = (j.get("companyName") or j.get("company") or "").strip()
                    ph = j.get("placeholders") or []
                    loc_text = ph[0].get("label", "") if ph else str(j.get("location") or "")
                    salary   = str(j.get("salary") or "").strip()
                    job_url  = j.get("jdURL") or j.get("jobUrl") or j.get("url") or ""
                    if job_url and not job_url.startswith("http"):
                        job_url = "https://www.naukri.com" + job_url
                    jid = str(j.get("jobId") or j.get("id") or title[:20])
                    date_posted = ""
                    ts = j.get("createdDate") or j.get("ambitionBoxData", {}).get("createdDate")
                    if isinstance(ts, (int, float)) and ts > 1_000_000_000:
                        date_posted = datetime.utcfromtimestamp(ts / 1000).strftime('%Y-%m-%dT%H:%M:%S')
                    if not title:
                        continue
                    jobs.append(self._make_job(
                        job_id=jid, title=title, company=company,
                        location=str(loc_text)[:80], salary=salary,
                        url=job_url, easy_apply=True, date_posted=date_posted,
                    ))
                except Exception as je:
                    self.log(f"Naukri parse error: {je}", "warning")
            if jobs:
                self.log(f"Naukri: extracted {len(jobs)} job(s) via response capture", "success")
            else:
                self.log("Naukri: API returned 0 jobs for these filters (filters may be too specific)", "warning")
            return jobs

        self.log("Naukri: no API response captured — falling back to DOM extraction", "warning")

        # ── Fallback: manual API call with Referer header ─────────────────────
        import json as _json
        kw_enc = _qp(keywords)
        loc_enc = _qp(location) if location else ""
        api_url = (
            f"https://www.naukri.com/jobapi/v3/search"
            f"?noOfResults={_limit}&urlType=search_by_key_loc&searchType=adv"
            f"&keyword={kw_enc}&location={loc_enc}"
            f"&pageNo=1&seoKey={seo_key}&src=jobsearchDesk&latLong="
        )
        if _job_age:
            api_url += f"&jobAge={_job_age}"
        if _min_exp > 0:
            _exp_lo2 = max(0, _min_exp - 2)
            _exp_hi2 = _min_exp + 3
            api_url += f"&experience={_exp_lo2}%2C{_exp_hi2}"
        self.log(f"Naukri manual API: {api_url[:120]}", "info")

        # Navigate to naukri.com first so the fetch has the right origin + cookies
        try:
            await page.goto(f"https://www.naukri.com/{seo_key}", wait_until="domcontentloaded", timeout=25000)
            await human_delay(2000, 3500)
            self.log(f"Naukri page (fallback nav): {page.url[:150]}", "info")
        except Exception as nav_err:
            self.log(f"Naukri navigation error: {nav_err}", "warning")

        api_data = None
        try:
            result = await page.evaluate(f"""async () => {{
                const r = await fetch({_json.dumps(api_url)}, {{
                    method: 'GET',
                    headers: {{
                        'appid': '109',
                        'systemid': 'Naukri',
                        'Accept': 'application/json, text/plain, */*',
                        'X-Requested-With': 'XMLHttpRequest',
                        'Referer': window.location.href,
                        'Origin': 'https://www.naukri.com',
                    }},
                    credentials: 'include',
                }});
                if (!r.ok) return {{error: r.status}};
                return r.json();
            }}""")
            if isinstance(result, dict) and not result.get("error"):
                api_data = result
                self.log(f"Naukri manual API: {len((api_data.get('jobDetails') or []))} job(s)", "info")
            else:
                self.log(f"Naukri manual API error: {result}", "warning")
        except Exception as e:
            self.log(f"Naukri manual API error: {e}", "warning")

        if api_data:
            job_list = api_data.get("jobDetails") or []
            now = datetime.utcnow()
            for j in job_list[:_limit]:
                try:
                    title   = j.get("title", "").strip()
                    company = j.get("companyName", "").strip()
                    loc_text= ", ".join(j.get("placeholders", [{}])[0].get("label", "").split(",")[:2]).strip() if j.get("placeholders") else ""
                    salary  = j.get("salary", "").strip() if j.get("salary") else ""
                    job_url = j.get("jdURL", "") or j.get("jobUrl", "")
                    if not job_url.startswith("http"):
                        job_url = "https://www.naukri.com" + job_url
                    jid     = str(j.get("jobId", "") or j.get("joId", "") or title[:20])

                    # Date posted — Naukri API returns createdDate as ms timestamp
                    date_posted = ""
                    ts = j.get("createdDate") or j.get("footerPlaceholderLabel")
                    if isinstance(ts, (int, float)) and ts > 1_000_000_000:
                        date_posted = datetime.utcfromtimestamp(ts / 1000).strftime('%Y-%m-%dT%H:%M:%S')
                    elif isinstance(ts, str):
                        m = re.search(r'(\d+)\s+(day|week|month|hour)s?\s+ago', ts, re.IGNORECASE)
                        if m:
                            n, unit = int(m.group(1)), m.group(2).lower()
                            delta = {'hour': timedelta(hours=n), 'day': timedelta(days=n),
                                     'week': timedelta(weeks=n), 'month': timedelta(days=n*30)}.get(unit)
                            if delta:
                                date_posted = (now - delta).strftime('%Y-%m-%dT%H:%M:%S')

                    if not title:
                        continue
                    jobs.append(self._make_job(
                        job_id=jid, title=title, company=company,
                        location=loc_text, salary=salary, url=job_url,
                        easy_apply=True, date_posted=date_posted,
                    ))
                except Exception as je:
                    self.log(f"Naukri API parse error: {je}", "warning")
            self.log(f"Naukri: extracted {len(jobs)} job(s) via API", "success" if jobs else "warning")
            return jobs

        # ── Fallback 1: Extract from Next.js __NEXT_DATA__ ────────────────────
        self.log("Naukri API failed — trying __NEXT_DATA__ extraction", "warning")
        try:
            next_data = await page.evaluate("""() => {
                const el = document.getElementById('__NEXT_DATA__');
                if (el) { try { return JSON.parse(el.textContent); } catch(e) {} }
                return null;
            }""")
            if next_data and isinstance(next_data, dict):
                self.log(f"Naukri __NEXT_DATA__ keys: {list(next_data.get('props', {}).get('pageProps', {}).keys())[:10]}", "info")
                # Walk into props.pageProps to find job list
                pp = next_data.get("props", {}).get("pageProps", {})
                raw_jobs = (pp.get("jobDetails") or pp.get("jobList") or
                            pp.get("jobs") or pp.get("searchResult", {}).get("jobDetails") or [])
                if not raw_jobs:
                    # Try one level deeper
                    for v in pp.values():
                        if isinstance(v, dict):
                            for k2 in ("jobDetails", "jobList", "jobs"):
                                if isinstance(v.get(k2), list) and len(v[k2]) > 0:
                                    raw_jobs = v[k2]; break
                        if raw_jobs:
                            break
                self.log(f"Naukri __NEXT_DATA__: {len(raw_jobs)} raw job(s)", "info")
                now_dt = datetime.utcnow()
                for j in raw_jobs[:_limit]:
                    try:
                        title   = (j.get("title") or j.get("jobTitle") or "").strip()
                        company = (j.get("companyName") or j.get("company") or "").strip()
                        ph = j.get("placeholders") or []
                        loc_text = ph[0].get("label", "") if ph else str(j.get("location") or "")
                        salary  = str(j.get("salary") or j.get("ctc") or "").strip()
                        job_url = j.get("jdURL") or j.get("jobUrl") or j.get("url") or ""
                        if job_url and not job_url.startswith("http"):
                            job_url = "https://www.naukri.com" + job_url
                        jid = str(j.get("jobId") or j.get("id") or title[:20])
                        date_posted = ""
                        ts = j.get("createdDate") or j.get("modifiedDate")
                        if isinstance(ts, (int, float)) and ts > 1_000_000_000:
                            date_posted = datetime.utcfromtimestamp(ts/1000).strftime('%Y-%m-%dT%H:%M:%S')
                        if title:
                            jobs.append(self._make_job(
                                job_id=jid, title=title, company=company,
                                location=str(loc_text)[:80], salary=salary,
                                url=job_url, easy_apply=True, date_posted=date_posted,
                            ))
                    except Exception:
                        pass
                if jobs:
                    self.log(f"Naukri: extracted {len(jobs)} job(s) via __NEXT_DATA__", "success")
                    return jobs
        except Exception as nd_err:
            self.log(f"Naukri __NEXT_DATA__ error: {nd_err}", "warning")

        # ── Fallback 2: Walk up from bg-jobNotes banners (each is inside a job card) ──
        # Scroll page fully so cards render and offsetHeight becomes non-zero
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await human_delay(1200, 2000)
            await page.evaluate("window.scrollTo(0, 0)")
            await human_delay(500, 800)
        except Exception:
            pass
        self.log("Naukri: trying bg-jobNotes parent extraction", "warning")
        try:
            card_data = await page.evaluate("""() => {
                const TITLE_SEL = '[class*="text-title18M"],[class*="text-title16M"],[class*="jobTitle"],[class*="job-title"],h2,h3';
                const COMP_SEL  = '[class*="text-title16Sb"],[class*="text-title14Sb"],[class*="comp-name"],[class*="companyName"]';
                const seen = new Set();
                const results = [];

                function extractCard(el) {
                    const titleEl = el.querySelector(TITLE_SEL);
                    const title = (titleEl?.innerText || '').trim().split('\\n')[0].replace(/\\s+/g,' ');
                    if (!title || title.length < 3 || ['Quick apply','Apply'].includes(title)) return null;
                    const compEl = el.querySelector(COMP_SEL);
                    const company = (compEl?.innerText || '').trim().split('\\n')[0].replace(/\\s+/g,' ');
                    const linkEl = el.querySelector('a[href*="naukri.com/job-listings"],a[href*="naukri.com/"][href*="-job-"]');
                    const href = linkEl?.href || '';
                    const text = el.innerText.slice(0, 400).replace(/\\n/g,' ');
                    return {title, company, href, text};
                }

                // Strategy 1: walk up from bg-jobNotes — use offsetHeight, not getBoundingClientRect
                const notes = document.querySelectorAll('[class*="bg-jobNotes"]');
                for (const note of notes) {
                    let el = note.parentElement;
                    for (let i = 0; i < 12 && el && el !== document.body; i++) {
                        if (!seen.has(el) && (el.offsetHeight > 60 || el.querySelector(TITLE_SEL))) {
                            const card = extractCard(el);
                            if (card) { seen.add(el); results.push(card); }
                            break;
                        }
                        el = el.parentElement;
                    }
                }

                // Strategy 2: scan all title elements directly (catches cards without bg-jobNotes)
                const titleEls = document.querySelectorAll(TITLE_SEL);
                for (const te of titleEls) {
                    const t = (te.innerText || '').trim().split('\\n')[0];
                    if (!t || t.length < 3) continue;
                    let card = te;
                    for (let i = 0; i < 8 && card && card !== document.body; i++) {
                        if (!seen.has(card) && card.offsetHeight > 60 && card.querySelector(COMP_SEL)) {
                            const data = extractCard(card);
                            if (data) { seen.add(card); results.push(data); }
                            break;
                        }
                        card = card.parentElement;
                    }
                    if (results.length >= 25) break;
                }
                return results;
            }""")
            self.log(f"Naukri bg-jobNotes walk: {len(card_data)} card(s)", "info")
            if card_data:
                now_dt = datetime.utcnow()
                for j in card_data[:_limit]:
                    try:
                        title = j.get("title", "").strip()
                        href = j.get("href", "")
                        text = j.get("text", "")
                        if not title:
                            continue
                        # Extract company from text (line after title)
                        lines = [l.strip() for l in text.split('  ') if l.strip() and l.strip() != title]
                        company = lines[0] if lines else ""
                        job_id = re.search(r"(\d{6,})", href)
                        jid = job_id.group(1) if job_id else re.sub(r"\W+", "", title[:20])
                        full_url = href if href.startswith("http") else f"https://www.naukri.com{href}"
                        # Date from text
                        date_posted = ""
                        m = re.search(r"(\d+)\s+(hr|hour|day|week|month)s?\s+ago", text, re.IGNORECASE)
                        if m:
                            n, unit = int(m.group(1)), m.group(2).lower()
                            delta = {"hr": timedelta(hours=n), "hour": timedelta(hours=n),
                                     "day": timedelta(days=n), "week": timedelta(weeks=n),
                                     "month": timedelta(days=n*30)}.get(unit)
                            if delta:
                                date_posted = (now_dt - delta).strftime('%Y-%m-%dT%H:%M:%S')
                        jobs.append(self._make_job(
                            job_id=jid, title=title, company=company.strip(),
                            location="", salary="", url=full_url,
                            easy_apply=True, date_posted=date_posted,
                        ))
                    except Exception:
                        pass
                if jobs:
                    self.log(f"Naukri: extracted {len(jobs)} job(s) via DOM walk", "success")
                    return jobs
        except Exception as walk_err:
            self.log(f"Naukri DOM walk error: {walk_err}", "warning")

        # ── Fallback 3: CSS selector scraping ──────────────────────────────────
        self.log("Naukri: trying CSS selector scraping", "warning")
        for _ in range(4):
            await page.evaluate("window.scrollBy(0, 700)")
            await human_delay(600, 1200)

        card_selectors = [
            "article.jobTuple", ".srp-jobtuple-wrapper article",
            ".cust-job-tuple", "[data-job-id]",
            "article[class*='Tuple']", "article[class*='jobTuple']",
            "article", "li[class*='job']", "div[class*='jobTuple']",
        ]
        job_cards = []
        used_sel = None
        for sel in card_selectors:
            try:
                cards = await page.query_selector_all(sel)
                if len(cards) >= 1:
                    job_cards = cards[:_limit]; used_sel = sel; break
            except Exception:
                continue

        self.log(f"Naukri HTML: {len(job_cards)} card(s) found via '{used_sel}'", "info")
        if not job_cards:
            try:
                # Dump ALL classes to find what Naukri's 2026 DOM actually uses
                all_cls = await page.evaluate("""() => {
                    const seen = new Set();
                    document.querySelectorAll('*[class]').forEach(e => {
                        if (typeof e.className === 'string')
                            e.className.split(' ').forEach(c => c && seen.add(c));
                    });
                    return [...seen].join(' ');
                }""")
                # Log classes that look job-related
                import re as _re
                job_cls = [c for c in all_cls.split() if _re.search(r'job|tuple|card|result|listing|srp|jd|vacancy', c, _re.I)]
                self.log(f"Naukri job-like classes: {' '.join(job_cls[:40])}", "warning")
                # Dump first 600 chars of body text
                snippet = (await page.evaluate("document.body.innerText"))[:300].replace('\n', ' ')
                self.log(f"Naukri body snippet: {snippet}", "warning")
                # Try JS-based search for any element with job-like text
                candidates = await page.evaluate("""() => {
                    const els = [...document.querySelectorAll('[class*="job"],[class*="Job"],[class*="tuple"],[class*="Tuple"],[class*="srp"],[class*="card"]')];
                    return els.slice(0,4).map(e=>({tag:e.tagName,cls:e.className.slice(0,60),txt:(e.innerText||'').slice(0,80).replace(/\\n/g,' ')}));
                }""")
                self.log(f"Naukri job-like elements: {candidates}", "warning")
            except Exception:
                pass
            self.log("Naukri: no job cards found — HTML fallback also failed.", "warning")
            return []

        # Debug: show first card text
        try:
            first_text = (await job_cards[0].inner_text()).replace('\n', ' ')[:200]
            self.log(f"Naukri card[0] text: {first_text}", "info")
        except Exception:
            pass

        now = datetime.utcnow()

        for card in job_cards:
            try:
                # Title
                title = ""
                for ts in ["a.title", ".title a", "a[class*='title']", "a[class*='jobTitle']",
                           "h2 a", "h3 a", "[class*='jobTitle']"]:
                    el = await card.query_selector(ts)
                    if el:
                        t = (await el.inner_text()).strip()
                        if t:
                            title = t
                            break

                # Company
                company = ""
                for cs in ["a.comp-name", ".comp-name", "a[class*='comp-name']",
                           "[class*='companyInfo'] a", "[class*='company'] a", ".subTitle a"]:
                    el = await card.query_selector(cs)
                    if el:
                        c = (await el.inner_text()).strip()
                        if c:
                            company = c
                            break

                # Location
                loc_text = ""
                for ls in [".locWdth", ".location span", ".loc-name",
                           "[class*='location']", ".ellipsis span"]:
                    el = await card.query_selector(ls)
                    if el:
                        l = (await el.inner_text()).strip()
                        if l:
                            loc_text = l
                            break

                # Salary
                salary = ""
                for ss in [".salary span", ".sal-wrap span", "[class*='salary']"]:
                    el = await card.query_selector(ss)
                    if el:
                        s = (await el.inner_text()).strip()
                        if s:
                            salary = s
                            break

                # Link
                href = ""
                link_el = await card.query_selector("a.title, a[href*='/job-listings'], a[href*='/jobs/']")
                if not link_el:
                    link_el = await card.query_selector("a[href*='naukri.com'], a[href*='/view']")
                if link_el:
                    href = await link_el.get_attribute("href") or ""

                if not title:
                    continue

                # Job ID from href or data attribute
                job_id = ""
                data_id = await card.get_attribute("data-job-id")
                if data_id:
                    job_id = data_id
                elif href:
                    m = re.search(r"(\d{6,})", href)
                    job_id = m.group(1) if m else href.split("/")[-1].split("?")[0]
                if not job_id:
                    job_id = re.sub(r"\W+", "", title[:20])

                full_url = href if href.startswith("http") else f"{self.base_url}{href}"

                # Posted date — Naukri shows "X days ago" text
                date_posted = ""
                for ds in ["[class*='postDate']", "[class*='post-date']", "[class*='date']",
                           "span[title]", ".fleft.grey-text"]:
                    el = await card.query_selector(ds)
                    if el:
                        raw = (await el.inner_text()).strip()
                        if raw:
                            m = re.search(r'(\d+)\s+(day|week|month|hour)s?\s+ago', raw, re.IGNORECASE)
                            if m:
                                n, unit = int(m.group(1)), m.group(2).lower()
                                delta = {'hour': timedelta(hours=n), 'day': timedelta(days=n),
                                         'week': timedelta(weeks=n), 'month': timedelta(days=n*30)}.get(unit)
                                if delta:
                                    date_posted = (now - delta).strftime('%Y-%m-%dT%H:%M:%S')
                            elif "today" in raw.lower() or "just" in raw.lower():
                                date_posted = now.strftime('%Y-%m-%dT%H:%M:%S')
                            if date_posted:
                                break

                # Fallback: parse card text for date
                if not date_posted:
                    try:
                        card_text = await card.inner_text()
                        m = re.search(r'(\d+)\s+(day|week|month|hour)s?\s+ago', card_text, re.IGNORECASE)
                        if m:
                            n, unit = int(m.group(1)), m.group(2).lower()
                            delta = {'hour': timedelta(hours=n), 'day': timedelta(days=n),
                                     'week': timedelta(weeks=n), 'month': timedelta(days=n*30)}.get(unit)
                            if delta:
                                date_posted = (now - delta).strftime('%Y-%m-%dT%H:%M:%S')
                    except Exception:
                        pass

                jobs.append(self._make_job(
                    job_id=job_id,
                    title=title.strip(),
                    company=company.strip(),
                    location=loc_text.strip(),
                    salary=salary.strip(),
                    url=full_url,
                    easy_apply=True,
                    date_posted=date_posted,
                ))
                await human_delay(60, 180)
            except Exception as exc:
                self.log(f"Naukri card parse error: {exc}", "warning")
                continue

        self.log(f"Naukri: extracted {len(jobs)} job(s)", "success" if jobs else "warning")
        return jobs

    async def _do_apply(self, job: Dict, profile: Dict) -> bool:
        page = await self._get_page()
        await page.goto(job["url"], wait_until="domcontentloaded")
        await human_delay(2000, 3000)

        apply_btn = await page.query_selector(
            "button#apply-button, .apply-button, button[id*='apply'], a.apply, "
            "button[class*='apply'], a[class*='apply']"
        )
        if not apply_btn:
            self.log("No apply button found on this Naukri job.", "warning")
            return False

        await apply_btn.click()
        await human_delay(1500, 2500)

        for _ in range(8):
            await human_delay(800, 1500)

            file_input = await page.query_selector("input[type='file']")
            if file_input and profile.get("resume_path"):
                try:
                    await file_input.set_input_files(profile["resume_path"])
                    await human_delay(500, 1000)
                except Exception:
                    pass

            await self.ai_fill_page(page, profile, job)

            proceed_btn = await page.query_selector(
                "button:has-text('Apply'), button:has-text('Proceed'), "
                "button:has-text('Submit'), button:has-text('Send')"
            )
            if proceed_btn:
                text = (await proceed_btn.inner_text()).strip().lower()
                if "apply" in text or "submit" in text:
                    await proceed_btn.click()
                    await human_delay(1500, 2500)
                    success = await page.query_selector(".success-screen, [class*='success'], .applied-badge")
                    return success is not None
                else:
                    await proceed_btn.click()
            else:
                break

        return False
