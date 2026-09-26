# JobHunt AI — Autonomous Application Agent

JobHunt AI is a deployment-ready foundation for an AI job-search agent that can discover roles, score fit, tailor applications, and — when explicitly enabled — submit routine applications through an allowed browser workflow.

## Autonomous mode

Set `AUTO_SUBMIT=true` in `.env`. The agent then uses a policy gate before every submission:

- minimum match score (`MINIMUM_MATCH_SCORE`, default 70)
- max applications per day (`MAX_APPLICATIONS_PER_DAY`, default 30)
- blocks senior/staff/principal/director-style roles by default
- blocks roles whose description indicates more than `MAX_REQUIRED_YEARS` years
- only submits to `ALLOWED_DOMAINS`
- pauses on CAPTCHA, reCAPTCHA, 2FA/security codes, unknown required fields, legal/work-authorization attestations, payment, or missing submit controls
- never attempts to bypass anti-bot controls

Use `POST /api/automation/run` to run the autonomous application cycle. It will create applications for qualified jobs, tailor them, and attempt submission until the daily budget is reached. A scheduler/cron job can call this endpoint periodically in deployment.

## Browser login

The worker uses a persistent Playwright profile at `BROWSER_PROFILE_DIR`. Run the browser once in headed mode (`BROWSER_HEADLESS=false`) and log into the job sites you are authorized to use. The agent then reuses that session; it does not need your passwords in the app database.

## Resume

Set `RESUME_PATH` to the local PDF/DOCX resume the agent is permitted to upload. For production, mount this file as a secret/volume rather than committing it to Git.

## Email applications

SMTP settings are included for direct application emails. The email worker uses the same profile/resume data and records the send result. Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, and `SMTP_PASSWORD`.

## Important deployment boundary

There is no universal safe adapter for every job website. JobHunt AI uses a generic browser worker plus an allowlist and can be extended with site-specific adapters. Only automate workflows where you are authorized to do so and where the site's rules permit it. Live submission requires network access, your authenticated browser session, and a real resume.

## Run

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Windows: run `start_windows.bat` after installing dependencies.

## API highlights

- `POST /api/jobs/ingest` — discover jobs
- `POST /api/jobs/{id}/qualify` — score a job
- `POST /api/applications/{id}/tailor` — personalize application
- `POST /api/applications/{id}/submit` — autonomous submission for one application
- `POST /api/automation/run` — autonomous batch cycle
- `GET /api/automation/policy` — inspect current safety/submission policy
- `POST /api/applications/{id}/inspect` — inspect an application page
- `POST /api/interviews/generate` — interview preparation
- `POST /api/feedback` — outcome learning

## Testing

Core matching, allowlist, and autonomous policy tests are included. The sandbox can validate the local application logic, but real third-party submissions must be tested only in a network-enabled deployment with your own authenticated sessions.
