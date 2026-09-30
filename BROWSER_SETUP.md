# Browser worker — setup and verification

This covers the two pieces that make the browser agent work: the Railway
worker (runs the real browser) and the Vercel app (talks to it over HTTP).

## 1. Deploy the worker on Railway

1. In Railway, create a service from `worker/` in this repo (it has its own
   `Dockerfile`, so Railway will build it as a container — don't point Railway
   at the repo root, point it at the `worker` folder specifically, or set
   the "root directory" to `worker` in the service settings).
2. Set these environment variables on the Railway service:
   - `BROWSER_WORKER_SECRET` — make up a long random string. You'll reuse the
     exact same value on Vercel.
   - `ALLOWED_DOMAINS` — optional. If you don't set it, it defaults to a solid
     list of real ATS providers (Greenhouse, Lever, Ashby, SmartRecruiters,
     Workable, Workday, BambooHR, Recruitee, Breezy, Jobvite, Teamtailor).
     Only set this yourself if you need to add or restrict domains.
3. Deploy. Railway will show you a public URL like
   `https://your-worker-name.up.railway.app`.
4. **Verify it's actually up** by visiting `https://your-worker-name.up.railway.app/health`
   in a browser. You should see JSON like:
   ```json
   {"status":"ok","worker":"playwright","allowed_domains":[...],"persistent_profile":false,"busy":false}
   ```
   If this doesn't load, stop here — nothing on the Vercel side will work
   until this does. Check Railway's build logs.

## 2. Point Vercel at the worker

On your Vercel project's environment variables, set:
- `BROWSER_WORKER_URL` — the full URL from step 1, **including `https://`**
  (e.g. `https://your-worker-name.up.railway.app`).
- `BROWSER_WORKER_SECRET` — the exact same value you set on Railway.

Redeploy Vercel after setting these (env var changes don't apply to already-running
deployments).

## 3. Deploy this update

```
cd ~/JobHunt-AI
unzip -o /path/to/jobhunt-browser-final.zip
git add -A && git commit -m "Browser worker: tested end-to-end" && git push origin main
```

This pushes to both places at once, since Vercel and Railway both watch the
same GitHub repo (Vercel builds from the repo root, Railway builds from
`worker/`).

## 4. Verify it yourself, in order

Do these in order — each one confirms the previous step actually worked,
so if something's wrong you'll know exactly where.

1. **Vercel root loads**: visit your production URL. You should see the
   dashboard, not JSON.
2. **Vercel health check**: visit `/api/health` — should return JSON with
   `"status":"ok"`.
3. **Worker health check**: visit your Railway worker's `/health` — should
   return JSON with `"status":"ok"`.
4. **Profile complete**: on My profile, make sure your name, email, and a
   resume are all saved (refresh the page — it should show "✓ On file:
   yourresume.pdf").
5. **Run the career agent** from Home to get some real, scored jobs into your
   pipeline.
6. **Field mapping preview**: on Apply tools, pick an application and click
   "Preview mapping" — it should show your real name/email/phone, and
   "resume" should show your filename, not "not set".
7. **Browser worker, dry run**: pick the same application, leave Dry run
   checked, click "Run browser worker". It should show the real fields it
   found on the real job page, what it would fill, and what (if anything)
   still needs you.
8. **Browser worker, for real**: once a dry run looks clean (nothing
   "needs you" except things you genuinely can't automate, like a CAPTCHA),
   uncheck Dry run and run it again. It will either submit and show a
   confirmation, or stop and tell you exactly why (and it will never
   silently fail — every stop comes with a specific reason).

## What "safe" means here

- The worker never fabricates anything — it only fills fields with data
  that's actually in your profile.
- It always stops for you on CAPTCHA, 2FA, login walls, legal/consent
  checkboxes, and any required question it can't map to your profile.
- The domain allowlist means it will only ever act on real ATS-hosted
  application pages, not random websites.
