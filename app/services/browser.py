import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from ..config import settings

class SubmissionBlocked(Exception):
    pass

class BrowserAutomation:
    """Generic browser worker for allowed application flows.

    It intentionally pauses on CAPTCHA, 2FA, legal attestations, payment and
    unknown required questions instead of bypassing them.
    """
    def allowed(self, url: str) -> bool:
        host = urlparse(url).netloc.lower().replace("www.", "")
        return any(host == d.strip() or host.endswith("." + d.strip()) for d in settings.allowed_domains.split(",") if d.strip())

    def _check_url(self, url: str):
        if not self.allowed(url):
            raise SubmissionBlocked("Domain is not on the configured allowlist")

    async def inspect_apply_page(self, url: str):
        self._check_url(url)
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            data = await self._inspect_page(page)
            await browser.close()
            return data

    async def _inspect_page(self, page):
        body = (await page.locator("body").inner_text())[:20000].lower()
        blocked_signals = [x for x in ("captcha", "recaptcha", "verify you are human", "two-factor", "2fa", "security code") if x in body]
        forms = await page.locator("form").count()
        inputs = await page.locator("input, textarea, select").count()
        return {"url": page.url, "title": await page.title(), "forms": forms, "inputs": inputs,
                "blocked_signals": blocked_signals, "ready_for_submission": not blocked_signals}

    async def submit(self, url: str, profile: dict, resume_path: str = "", dry_run: bool = False):
        self._check_url(url)
        from playwright.async_api import async_playwright
        storage = Path(settings.browser_profile_dir)
        storage.mkdir(parents=True, exist_ok=True)
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(str(storage), headless=settings.browser_headless)
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            info = await self._inspect_page(page)
            if info["blocked_signals"]:
                await context.close()
                raise SubmissionBlocked("Human action required: " + ", ".join(info["blocked_signals"]))
            if dry_run:
                await context.close()
                return {"submitted": False, "dry_run": True, "page": info}

            values = {
                "name": profile.get("name", ""), "email": profile.get("email", ""),
                "location": profile.get("location", ""), "headline": profile.get("headline", ""),
                "phone": profile.get("phone", "")
            }
            for key, value in values.items():
                if not value: continue
                selectors = [f'input[name*="{key}" i]', f'input[id*="{key}" i]', f'textarea[name*="{key}" i]', f'textarea[id*="{key}" i]']
                for sel in selectors:
                    loc = page.locator(sel).first
                    if await loc.count():
                        try: await loc.fill(value)
                        except Exception: pass
                        break

            if resume_path and Path(resume_path).exists():
                files = page.locator('input[type="file"]')
                if await files.count():
                    await files.first.set_input_files(resume_path)

            required = page.locator("input[required], textarea[required], select[required]")
            missing = []
            for i in range(await required.count()):
                el = required.nth(i)
                try:
                    val = await el.input_value()
                    if not val:
                        missing.append(await el.get_attribute("name"))
                except Exception: pass
            if missing:
                await context.close()
                raise SubmissionBlocked("Required fields need human input: " + ", ".join(x or "unnamed" for x in missing))

            # Never auto-submit legal attestations or payment/checkout flows.
            body = (await page.locator("body").inner_text()).lower()
            risky = ["i certify", "i attest", "legal authorization", "application fee", "payment required", "work authorization"]
            if any(x in body for x in risky):
                await context.close()
                raise SubmissionBlocked("Human review required for legal/work-authorization/payment content")

            buttons = page.locator('button[type="submit"], input[type="submit"], button:has-text("Apply"), button:has-text("Submit")')
            if not await buttons.count():
                await context.close()
                raise SubmissionBlocked("No safe application submit button detected")
            await buttons.first.click()
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            result = {"submitted": True, "url": page.url, "submitted_at": datetime.utcnow().isoformat()}
            await context.close()
            return result
