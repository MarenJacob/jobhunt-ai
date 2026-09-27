import base64, json, os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import httpx
from ..config import settings

class SubmissionBlocked(Exception):
    pass

class BrowserAutomation:
    """ATS browser orchestrator.

    Uses an external Playwright worker when BROWSER_WORKER_URL is configured.
    Local Playwright remains available for development. The worker never
    bypasses CAPTCHA/2FA, legal attestations, payment or unknown required data.
    """
    def allowed(self, url: str) -> bool:
        host = urlparse(url).netloc.lower().split(":")[0].replace("www.", "")
        return any(host == d.strip() or host.endswith("." + d.strip()) for d in settings.allowed_domains.split(",") if d.strip())

    def _check_url(self, url: str):
        if not self.allowed(url):
            raise SubmissionBlocked("Domain is not on the configured allowlist")

    async def _remote(self, payload: dict):
        if not settings.browser_worker_url:
            return None
        headers = {"Authorization": f"Bearer {settings.browser_worker_secret}"} if settings.browser_worker_secret else {}
        try:
            async with httpx.AsyncClient(timeout=settings.browser_worker_timeout) as client:
                r = await client.post(settings.browser_worker_url.rstrip("/") + "/execute", json=payload, headers=headers)
            data = r.json() if r.content else {}
            if r.status_code >= 400:
                raise SubmissionBlocked(data.get("detail") or data.get("message") or f"Browser worker returned {r.status_code}")
            return data
        except httpx.HTTPError as e:
            raise SubmissionBlocked(f"Browser worker unavailable: {e}")

    async def inspect_apply_page(self, url: str):
        self._check_url(url)
        remote = await self._remote({"action":"inspect","url":url})
        if remote is not None:
            return remote
        return await self._local(url, {}, "", "", dry_run=True)

    async def submit(self, url: str, profile: dict, resume_path: str = "", resume_bytes: bytes | None = None, resume_filename: str = "resume.pdf", cover_letter: str = "", dry_run: bool = False):
        self._check_url(url)
        resume_b64 = base64.b64encode(resume_bytes).decode("ascii") if resume_bytes else ""
        payload = {
            "action": "submit", "url": url, "profile": profile,
            "cover_letter": cover_letter, "dry_run": dry_run,
            "resume_base64": resume_b64, "resume_filename": resume_filename,
        }
        remote = await self._remote(payload)
        if remote is not None:
            return remote
        return await self._local(url, profile, resume_path, cover_letter, dry_run=dry_run, resume_bytes=resume_bytes, resume_filename=resume_filename)

    async def _local(self, url, profile, resume_path, cover_letter, dry_run=False, resume_bytes=None, resume_filename="resume.pdf"):
        from playwright.async_api import async_playwright
        storage = Path(settings.browser_profile_dir)
        storage.mkdir(parents=True, exist_ok=True)
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(str(storage), headless=settings.browser_headless)
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(1200)
                info = await self._inspect_page(page)
                if info["blocked_signals"]:
                    raise SubmissionBlocked("Human action required: " + ", ".join(info["blocked_signals"]))
                if info.get("login_required"):
                    raise SubmissionBlocked("Login is required. Sign in to the ATS in the authenticated browser session, then retry.")
                mapping = await self._discover_fields(page)
                if dry_run:
                    return {"submitted":False,"dry_run":True,"page":info,"mapping":mapping}
                result = await self._fill(page, mapping, profile, cover_letter, resume_path, resume_bytes, resume_filename)
                if result["unresolved"]:
                    raise SubmissionBlocked("Human input required: " + ", ".join(result["unresolved"][:12]))
                risky = await self._risk_check(page)
                if risky:
                    raise SubmissionBlocked(risky)
                submit = await self._find_submit(page)
                if not submit:
                    raise SubmissionBlocked("No safe application submit button detected")
                await submit.click()
                await page.wait_for_timeout(1500)
                confirmation = await self._confirmation(page)
                return {"submitted":True,"url":page.url,"submitted_at":datetime.utcnow().isoformat(),"mapping":mapping,"confirmation":confirmation}
            finally:
                await context.close()

    async def _inspect_page(self, page):
        body = (await page.locator("body").inner_text())[:30000].lower()
        blocked = [x for x in ("captcha","recaptcha","verify you are human","two-factor","2fa","security code") if x in body]
        login = any(x in body for x in ("sign in to apply","log in to apply","login to apply","sign in to continue"))
        forms = await page.locator("form").count()
        controls = await page.locator("input, textarea, select, [role='combobox'], [contenteditable='true']").count()
        return {"url":page.url,"title":await page.title(),"forms":forms,"inputs":controls,"blocked_signals":blocked,"login_required":login,"ready_for_submission":not blocked and not login}

    async def _discover_fields(self, page):
        selectors = "input, textarea, select, [role='combobox'], [contenteditable='true']"
        loc = page.locator(selectors)
        rows=[]
        for i in range(min(await loc.count(), 250)):
            e=loc.nth(i)
            try:
                rows.append({
                    "index":i,"tag":await e.evaluate("el=>el.tagName.toLowerCase()"),
                    "type":await e.get_attribute("type"),"name":await e.get_attribute("name"),"id":await e.get_attribute("id"),
                    "label":await e.get_attribute("aria-label"),"placeholder":await e.get_attribute("placeholder"),
                    "autocomplete":await e.get_attribute("autocomplete"),"required":await e.get_attribute("required") is not None,
                })
            except Exception: continue
        return rows

    async def _fill(self,page,mapping,profile,cover_letter,resume_path,resume_bytes,resume_filename):
        from .ats import canonical_value
        unresolved=[]; filled=[]
        for field in mapping:
            key=field.get("canonical")
            value=canonical_value(profile,key,cover_letter)
            if not value and key == "resume" and resume_bytes:
                value="__FILE__"
            if not value:
                if field.get("required") and key not in {"work_authorization","sponsorship"}: unresolved.append(field.get("label") or field.get("name") or field.get("id") or f"field-{field.get('index')}")
                continue
            e=page.locator("input, textarea, select, [role='combobox'], [contenteditable='true']").nth(field["index"])
            try:
                typ=(field.get("type") or "").lower()
                if key=="resume" and typ=="file":
                    if resume_bytes:
                        import tempfile
                        suffix=Path(resume_filename).suffix or ".pdf"
                        tmp=Path(tempfile.gettempdir())/f"jobhunt-resume{suffix}"; tmp.write_bytes(resume_bytes)
                        await e.set_input_files(str(tmp))
                    elif resume_path and Path(resume_path).exists(): await e.set_input_files(resume_path)
                    else: unresolved.append(field.get("label") or "Resume")
                elif field.get("tag")=="select":
                    await e.select_option(label=value) if value else None
                elif await e.get_attribute("role")=="combobox":
                    await e.fill(value); await page.wait_for_timeout(300); await e.press("Enter")
                else: await e.fill(value)
                filled.append(field.get("canonical"))
            except Exception:
                if field.get("required"): unresolved.append(field.get("label") or field.get("name") or "required field")
        return {"filled":filled,"unresolved":unresolved}

    async def _risk_check(self,page):
        body=(await page.locator("body").inner_text()).lower()
        risky=("i certify","i attest","legal authorization","application fee","payment required","credit card","work authorization")
        for x in risky:
            if x in body: return "Human review required for legal/work-authorization/payment content"
        return ""

    async def _find_submit(self,page):
        for sel in ["button[type='submit']","input[type='submit']","button:has-text('Submit application')","button:has-text('Submit')","button:has-text('Apply')"]:
            loc=page.locator(sel)
            if await loc.count():
                for i in range(min(await loc.count(),5)):
                    b=loc.nth(i)
                    try:
                        if await b.is_visible() and await b.is_enabled(): return b
                    except Exception: pass
        return None

    async def _confirmation(self,page):
        body=(await page.locator("body").inner_text())[:12000].lower()
        return next((x for x in ("application submitted","application received","thank you for applying","thanks for applying","application complete") if x in body), "page changed after submission")
