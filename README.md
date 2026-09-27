# JobHunt AI — Career Agent v5

A career operating system that discovers roles, scores fit, prepares applications, inspects live ATS forms, maps candidate data, fills supported ATS flows through a persistent Playwright browser worker, and pauses when human-only checkpoints are encountered.

## Architecture

- **Web/API:** FastAPI + PostgreSQL/SQLite
- **Agent orchestration:** Vercel/serverless compatible
- **Search:** Tavily
- **AI:** OpenAI-compatible career intelligence
- **Browser:** dedicated Playwright worker with persistent browser profile
- **ATS:** Workday, Greenhouse, Lever, Ashby, SmartRecruiters + generic forms
- **Resume:** PDF/DOCX extraction and stored source document for later upload

## Real browser worker

For local/production Docker execution:

```bash
cp .env.example .env
# set DATABASE_URL, OPENAI_API_KEY, TAVILY_API_KEY and BROWSER_WORKER_SECRET
docker compose up --build
```

The API uses `BROWSER_WORKER_URL` to delegate live browser work. The worker keeps its authenticated profile under `storage/browser-profile`.

### Human checkpoints

The worker intentionally pauses for:

- CAPTCHA / reCAPTCHA / human verification
- 2FA/security codes
- login that requires user authentication
- legal/work-authorisation attestations
- payment/application fees
- unknown required questions or fields
- unsafe/ambiguous submit controls

It does not bypass anti-bot controls or invent candidate information.

## Vercel deployment

Deploy the API/UI to Vercel and host the browser worker separately. Set:

```text
BROWSER_WORKER_URL=https://your-private-worker.example.com
BROWSER_WORKER_SECRET=...
```

Do not expose the worker publicly without authentication. Keep its browser-profile storage persistent.

## Resume import

Candidate Profile → Upload PDF/DOCX → Parse & auto-fill → review → Save. The source resume is retained so the browser worker can attach it to ATS file inputs.

## Safe rollout

1. `AUTO_SUBMIT=false`
2. Run agent and qualify roles
3. Create application drafts
4. Inspect ATS pages
5. Use browser-worker dry runs
6. Review mapping and unresolved fields
7. Enable autonomous submission only after policy review

The system never claims universal compatibility with every employer website. New ATS patterns should be added as adapters rather than weakening the safety checks.
