"""ATS browser orchestration.

This process (Vercel) never launches a real browser itself — serverless
functions have no Chromium binary and no persistent filesystem, so trying to
do that here crashes with a 500. All real browser work happens on the
separate Playwright worker (see worker/app.py, deployed on Railway or similar)
and is reached over HTTP via BROWSER_WORKER_URL. If that isn't configured or
isn't reachable, we raise a clear, actionable error instead of crashing.
"""
import base64, re
from urllib.parse import urlparse

import httpx

from ..config import settings


class SubmissionBlocked(Exception):
    pass


class BrowserAutomation:
    def allowed(self, url: str) -> bool:
        host = urlparse(url).netloc.lower().split(":")[0].replace("www.", "")
        return any(host == d.strip() or host.endswith("." + d.strip()) for d in settings.allowed_domains.split(",") if d.strip())

    def _check_url(self, url: str):
        if not self.allowed(url):
            raise SubmissionBlocked("This job's domain is not on the configured allowlist (ALLOWED_DOMAINS).")

    def _worker_url(self):
        raw = (settings.browser_worker_url or "").strip()
        if not raw:
            return ""
        return raw if re.match(r"^https?://", raw, re.I) else "https://" + raw

    async def _remote(self, payload: dict):
        url = self._worker_url()
        if not url:
            raise SubmissionBlocked(
                "The browser worker isn't configured yet. Deploy the worker/ service (e.g. on Railway) and set "
                "BROWSER_WORKER_URL (and BROWSER_WORKER_SECRET) in this app's environment variables, then redeploy."
            )
        headers = {"Authorization": f"Bearer {settings.browser_worker_secret}"} if settings.browser_worker_secret else {}
        try:
            async with httpx.AsyncClient(timeout=settings.browser_worker_timeout) as client:
                r = await client.post(url.rstrip("/") + "/execute", json=payload, headers=headers)
            data = r.json() if r.content else {}
            if r.status_code >= 400:
                raise SubmissionBlocked(data.get("detail") or data.get("message") or f"Browser worker returned {r.status_code}")
            return data
        except httpx.ConnectError as e:
            raise SubmissionBlocked(f"Could not reach the browser worker at {url}. Check that it's deployed and running, and that BROWSER_WORKER_URL is correct. ({e})")
        except httpx.HTTPError as e:
            raise SubmissionBlocked(f"Browser worker unavailable: {e}")

    async def inspect_apply_page(self, url: str):
        self._check_url(url)
        return await self._remote({"action": "inspect", "url": url})

    async def submit(self, url: str, profile: dict, resume_path: str = "", resume_bytes: bytes | None = None,
                      resume_filename: str = "resume.pdf", cover_letter: str = "", dry_run: bool = False):
        self._check_url(url)
        resume_b64 = base64.b64encode(resume_bytes).decode("ascii") if resume_bytes else ""
        payload = {"action": "submit", "url": url, "profile": profile, "cover_letter": cover_letter,
                   "dry_run": dry_run, "resume_base64": resume_b64, "resume_filename": resume_filename}
        return await self._remote(payload)
