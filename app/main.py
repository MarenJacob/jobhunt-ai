import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from .db import SessionLocal, init_db
from .models import Job, Application, Feedback, Profile, ATSRun, TailoringRun, TelemetryReport, InterviewSession, NegotiationRun, BrowserRun
from .schemas import JobIn, ProfileIn, ApplicationIn, FeedbackIn, SearchIn
from .services.matcher import match_job
from .services.sources import discover as discover_jobs
from .services.jobfilter import verify_page, looks_expired
from .services import jobfilter as _jf
from .services.ai import AIService
from .services.browser import BrowserAutomation
from .services.feedback import outcome_insight
from .services.submission import SubmissionService, SubmissionBlocked
from .services.resume_parser import extract_text, parse_resume
from .services.ats import detect_platform, map_profile, analyze_fields
from .services.tailoring import keyword_alignment, align_bullets
from .services.telemetry import company_telemetry
from .services.interview import build_mock
from .services.negotiation import model_offer, counter_script
from .services.candidate_protocol import issue_token

BASE = Path(__file__).parent
app = FastAPI(title="JobHunt AI", version="2.0.0", docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE/"static"), name="static")
templates = Jinja2Templates(directory=str(BASE/"templates"))

_db_ready = False
_db_lock = threading.Lock()

def ensure_db():
    """Initialize/migrate the database on first request as well as startup.

    Some serverless ASGI adapters do not guarantee FastAPI lifespan/startup
    execution before the first invocation. Keeping initialization here makes
    the application safe on Vercel cold starts without relying on lifespan.
    """
    global _db_ready
    if _db_ready:
        return
    with _db_lock:
        if not _db_ready:
            init_db()
            _db_ready = True

@app.on_event("startup")
def startup():
    ensure_db()

def db():
    ensure_db()
    s=SessionLocal()
    try: yield s
    finally: s.close()

def get_profile(s):
    p=s.query(Profile).first()
    if not p:
        p=Profile(name="", headline="", location="Nigeria", skills="Python, JavaScript, React, FastAPI, AI, prompt engineering, product design, web development", projects="", preferences="new grad, junior, graduate, remote, Nigeria")
        s.add(p); s.commit(); s.refresh(p)
    return p

@app.get("/", response_class=HTMLResponse)
def home(request: Request, s: Session=Depends(db)):
    import os as _os
    static_dir = _os.path.join(_os.path.dirname(__file__), "static")
    def _v(name):
        try: return str(int(_os.path.getmtime(_os.path.join(static_dir, name))))
        except OSError: return "1"
    context = {"request": request, "jobs": s.query(Job).order_by(Job.match_score.desc()).limit(25).all(), "apps": s.query(Application).order_by(Application.created_at.desc()).limit(10).all(), "profile": get_profile(s), "asset_v": {"css": _v("app.css"), "js": _v("app.js")}}
    return templates.TemplateResponse(request=request, name="index.html", context=context)

@app.get("/api/health")
def health():
    from .config import settings
    return {"status":"ok","service":"JobHunt AI","version":"3.0.0","search_configured":bool(settings.tavily_api_key),"ai_configured":bool(settings.openai_api_key),"database":"postgresql" if settings.database_url.startswith("postgres") else "sqlite"}

@app.get("/api/dashboard")
def dashboard(s: Session=Depends(db)):
    jobs=s.query(Job).filter(Job.expired==False).all(); apps=s.query(Application).all(); fb=s.query(Feedback).all()
    submitted=sum(a.status=="submitted" for a in apps)
    pending=sum(a.status in {"draft","application_draft","approved_for_submission"} for a in apps)
    blocked=sum(a.status in {"needs_human","submission_error"} for a in apps)
    expired_count=s.query(Job).filter(Job.expired==True).count()
    return {"jobs":len(jobs),"qualified":sum(j.match_score>=60 for j in jobs),"applications":len(apps),"interviews":sum(a.status=="interview" for a in apps),"submitted":submitted,"pending":pending,"blocked":blocked,"expired":expired_count,"feedback":outcome_insight(fb)}

@app.get("/api/jobs")
def jobs(include_expired: bool=False, s: Session=Depends(db)):
    q=s.query(Job)
    if not include_expired: q=q.filter(Job.expired==False)
    return [{"id":j.id,"title":j.title,"company":j.company,"location":j.location,"url":j.url,"source":j.source,"score":j.match_score,"status":j.status,"remote":j.remote,"verified":j.verified,"expired":j.expired,"posted_at":j.posted_at.isoformat() if j.posted_at else None,"description":j.description or ""} for j in q.order_by(Job.match_score.desc()).all()]

@app.post("/api/jobs")
def add_job(data: JobIn, s: Session=Depends(db)):
    j=s.query(Job).filter_by(url=data.url).first()
    if j: return {"id":j.id,"duplicate":True}
    j=Job(**data.model_dump()); s.add(j); s.commit(); s.refresh(j); return {"id":j.id}

@app.post("/api/jobs/ingest")
async def ingest(data: SearchIn, s: Session=Depends(db)):
    """Manual one-off search, filtered and verified the same way as the agent run
    (rejects blogs/wikis/listing pages; only stores single, open job postings)."""
    from .config import settings as _settings
    if not _settings.tavily_api_key:
        raise HTTPException(503, "Web search is not configured. Add TAVILY_API_KEY, or use Run career agent to pull from job feeds.")
    import httpx
    report = {"errors": [], "rejected": []}
    async with httpx.AsyncClient() as client:
        candidates = await __import__("app.services.sources", fromlist=["search_web"]).search_web(client, [data.query], report)
    added = []
    for c in candidates[: data.max_results]:
        if s.query(Job).filter_by(url=c.url).first(): continue
        j = Job(title=c.title, company=c.company, location=c.location, url=c.url, source=c.source,
                description=c.description, remote=c.remote, verified=c.verified)
        s.add(j); added.append(c.title)
    s.commit()
    return {"added": len(added), "titles": added, "rejected": len(report["rejected"]), "configured": True}

@app.post("/api/jobs/{job_id}/qualify")
def qualify(job_id:int,s:Session=Depends(db)):
    j=s.get(Job,job_id)
    if not j: raise HTTPException(404,"Job not found")
    p=get_profile(s); text=" ".join([p.skills,p.projects,p.experience,p.education,p.preferences])
    r=match_job(j.title+" "+j.description,text,p.preferences,j.title,p.headline or "",p.location or "")
    j.match_score=r.score; j.qualification=json.dumps({"matched":r.matched,"gaps":r.gaps,"rationale":r.rationale,"flags":r.flags}); j.status="qualified" if r.score>=60 else "review"
    s.commit(); return {"score":r.score,"matched":r.matched,"gaps":r.gaps,"rationale":r.rationale}


@app.get("/api/applications")
def applications(s: Session=Depends(db)):
    rows=[]
    for a in s.query(Application).order_by(Application.created_at.desc()).limit(100).all():
        j=s.get(Job,a.job_id)
        rows.append({"id":a.id,"job_id":a.job_id,"title":j.title if j else "Unknown role","company":j.company if j else "Unknown","score":j.match_score if j else 0,"status":a.status,"submitted_at":a.submitted_at.isoformat() if a.submitted_at else None,"follow_up_at":a.follow_up_at.isoformat() if a.follow_up_at else None,"notes":a.notes or ""})
    return rows

@app.get("/api/profile")
def profile_get(s: Session=Depends(db)):
    p=get_profile(s)
    return {c:getattr(p,c) for c in ["name","headline","email","location","skills","projects","experience","education","preferences","phone","address","linkedin","github","website","work_authorization","sponsorship","salary","resume_filename"]}

@app.get("/api/automation/status")
def automation_status(s: Session=Depends(db)):
    from .config import settings
    today=datetime.utcnow().date()
    submitted=s.query(Application).filter(Application.status=="submitted", Application.submitted_at!=None, Application.submitted_at>=datetime.combine(today, datetime.min.time())).count()
    return {"enabled":settings.auto_submit,"submitted_today":submitted,"daily_limit":settings.max_applications_per_day,"remaining":max(0,settings.max_applications_per_day-submitted),"threshold":settings.minimum_match_score}

@app.api_route("/api/cron/agent", methods=["GET", "POST"])
async def cron_agent(request: Request, s: Session=Depends(db)):
    from .config import settings
    if settings.cron_secret:
        supplied=request.headers.get("authorization","")
        if supplied != f"Bearer {settings.cron_secret}":
            raise HTTPException(401,"Unauthorized")
    if not settings.auto_submit:
        return {"ok":True,"skipped":True,"reason":"AUTO_SUBMIT is disabled"}
    return await automation_run(s)

@app.post("/api/profile")
def profile(data:ProfileIn,s:Session=Depends(db)):
    p=get_profile(s)
    for k,v in data.model_dump().items(): setattr(p,k,v)
    s.commit(); return {"ok":True}

@app.post("/api/profile/import-resume")
async def import_resume(file: UploadFile = File(...)):
    filename = file.filename or "resume"
    if not filename.lower().endswith((".pdf", ".docx")):
        raise HTTPException(400, "Upload a PDF or DOCX resume.")
    data = await file.read()
    if not data:
        raise HTTPException(400, "The uploaded resume is empty.")
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, "Resume must be 8 MB or smaller.")
    try:
        text = extract_text(filename, data)
        if len(text.strip()) < 80:
            raise ValueError("Could not extract enough text from this resume. Try an editable PDF/DOCX.")
        parsed = parse_resume(text, AIService())
        parsed["filename"] = filename
        # Persist the source resume so the browser worker can attach it later.
        # Parsed profile fields remain reviewable in the UI before final save.
        s = SessionLocal()
        try:
            p = get_profile(s)
            p.resume_filename = filename
            p.resume_blob = data
            for k in ["name","headline","email","location","skills","projects","experience","education","preferences","phone","address","linkedin","github","website"]:
                if parsed.get(k): setattr(p,k,parsed[k])
            s.commit()
        finally:
            s.close()
        parsed["characters"] = len(text)
        parsed["resume_blob"] = data
        return {"ok": True, "profile": {k:v for k,v in parsed.items() if k != "resume_blob"}, "message": "Resume parsed successfully. Review the imported fields, then save your profile. The resume is retained for ATS uploads after you save."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(422, f"Resume parsing failed: {e}")

@app.post("/api/applications")
def create_application(data:ApplicationIn,s:Session=Depends(db)):
    j=s.get(Job,data.job_id)
    if not j: raise HTTPException(404,"Job not found")
    a=Application(job_id=j.id); s.add(a); j.status="application_draft"; s.commit(); s.refresh(a); return {"id":a.id,"status":a.status}

@app.post("/api/applications/{application_id}/tailor")
def tailor(application_id:int,s:Session=Depends(db)):
    a=s.get(Application,application_id)
    if not a: raise HTTPException(404,"Application not found")
    j=s.get(Job,a.job_id); p=get_profile(s)
    profile={c:getattr(p,c) for c in ["name","headline","email","location","skills","projects","experience","education","preferences","phone","address","linkedin","github","website","work_authorization","sponsorship","salary","resume_filename"]}
    job={"title":j.title,"company":j.company,"location":j.location,"description":j.description,"url":j.url}
    out=AIService().tailor(profile,job); a.cover_letter=out.get("cover_letter",""); a.tailored_cv=out.get("cv_summary",""); a.answers=json.dumps(out.get("screening_questions",[])); s.commit(); return out

@app.post("/api/applications/{application_id}/approve")
def approve(application_id:int,s:Session=Depends(db)):
    a=s.get(Application,application_id)
    if not a: raise HTTPException(404,"Application not found")
    a.approved=True; a.status="approved_for_submission"; s.commit(); return {"approved":True,"next_step":"Use the browser workflow or submit manually after review."}

@app.get("/api/agent/readiness")
def agent_readiness(s: Session=Depends(db)):
    from .config import settings
    p=get_profile(s)
    checks={
        "profile": bool((p.name or '').strip() and (p.email or '').strip()),
        "search": bool(settings.tavily_api_key),
        "ai": bool(settings.openai_api_key),
        "database": True,
        "submission": bool(settings.auto_submit),
        "browser_worker": bool(settings.browser_worker_url),
    }
    return {"ready": checks["profile"] and checks["search"], "checks":checks, "mode":"autonomous" if settings.auto_submit else "safe", "message":"Ready to discover and qualify jobs." if checks["profile"] and checks["search"] else "Complete your candidate profile and add TAVILY_API_KEY before running the agent."}

@app.post("/api/agent/run")
async def agent_run(s: Session=Depends(db)):
    """Discover new roles from real job feeds + verified web search, re-check the
    existing pipeline for postings that have gone stale, then score everything."""
    from .config import settings
    profile = get_profile(s)
    if not (profile.name or "").strip() or not (profile.email or "").strip():
        raise HTTPException(400, "Add your name and email in My profile before running the agent.")
    profile_dict = {c: getattr(profile, c) for c in ["headline", "skills", "projects", "experience", "education", "preferences", "location"]}

    known_urls = {u for (u,) in s.query(Job.url).all()}
    candidates, report = await discover_jobs(profile_dict, known_urls)
    discovered = 0
    now = datetime.utcnow()
    for c in candidates:
        j = Job(title=c.title, company=c.company, location=c.location, url=c.url, source=c.source,
                description=c.description, remote=c.remote, verified=c.verified, posted_at=now, last_checked_at=now)
        s.add(j); discovered += 1
    s.commit()

    # Re-check open roles already in the pipeline so stale postings do not linger forever.
    stale_cutoff = now - timedelta(days=settings.job_stale_days if hasattr(settings, "job_stale_days") else 10)
    to_check = (s.query(Job).filter(Job.expired == False, Job.status.in_(["discovered", "qualified", "review"]))
                .filter((Job.last_checked_at == None) | (Job.last_checked_at < stale_cutoff)).order_by(Job.created_at.desc()).limit(25).all())
    rechecked, expired_now = 0, 0
    if to_check:
        import httpx
        async with httpx.AsyncClient() as client:
            for j in to_check:
                jp, text, status = await verify_page(client, j.url)
                j.last_checked_at = now; rechecked += 1
                if status in (404, 410) or looks_expired(text) or (jp and jp.get("expired")):
                    j.expired = True; j.status = "expired"; expired_now += 1
                elif jp:
                    j.verified = True
                    if jp.get("description"): j.description = jp["description"]
        s.commit()

    text = " ".join([profile.skills or "", profile.projects or "", profile.experience or "", profile.education or "", profile.preferences or ""])
    jobs = s.query(Job).filter(Job.expired == False).order_by(Job.created_at.desc()).limit(150).all()
    qualified = 0
    drafts = 0
    for j in jobs:
        r = match_job(j.title + " " + (j.description or ""), text, profile.preferences or "", j.title, profile.headline or "", profile.location or "")
        j.match_score = r.score
        j.qualification = json.dumps({"matched": r.matched, "gaps": r.gaps, "rationale": r.rationale, "flags": r.flags})
        j.status = "qualified" if r.score >= settings.minimum_match_score else "review"
        if j.status == "qualified":
            qualified += 1
            a = s.query(Application).filter_by(job_id=j.id).first()
            if not a:
                s.add(Application(job_id=j.id, status="application_draft")); drafts += 1
    s.commit()

    result = {"mode": "autonomous" if settings.auto_submit else "safe", "discovered": discovered, "qualified": qualified,
              "drafts": drafts, "prepared": drafts, "skipped": len(known_urls), "total_roles": len(jobs),
              "rechecked": rechecked, "expired": expired_now, "sources": report["sources"],
              "rejected_examples": report["rejected"][:8], "rejected_total": len(report["rejected"]),
              "search_errors": report["errors"]}
    if not report["sources"] and not settings.tavily_api_key:
        result["message"] = "No job feeds returned results this run and web search is not configured (set TAVILY_API_KEY). Existing roles were re-scored."
    elif settings.auto_submit:
        execution = await automation_run(s)
        result.update(execution)
    else:
        result["message"] = f"Found {discovered} new role(s), rejected {len(report['rejected'])} non-job pages, and rechecked {rechecked} existing listing(s) ({expired_now} had gone stale)."
    return result


@app.post("/api/automation/run")
async def automation_run(s:Session=Depends(db)):
    from .config import settings
    if not settings.auto_submit:
        raise HTTPException(403,"AUTO_SUBMIT is disabled")
    today=datetime.utcnow().date()
    submitted_today=s.query(Application).filter(Application.submitted_at!=None, Application.submitted_at>=datetime.combine(today, datetime.min.time())).count()
    budget=max(0, settings.max_applications_per_day-submitted_today)
    jobs=s.query(Job).filter(Job.match_score>=settings.minimum_match_score, Job.status.in_(["qualified","application_draft"])).order_by(Job.match_score.desc()).limit(budget).all()
    p=get_profile(s); profile={c:getattr(p,c) for c in ["name","headline","email","location","skills","projects","experience","education","preferences","phone","address","linkedin","github","website","work_authorization","sponsorship","salary","resume_filename"]}
    results=[]
    for j in jobs:
        a=s.query(Application).filter_by(job_id=j.id).first()
        if not a:
            a=Application(job_id=j.id, status="application_draft"); s.add(a); s.flush()
        if not a.cover_letter:
            try:
                job={"title":j.title,"company":j.company,"location":j.location,"description":j.description,"url":j.url}
                out=AIService().tailor(profile,job); a.cover_letter=out.get("cover_letter",""); a.tailored_cv=out.get("cv_summary",""); a.answers=json.dumps(out.get("screening_questions",[]))
            except Exception as e:
                a.status="needs_human"; a.notes="Tailoring failed: "+str(e); results.append({"job_id":j.id,"status":a.status}); continue
        try:
            out=await SubmissionService(s).submit_application(a,j,profile)
            results.append({"job_id":j.id,"status":a.status,"result":out.get("result",{})})
        except SubmissionBlocked as e:
            a.status="needs_human"; a.notes=str(e); results.append({"job_id":j.id,"status":a.status,"reason":str(e)})
        except Exception as e:
            a.status="submission_error"; a.notes=str(e); results.append({"job_id":j.id,"status":a.status,"reason":str(e)})
        s.commit()
    return {"processed":len(results),"daily_budget_remaining":max(0, budget-len([x for x in results if x.get("status")=="submitted"])),"results":results}

@app.get("/api/automation/policy")
def automation_policy(s: Session=Depends(db)):
    return {"auto_submit": __import__("app.config", fromlist=["settings"]).settings.auto_submit, "max_applications_per_day": __import__("app.config", fromlist=["settings"]).settings.max_applications_per_day, "minimum_match_score": __import__("app.config", fromlist=["settings"]).settings.minimum_match_score, "allowed_domains": __import__("app.config", fromlist=["settings"]).settings.allowed_domains.split(",")}

@app.post("/api/applications/{application_id}/submit")
async def submit_application(application_id:int, dry_run: bool=False, s:Session=Depends(db)):
    a=s.get(Application,application_id)
    if not a: raise HTTPException(404,"Application not found")
    j=s.get(Job,a.job_id); p=get_profile(s)
    if not a.cover_letter and not a.tailored_cv:
        raise HTTPException(400,"Tailor the application before autonomous submission")
    if not __import__("app.config", fromlist=["settings"]).settings.auto_submit and not dry_run:
        raise HTTPException(403,"AUTO_SUBMIT is disabled. Enable it in .env after reviewing your policy.")
    profile={c:getattr(p,c) for c in ["name","headline","email","location","skills","projects","experience","education","preferences","phone","address","linkedin","github","website","work_authorization","sponsorship","salary","resume_filename"]}
    try:
        out=await SubmissionService(s).submit_application(a,j,profile,dry_run=dry_run)
        s.commit()
        return out
    except SubmissionBlocked as e:
        a.status="needs_human"; a.notes=str(e); s.commit()
        raise HTTPException(409,str(e))
    except Exception as e:
        a.status="submission_error"; a.notes=str(e); s.commit()
        raise HTTPException(500,str(e))

@app.post("/api/applications/{application_id}/inspect")
async def inspect(application_id:int,s:Session=Depends(db)):
    a=s.get(Application,application_id); j=s.get(Job,a.job_id) if a else None
    if not j: raise HTTPException(404,"Application not found")
    try:
        out=await BrowserAutomation().inspect_apply_page(j.url)
        run=BrowserRun(application_id=a.id, platform=__import__("app.services.ats",fromlist=["detect_platform"]).detect_platform(j.url), action="inspect", status="ready" if out.get("ready_for_submission") else "needs_human", details=json.dumps(out))
        s.add(run); s.commit()
        return out
    except Exception as e:
        run=BrowserRun(application_id=a.id, platform=__import__("app.services.ats",fromlist=["detect_platform"]).detect_platform(j.url), action="inspect", status="error", details=json.dumps({"error":str(e)}))
        s.add(run); s.commit(); raise HTTPException(400,str(e))

@app.post("/api/interviews/generate")
def interview(job_id:int,s:Session=Depends(db)):
    j=s.get(Job,job_id); p=get_profile(s)
    if not j: raise HTTPException(404,"Job not found")
    profile={c:getattr(p,c) for c in ["name","headline","skills","projects","experience","education"]}
    return json.loads(AIService().interview(profile,{"title":j.title,"company":j.company,"description":j.description}))


@app.post("/api/applications/{application_id}/ats-map")
def ats_map(application_id:int, fields: list[dict], s:Session=Depends(db)):
    a=s.get(Application,application_id)
    if not a: raise HTTPException(404,"Application not found")
    j=s.get(Job,a.job_id)
    p=get_profile(s)
    profile={c:getattr(p,c) for c in ["name","headline","email","location","skills","projects","experience","education","preferences","phone","address","linkedin","github","website","work_authorization","sponsorship","salary","resume_filename"]}
    platform=detect_platform(j.url)
    mapping=map_profile(profile,fields)
    unresolved=[f.get('label') or f.get('name') for f in fields if f.get('required') and not mapping.get(f.get('name') or f.get('id') or f.get('label'))]
    run=ATSRun(application_id=a.id,platform=platform,field_map=json.dumps(mapping),unresolved=json.dumps(unresolved),status='needs_human' if unresolved else 'mapped')
    s.add(run); s.commit()
    return {'platform':platform,'mapping':mapping,'unresolved':unresolved,'status':run.status}

@app.get("/api/applications/{application_id}/ats")
def ats_status(application_id:int,s:Session=Depends(db)):
    rows=s.query(ATSRun).filter_by(application_id=application_id).order_by(ATSRun.created_at.desc()).all()
    return [{'id':r.id,'platform':r.platform,'mapping':json.loads(r.field_map or '{}'),'unresolved':json.loads(r.unresolved or '[]'),'status':r.status} for r in rows]

@app.post("/api/applications/{application_id}/browser/inspect")
async def browser_inspect(application_id:int,s:Session=Depends(db)):
    return await inspect(application_id,s)

@app.get("/api/applications/{application_id}/browser/runs")
def browser_runs(application_id:int,s:Session=Depends(db)):
    rows=s.query(BrowserRun).filter_by(application_id=application_id).order_by(BrowserRun.created_at.desc()).limit(20).all()
    return [{"id":r.id,"platform":r.platform,"action":r.action,"status":r.status,"mapping":json.loads(r.mapping or "{}"),"unresolved":json.loads(r.unresolved or "[]"),"details":json.loads(r.details or "{}"),"created_at":r.created_at.isoformat()} for r in rows]

@app.post("/api/applications/{application_id}/browser/execute")
async def browser_execute(application_id:int,dry_run:bool=False,s:Session=Depends(db)):
    # NOTE: AUTO_SUBMIT only gates the unattended /api/automation/run loop. Clicking
    # "Run browser worker" here with dry_run=False IS the person's explicit, one-off
    # instruction to submit this one application — that's not autonomous behavior,
    # so it isn't blocked by the autonomy policy. The worker itself still stops for
    # CAPTCHA, 2FA, logins, legal/consent text, and any unresolved required field.
    from .config import settings
    a=s.get(Application,application_id)
    if not a: raise HTTPException(404,"Application not found")
    j=s.get(Job,a.job_id)
    if not j: raise HTTPException(404,"Job not found")
    p=get_profile(s)
    profile={c:getattr(p,c) for c in ["name","headline","email","location","skills","projects","experience","education","preferences","phone","address","linkedin","github","website","work_authorization","sponsorship","salary","resume_filename"]}
    try:
        out=await BrowserAutomation().submit(j.url,profile,settings.resume_path,p.resume_blob,p.resume_filename,a.cover_letter,dry_run=dry_run)
        status="submitted" if out.get("submitted") else "dry_run"
        run=BrowserRun(application_id=a.id,platform=detect_platform(j.url),action="submit",status=status,details=json.dumps(out))
        s.add(run); s.commit()
        if out.get("submitted"):
            a.status="submitted"; a.submitted_at=datetime.utcnow(); a.follow_up_at=datetime.utcnow()+timedelta(days=settings.follow_up_days); s.commit()
        return out
    except SubmissionBlocked as e:
        run=BrowserRun(application_id=a.id,platform=detect_platform(j.url),action="submit",status="needs_human",details=json.dumps({"error":str(e)})); s.add(run); s.commit()
        a.status="needs_human"; a.notes=str(e); s.commit(); raise HTTPException(409,str(e))

@app.post("/api/applications/{application_id}/tailor/analyze")
def tailor_analyze(application_id:int,s:Session=Depends(db)):
    a=s.get(Application,application_id)
    if not a: raise HTTPException(404,"Application not found")
    j=s.get(Job,a.job_id); p=get_profile(s)
    resume=' '.join([p.headline,p.skills,p.projects,p.experience,p.education])
    alignment=keyword_alignment(resume,j.description or j.title)
    bullets=[]
    for section in (p.experience or '').split('\n'):
        line=section.strip(' •-')
        if line: bullets.append(line)
    bullet_result=align_bullets(bullets[:40],j.description or j.title)
    run=TailoringRun(application_id=a.id,ats_score=alignment['score'],matched_keywords=json.dumps(alignment['matched']),missing_keywords=json.dumps(alignment['missing']),bullet_alignment=json.dumps(bullet_result))
    s.add(run); s.commit()
    return {'ats_score':alignment['score'],'matched_keywords':alignment['matched'],'missing_keywords':alignment['missing'],'bullet_alignment':bullet_result}

@app.get("/api/applications/{application_id}/tailoring")
def tailoring_history(application_id:int,s:Session=Depends(db)):
    rows=s.query(TailoringRun).filter_by(application_id=application_id).order_by(TailoringRun.created_at.desc()).all()
    return [{'id':r.id,'ats_score':r.ats_score,'matched_keywords':json.loads(r.matched_keywords),'missing_keywords':json.loads(r.missing_keywords),'bullet_alignment':json.loads(r.bullet_alignment)} for r in rows]

@app.post("/api/companies/{company}/telemetry")
def telemetry(company:str,s:Session=Depends(db)):
    jobs=[{'company':j.company,'title':j.title,'location':j.location} for j in s.query(Job).all()]
    apps=[]
    for a in s.query(Application).all():
        j=s.get(Job,a.job_id); apps.append({'company':j.company if j else '','status':a.status})
    report=company_telemetry(company,jobs,apps)
    s.add(TelemetryReport(company=company,report=json.dumps(report))); s.commit()
    return report

@app.post("/api/interviews/mock")
def mock_interview(job_id:int,s:Session=Depends(db)):
    j=s.get(Job,job_id)
    if not j: raise HTTPException(404,"Job not found")
    p=get_profile(s); profile={c:getattr(p,c) for c in ['skills','projects','experience','education']}
    session=build_mock({'title':j.title,'company':j.company,'description':j.description},profile)
    row=InterviewSession(job_id=job_id,session=json.dumps(session)); s.add(row); s.commit(); s.refresh(row)
    return {'id':row.id,**session}

@app.get("/api/interviews/{session_id}")
def get_interview(session_id:int,s:Session=Depends(db)):
    row=s.get(InterviewSession,session_id)
    if not row: raise HTTPException(404,"Interview session not found")
    return json.loads(row.session)

@app.post("/api/applications/{application_id}/negotiation")
def negotiation(application_id:int, payload:dict,s:Session=Depends(db)):
    a=s.get(Application,application_id)
    if not a: raise HTTPException(404,"Application not found")
    j=s.get(Job,a.job_id)
    analysis=model_offer(payload.get('offer'),payload.get('market_low'),payload.get('market_high'))
    script=counter_script(j.title,j.company,analysis['counter_reference'])
    row=NegotiationRun(application_id=application_id,analysis=json.dumps(analysis),script=script); s.add(row); s.commit()
    return {'analysis':analysis,'script':script}

@app.post("/api/candidate/token")
def candidate_token(s:Session=Depends(db)):
    from .config import settings
    p=get_profile(s)
    profile={c:getattr(p,c) for c in ['name','headline','email','location','skills','projects','experience','education']}
    return issue_token(profile,settings.secret_key)

@app.post("/api/candidate/token/verify")
def candidate_token_verify(payload:dict):
    from .config import settings
    from .services.candidate_protocol import verify_token
    result=verify_token(payload.get('token',''),settings.secret_key)
    if not result: raise HTTPException(401,'Invalid or expired candidate token')
    return result

@app.post("/api/feedback")
def feedback(data:FeedbackIn,s:Session=Depends(db)):
    a=s.get(Application,data.application_id)
    if not a: raise HTTPException(404,"Application not found")
    s.add(Feedback(**data.model_dump())); a.status=data.outcome; s.commit(); return {"ok":True,"insight":outcome_insight(s.query(Feedback).all())}

@app.get("/api/followups")
def followups(s:Session=Depends(db)):
    now=datetime.utcnow(); rows=s.query(Application).filter(Application.follow_up_at!=None,Application.follow_up_at<=now).all()
    return [{"id":a.id,"job_id":a.job_id,"status":a.status,"follow_up_at":a.follow_up_at} for a in rows]
