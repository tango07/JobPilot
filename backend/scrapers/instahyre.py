"""
Instahyre scraper — search jobs and apply with profile.
Updated for 2025-2026 DOM.
"""

import re
from datetime import datetime, timedelta
from typing import List, Dict
from .base import BaseScraper, human_delay, human_type
from urllib.parse import urlencode, quote_plus


class InstaHyreScraper(BaseScraper):
    site_name = "instahyre"
    base_url = "https://www.instahyre.com"
    login_url = "https://www.instahyre.com/login/"

    async def _is_logged_in(self, page) -> bool:
        url = page.url
        if any(p in url for p in ["/dashboard", "/candidate", "/profile"]):
            return True
        return await page.query_selector(
            ".user-menu, .profile-avatar, [href*='dashboard'], "
            "[class*='userMenu'], [class*='user-profile']"
        ) is not None

    def _sso_google_selectors(self) -> list:
        return [
            "a[href*='google-oauth']",
            "a[href*='social/login/google']",
            "a[href*='accounts.google.com']",
            ".google-login-btn",
            "[class*='google-login']",
            "button[title*='Google']",
        ]

    async def _do_login(self, username: str, password: str) -> bool:
        page = await self._get_page()
        await page.goto(self.login_url, wait_until="domcontentloaded")
        await human_delay(1500, 2500)

        if await page.query_selector(".user-menu, .profile-avatar, [href='/candidate/dashboard/']"):
            return True

        try:
            await human_type(page, "input[name='email'], input[type='email']", username)
            await human_delay(400, 800)
            await human_type(page, "input[name='password'], input[type='password']", password)
            await human_delay(400, 800)

            submit_btn = await page.query_selector("button[type='submit'], input[type='submit']")
            if submit_btn:
                await submit_btn.click()
            else:
                await page.keyboard.press("Enter")

            await page.wait_for_load_state("networkidle", timeout=15000)
            await human_delay(1500, 2500)

            return (
                await page.query_selector(".user-menu, .profile-avatar, [href*='dashboard']") is not None
                or "dashboard" in page.url
            )
        except Exception as e:
            self.log(f"Instahyre login error: {e}", "error")
            return False

    async def _do_search(self, keywords: str, location: str, filters: Dict) -> List[Dict]:
        page = await self._get_page()
        jobs = []
        _limit = int(filters.get('results_limit', 25) or 25)

        # ── Try Instahyre's internal API first (bypasses AngularJS rendering issues) ──
        import json as _json
        from urllib.parse import quote_plus as _qp

        api_url = (
            f"https://www.instahyre.com/api/v1/opportunity"
            f"?designation={_qp(keywords)}"
            f"{'&city=' + _qp(location) if location else ''}"
            f"&page=1&page_size={_limit}"
        )
        self.log(f"Instahyre API: {api_url[:120]}", "info")

        api_jobs = []
        try:
            # First navigate to the site so we have cookies/session
            await page.goto("https://www.instahyre.com/search-jobs", wait_until="domcontentloaded", timeout=25000)
            await human_delay(2000, 3000)
            if any(p in page.url for p in ["login", "signin", "register"]):
                self.log("Instahyre redirected to login — connect your account on Job Sites page.", "error")
                return []

            result = await page.evaluate(f"""async () => {{
                const r = await fetch({_json.dumps(api_url)}, {{
                    headers: {{'Accept': 'application/json, text/javascript, */*; q=0.01',
                               'X-Requested-With': 'XMLHttpRequest'}},
                    credentials: 'include',
                }});
                if (!r.ok) return {{error: r.status, url: r.url}};
                return r.json();
            }}""")
            self.log(f"Instahyre API response keys: {list(result.keys()) if isinstance(result, dict) else type(result).__name__}", "info")

            if isinstance(result, dict) and not result.get("error"):
                # API may return {results: [...]} or {opportunities: [...]} or a list
                raw = (result.get("results") or result.get("opportunities") or
                       result.get("jobs") or result.get("data") or [])
                if isinstance(result, list):
                    raw = result
                self.log(f"Instahyre API: {len(raw)} raw item(s)", "info")

                now_dt = datetime.utcnow()
                for j in raw[:_limit]:
                    try:
                        title   = (j.get("designation") or j.get("title") or j.get("role") or "").strip()
                        company_obj = j.get("employer") or j.get("company") or {}
                        company = (company_obj.get("name") if isinstance(company_obj, dict) else str(company_obj or "")).strip()
                        loc_raw = j.get("city") or j.get("location") or j.get("cities") or ""
                        if isinstance(loc_raw, list):
                            loc_text = ", ".join(str(x.get("name", x) if isinstance(x, dict) else x) for x in loc_raw[:2])
                        else:
                            loc_text = str(loc_raw).strip()

                        salary  = ""
                        ctc = j.get("ctc_offered") or j.get("salary") or j.get("ctc")
                        if ctc:
                            salary = str(ctc).strip()

                        slug = j.get("slug") or j.get("id") or j.get("pk") or ""
                        job_url = f"https://www.instahyre.com/opportunity/{slug}" if slug else ""
                        jid = str(j.get("id") or j.get("pk") or slug or title[:20])

                        # Date posted
                        date_posted = ""
                        for df in ["created_at", "posted_at", "created", "date_posted"]:
                            raw_dt = j.get(df)
                            if raw_dt:
                                try:
                                    date_posted = raw_dt[:19].replace(" ", "T")
                                    break
                                except Exception:
                                    pass

                        if not title:
                            continue
                        api_jobs.append(self._make_job(
                            job_id=jid, title=title, company=company,
                            location=loc_text, salary=salary, url=job_url,
                            easy_apply=True, date_posted=date_posted,
                        ))
                    except Exception as pe:
                        self.log(f"Instahyre API parse error: {pe}", "warning")

            if api_jobs:
                self.log(f"Instahyre: extracted {len(api_jobs)} job(s) via API", "success")
                return api_jobs
            else:
                self.log("Instahyre API returned 0 jobs — falling back to HTML scraping", "warning")
        except Exception as api_err:
            self.log(f"Instahyre API error: {api_err}", "warning")

        # ── Fallback: HTML scraping with Angular wait ────────────────────────────
        self.log(f"Instahyre page loaded: {page.url[:80]}", "info")
        await human_delay(2000, 3000)

        if keywords:
            search_applied = False

            # Method 1: Use Selectize.js JavaScript API (skills-selectized input)
            try:
                result = await page.evaluate(f"""() => {{
                    const input = document.getElementById('skills');
                    if (input && input.selectize) {{
                        const sel = input.selectize;
                        sel.clear(true);
                        // Try createItem (free-text mode) and addOption
                        try {{ sel.createItem({repr(keywords)}, false); }} catch(e) {{}}
                        try {{ sel.addOption({{value: {repr(keywords)}, text: {repr(keywords)}}}); sel.addItem({repr(keywords)}, true); }} catch(e) {{}}
                        return 'selectize_api';
                    }}
                    return null;
                }}""")
                if result:
                    self.log(f"Instahyre: applied keyword via Selectize API", "info")

                    # ── Apply location: type into location autocomplete and pick first suggestion ──
                    if location:
                        cities = [c.strip() for c in location.split(",") if c.strip()]
                        for city in cities[:2]:
                            try:
                                # After first city Angular may re-render — wait for input to be ready
                                await human_delay(400, 700)
                                # ID confirmed as 'locations-selectized'; fallback to placeholder selectors
                                loc_input = await page.query_selector(
                                    "#locations-selectized, "
                                    "input[placeholder*='ity'], "
                                    "input[placeholder*='ocati']"
                                )
                                if not loc_input:
                                    self.log(f"Instahyre: location input not found for '{city}'", "warning")
                                else:
                                    await loc_input.scroll_into_view_if_needed()
                                    await loc_input.click(force=True)
                                    await human_delay(300, 500)
                                    await loc_input.fill("")
                                    await loc_input.type(city[:6], delay=60)
                                    await human_delay(1500, 2500)  # wait for server autocomplete
                                    drop_opt = await page.query_selector(
                                        ".selectize-dropdown .option:first-child, "
                                        ".selectize-dropdown-content .option"
                                    )
                                    if drop_opt:
                                        opt_text = (await drop_opt.inner_text()).strip()
                                        await drop_opt.click()
                                        self.log(f"Instahyre: selected location '{opt_text}'", "info")
                                        await human_delay(500, 800)
                                    else:
                                        await page.keyboard.press("Escape")
                                        self.log(f"Instahyre: no autocomplete for '{city}' — skipping", "warning")
                            except Exception as loc_err:
                                self.log(f"Instahyre location error: {loc_err}", "warning")

                    # ── Apply experience filter if provided ──────────────────────
                    _min_exp = int(filters.get('min_experience', 0) or 0)
                    if _min_exp > 0:
                        try:
                            _exp_js = f"""() => {{
                                const target = {_min_exp};

                                // Strategy 1: plain text/number input (Instahyre uses input[placeholder='e.g. 4'])
                                const textInputs = [...document.querySelectorAll(
                                    'input[placeholder*="e.g."], input[placeholder*="year"], ' +
                                    'input[placeholder*="exp"], input[type="number"]'
                                )];
                                for (const inp of textInputs) {{
                                    const ph = (inp.placeholder || '').toLowerCase();
                                    const ng = (inp.getAttribute('ng-model') || '').toLowerCase();
                                    if (ph.includes('e.g.') || ph.includes('year') || ph.includes('exp') ||
                                        ng.includes('exp') || ng.includes('year')) {{
                                        inp.value = String(target);
                                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                                        return 'input:' + target;
                                    }}
                                }}

                                // Strategy 2: <select> with numeric options
                                const selects = [...document.querySelectorAll('select')];
                                for (const sel of selects) {{
                                    const opts = [...sel.options].map(o => o.text.toLowerCase());
                                    const hasExp = opts.some(o => o.includes('year') || /\\d/.test(o));
                                    if (!hasExp) continue;
                                    for (let i = 0; i < sel.options.length; i++) {{
                                        const txt = sel.options[i].text;
                                        const nums = txt.match(/\\d+/g);
                                        if (!nums) continue;
                                        const lo = parseInt(nums[0]);
                                        const hi = nums[1] ? parseInt(nums[1]) : lo + 5;
                                        if (target >= lo && target <= hi) {{
                                            sel.value = sel.options[i].value;
                                            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                                            return 'select:' + txt;
                                        }}
                                    }}
                                }}
                                return null;
                            }}"""
                            exp_applied = await page.evaluate(_exp_js)
                            if exp_applied:
                                self.log(f"Instahyre: set experience filter → '{exp_applied}'", "info")
                                await human_delay(500, 800)
                            else:
                                self.log(f"Instahyre: experience input not found on page", "warning")
                        except Exception as exp_err:
                            self.log(f"Instahyre experience filter error: {exp_err}", "warning")

                    # Trigger Angular search by clicking submit / pressing Enter
                    try:
                        btn = await page.query_selector("button[type='submit'], button[ng-click*='search'], .search-btn, button.btn-primary")
                        if btn and await btn.is_visible():
                            await btn.click()
                        else:
                            await page.keyboard.press("Enter")
                    except Exception:
                        pass
                    await human_delay(3000, 5000)
                    # Try to sort by most recent — look for "Latest" / "Freshness" sort option
                    try:
                        sort_applied = await page.evaluate("""() => {
                            // Instahyre may have a sort dropdown or radio buttons
                            const labels = [...document.querySelectorAll('label,button,a,[ng-click]')];
                            for (const el of labels) {
                                const t = (el.innerText || el.textContent || '').trim().toLowerCase();
                                if (t === 'latest' || t === 'freshness' || t === 'newest' || t === 'recent' || t === 'date') {
                                    el.click();
                                    return true;
                                }
                            }
                            return false;
                        }""")
                        if sort_applied:
                            self.log("Instahyre: applied date sort", "info")
                            await human_delay(2000, 3000)
                    except Exception:
                        pass
                    search_applied = True
            except Exception as se:
                self.log(f"Instahyre Selectize API error: {se}", "warning")

            # Method 2: Type directly into the Selectize input and wait for dropdown
            if not search_applied:
                try:
                    skills_input = await page.query_selector("input#skills-selectized")
                    if skills_input and await skills_input.is_visible():
                        await skills_input.click()
                        await human_delay(300, 600)
                        await skills_input.fill(keywords)
                        await human_delay(1500, 2500)  # Wait for autocomplete dropdown
                        # Try to click first dropdown option
                        dropdown_item = await page.query_selector(
                            ".selectize-dropdown-content .option:first-child, "
                            ".selectize-dropdown .option:first-child"
                        )
                        if dropdown_item and await dropdown_item.is_visible():
                            await dropdown_item.click()
                            self.log(f"Instahyre: selected '{keywords}' from Selectize dropdown", "info")
                        else:
                            # No dropdown match — press Tab to create free-text tag
                            await page.keyboard.press("Tab")
                            self.log(f"Instahyre: pressed Tab to create '{keywords}' tag", "info")
                        await human_delay(2000, 3500)
                        # Click search button
                        btn = await page.query_selector("button[type='submit'], button[ng-click*='search'], .search-btn")
                        if btn and await btn.is_visible():
                            await btn.click()
                            await human_delay(3000, 5000)
                        search_applied = True
                except Exception as inp_err:
                    self.log(f"Instahyre input error: {inp_err}", "warning")

            if not search_applied:
                self.log("Instahyre: keyword filter not applied — showing all jobs", "warning")
                await human_delay(2000, 3000)

        # Wait for Angular rendering: poll until card text is non-trivial (> "View »")
        self.log("Instahyre: waiting for Angular rendering...", "info")
        card_selectors = [
            ".opportunity", "div[class*='opportunity']",
            ".jobs .opportunity", ".job-card", "div[ng-repeat]", "li[ng-repeat]",
        ]
        job_cards = []
        used_sel = None

        for attempt in range(8):  # poll up to ~12s
            for sel in card_selectors:
                try:
                    cards = await page.query_selector_all(sel)
                    if len(cards) >= 1:
                        # Check if content is rendered (not just "View »")
                        sample = await cards[0].inner_text()
                        if len(sample.strip()) > 10 and "View" not in sample[:20]:
                            job_cards = cards[:_limit]
                            used_sel = sel
                            break
                except Exception:
                    continue
            if job_cards:
                break
            # Scroll a bit to trigger lazy load, then wait
            await page.evaluate("window.scrollBy(0, 400)")
            await human_delay(1500, 2000)

        # If content still "View »", try getting data from Angular $scope
        if not job_cards or (job_cards and len((await job_cards[0].inner_text()).strip()) <= 10):
            self.log("Instahyre: trying AngularJS $scope extraction...", "info")
            try:
                ng_jobs = await page.evaluate("""() => {
                    const results = [];
                    const cards = document.querySelectorAll('.opportunity, div[ng-repeat], li[ng-repeat]');
                    cards.forEach(el => {
                        try {
                            const sc = angular && angular.element(el).scope();
                            if (sc && sc.opportunity) {
                                const o = sc.opportunity;
                                results.push({
                                    title: o.designation || o.title || '',
                                    company: (o.employer && o.employer.name) || o.company_name || '',
                                    location: (o.cities && o.cities.map(c=>c.name).join(', ')) || o.location || '',
                                    salary: o.ctc_offered || '',
                                    slug: o.slug || o.id || '',
                                    created_at: o.created_at || ''
                                });
                            }
                        } catch(e) {}
                    });
                    return results;
                }""")
                if ng_jobs and len(ng_jobs) > 0:
                    self.log(f"Instahyre: got {len(ng_jobs)} job(s) via Angular $scope", "info")
                    now_dt = datetime.utcnow()
                    for j in ng_jobs:
                        title = j.get("title", "").strip()
                        if not title:
                            continue
                        slug = j.get("slug", "")
                        job_url = f"https://www.instahyre.com/opportunity/{slug}" if slug else ""
                        date_posted = j.get("created_at", "")[:19].replace(" ", "T") if j.get("created_at") else ""
                        jobs.append(self._make_job(
                            job_id=str(slug or title[:20]),
                            title=title, company=j.get("company", "").strip(),
                            location=j.get("location", "").strip(),
                            salary=str(j.get("salary", "") or "").strip(),
                            url=job_url, easy_apply=True, date_posted=date_posted,
                        ))
                    if jobs:
                        self.log(f"Instahyre: extracted {len(jobs)} job(s) via $scope", "success")
                        return jobs
            except Exception as ng_err:
                self.log(f"Instahyre $scope extraction failed: {ng_err}", "warning")

        self.log(f"Instahyre: {len(job_cards)} card(s) found via '{used_sel}'", "info")

        if not job_cards:
            try:
                all_classes = await page.evaluate("""() => {
                    const els = document.querySelectorAll('div[class], article[class], li[class]');
                    const seen = new Set();
                    [...els].slice(0, 80).forEach(e => e.className.split(' ').forEach(c => c && seen.add(c)));
                    return [...seen].join(', ');
                }""")
                self.log(f"Instahyre classes on page: {all_classes[:500]}", "warning")
                first_html = await page.evaluate("document.body.innerHTML.substring(0, 800)")
                self.log(f"Instahyre body HTML start: {first_html[:400]}", "warning")
            except Exception:
                pass
            self.log(f"Instahyre: no job cards found. URL: {page.url[:80]}", "warning")
            return []

        # Debug: dump first card innerHTML to understand structure
        try:
            first_html = await page.evaluate("document.querySelector('.opportunity, div[ng-repeat]').innerHTML")
            self.log(f"Instahyre card[0] innerHTML: {first_html[:400]}", "info")
        except Exception:
            pass

        now = datetime.utcnow()

        for card in job_cards:
            try:
                # Try to extract via innerHTML analysis (for Angular-rendered content)
                card_html = ""
                card_text = ""
                try:
                    card_html = await page.evaluate("(el) => el.innerHTML", card)
                    card_text = await card.inner_text()
                except Exception:
                    pass

                # Title
                title = ""
                for ts in ["h2 a", "h3 a", "h2", "h3", ".job-title a", ".job-title",
                           "[class*='title'] a", "[class*='title']",
                           "[ng-bind*='title']", "[ng-bind*='designation']",
                           "a[class*='job']", ".designation"]:
                    el = await card.query_selector(ts)
                    if el:
                        t = (await el.inner_text()).strip()
                        if t and t.lower() not in ("view", "view »", "»", "apply"):
                            title = t
                            break

                # Company
                company = ""
                for cs in [".company-name", "[class*='company-name']", "[class*='company']",
                           ".org-name", "[class*='org']", "[ng-bind*='company']",
                           "[ng-bind*='employer']", ".employer-name"]:
                    el = await card.query_selector(cs)
                    if el:
                        c = (await el.inner_text()).strip()
                        if c:
                            company = c
                            break

                # Location
                loc_text = ""
                for ls in [".location", "[class*='location']", "[class*='city']",
                           "[ng-bind*='city']", "[ng-bind*='location']"]:
                    el = await card.query_selector(ls)
                    if el:
                        l = (await el.inner_text()).strip()
                        if l:
                            loc_text = l
                            break

                # Salary
                salary = ""
                for ss in [".salary", "[class*='salary']", "[class*='ctc']", "[class*='pay']",
                           "[ng-bind*='ctc']", "[ng-bind*='salary']"]:
                    el = await card.query_selector(ss)
                    if el:
                        s = (await el.inner_text()).strip()
                        if s:
                            salary = s
                            break

                # Link
                href = ""
                for lsel in ["a[href*='/opportunity/']", "a[href*='/job/']",
                             "a[href*='/jobs/']", "a[href*='instahyre']", "a"]:
                    link_el = await card.query_selector(lsel)
                    if link_el:
                        h = await link_el.get_attribute("href") or ""
                        if h and h not in ("#", "/"):
                            href = h
                            break

                if not title:
                    # Last resort: parse card text for a title pattern
                    lines = [l.strip() for l in card_text.split('\n') if len(l.strip()) > 3
                             and l.strip().lower() not in ("view", "view »", "»", "apply", "")]
                    if lines:
                        title = lines[0]

                if not title:
                    continue

                job_id = re.sub(r"[^a-zA-Z0-9]", "", href.split("?")[0][-24:]) if href else re.sub(r"\W+", "", title[:20])
                full_url = href if href.startswith("http") else (f"{self.base_url}{href}" if href else "")

                # Date posted
                date_posted = ""
                m = re.search(r'(\d+)\s+(second|minute|hour|day|week|month)s?\s+ago',
                              card_text, re.IGNORECASE)
                if m:
                    n, unit = int(m.group(1)), m.group(2).lower()
                    delta = {
                        'second': timedelta(seconds=n), 'minute': timedelta(minutes=n),
                        'hour': timedelta(hours=n), 'day': timedelta(days=n),
                        'week': timedelta(weeks=n), 'month': timedelta(days=n*30)
                    }.get(unit)
                    if delta:
                        date_posted = (now - delta).strftime('%Y-%m-%dT%H:%M:%S')
                elif re.search(r'just now|today', card_text, re.IGNORECASE):
                    date_posted = now.strftime('%Y-%m-%dT%H:%M:%S')

                jobs.append(self._make_job(
                    job_id=job_id, title=title.strip(), company=company.strip(),
                    location=loc_text.strip(), salary=salary.strip(),
                    url=full_url, easy_apply=True, date_posted=date_posted,
                ))
                await human_delay(60, 180)
            except Exception as exc:
                self.log(f"Instahyre card parse error: {exc}", "warning")
                continue

        self.log(f"Instahyre: extracted {len(jobs)} job(s)", "success" if jobs else "warning")
        return jobs

    async def _do_apply(self, job: Dict, profile: Dict) -> bool:
        page = await self._get_page()
        await page.goto(job["url"], wait_until="domcontentloaded")
        await human_delay(2000, 3000)

        apply_btn = await page.query_selector(
            "button.apply-btn, a.apply-btn, button:has-text('Apply'), "
            "[class*='apply-button'], button[data-action='apply'], "
            "[class*='ApplyBtn'], [class*='apply-btn']"
        )

        if not apply_btn:
            self.log("No Instahyre apply button found.", "warning")
            return False

        await apply_btn.click()
        await human_delay(1500, 2500)

        for step in range(6):
            await human_delay(800, 1500)

            file_input = await page.query_selector("input[type='file']")
            if file_input and profile.get("resume_path"):
                try:
                    await file_input.set_input_files(profile["resume_path"])
                    await human_delay(500, 1000)
                except Exception:
                    pass

            await self.ai_fill_page(page, profile, job)

            submit_btn = await page.query_selector(
                "button:has-text('Apply'), button:has-text('Submit'), button[type='submit']"
            )
            next_btn = await page.query_selector("button:has-text('Next'), button:has-text('Continue')")

            if submit_btn:
                await submit_btn.click()
                await human_delay(1500, 2500)
                success = await page.query_selector(
                    ".success, [class*='success'], .applied, [class*='applied']"
                )
                return success is not None
            elif next_btn:
                await next_btn.click()
            else:
                break

        return False
