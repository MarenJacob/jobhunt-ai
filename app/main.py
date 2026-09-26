import json
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from .db import SessionLocal, init_db
from .models import Job, Application, Feedback, Profile
from .schemas import JobIn, ProfileIn, ApplicationIn, FeedbackIn, SearchIn
from .services.matcher import match_job
from .services.search import SearchService
from .services.ai import AIService
from .services.browser import BrowserAutomation
from .services.feedback import outcome_insight
from .services.submission import SubmissionService, SubmissionBlocked

BASE = Path(__file__).parent
app = FastAPI(title="JobHunt AI", version="2.0.0", docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE/"static"), name="static")
templates = Jinja2Templates(directory=str(BASE/"templates"))

@app.on_event("startup")
def startup(): init_db()

def db():
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
    context = {"request": request, "jobs": s.query(Job).order_by(Job.match_score.desc()).limit(25).all(), "apps": s.query(Application).order_by(Application.created_at.desc()).limit(10).all(), "profile": get_profile(s)}
    return templates.TemplateResponse(request=request, name="index.html", context=context)

@app.get("/api/health")
def health():
    from .config import settings
    return {"status":"ok","service":"JobHunt AI","version":"2.1.0","search_configured":bool(settings.tavily_api_key),"ai_configured":bool(settings.openai_api_key),"database":"postgresql" if settings.database_url.startswith("postgres") else "sqlite"}

@app.get("/api/dashboard")
def dashboard(s: Session=Depends(db)):
    jobs=s.query(Job).all(); apps=s.query(Application).all(); fb=s.query(Feedback).all()
    submitted=sum(a.status=="submitted" for a in apps)
    pending=sum(a.status in {"draft","application_draft","approved_for_submission"} for a in apps)
    blocked=sum(a.status in {"needs_human","submission_error"} for a in apps)
    return {"jobs":len(jobs),"qualified":sum(j.match_score>=60 for j in jobs),"applications":len(apps),"interviews":sum(a.status=="interview" for a in apps),"submitted":submitted,"pending":pending,"blocked":blocked,"feedback":outcome_insight(fb)}

@app.get("/api/jobs")
def jobs(s: Session=Depends(db)): return [{"id":j.id,"title":j.title,"company":j.company,"location":j.location,"url":j.url,"source":j.source,"score":j.match_score,"status":j.status,"remote":j.remote,"description":j.description or ""} for j in s.query(Job).order_by(Job.match_score.desc()).all()]

@app.post("/api/jobs")
def add_job(data: JobIn, s: Session=Depends(db)):
    j=s.query(Job).filter_by(url=data.url).first()
    if j: return {"id":j.id,"duplicate":True}
    j=Job(**data.model_dump()); s.add(j); s.commit(); s.refresh(j); return {"id":j.id}

@app.post("/api/jobs/ingest")
async def ingest(data: SearchIn, s: Session=Depends(db)):
    results=await SearchService().search(data.query, data.max_results)
    added=[]
    for r in results:
        url=r.get("url","")
        if not url: continue
        if s.query(Job).filter_by(url=url).first(): continue
        title=r.get("title",""); desc=r.get("content",""); company=r.get("company","") or ""
        j=Job(title=title,company=company,location="",url=url,source=SearchService.source_for(url),description=desc,remote="remote" in (title+desc).lower())
        s.add(j); added.append(title)
    s.commit(); return {"added":len(added),"titles":added,"configured":bool(results or __import__('os').getenv('TAVILY_API_KEY'))}

@app.post("/api/jobs/{job_id}/qualify")
def qualify(job_id:int,s:Session=Depends(db)):
    j=s.get(Job,job_id)
    if not j: raise HTTPException(404,"Job not found")
    p=get_profile(s); text=" ".join([p.skills,p.projects,p.experience,p.education,p.preferences])
    r=match_job(j.title+" "+j.description,text,p.preferences)
    j.match_score=r.score; j.qualification=json.dumps({"matched":r.matched,"gaps":r.gaps,"rationale":r.rationale}); j.status="qualified" if r.score>=60 else "review"
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
    return {c:getattr(p,c) for c in ["name","headline","email","location","skills","projects","experience","education","preferences"]}

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
    profile={c:getattr(p,c) for c in ["name","headline","email","location","skills","projects","experience","education","preferences"]}
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
    }
    return {"ready": checks["profile"] and checks["search"], "checks":checks, "mode":"autonomous" if settings.auto_submit else "safe", "message":"Ready to discover and qualify jobs." if checks["profile"] and checks["search"] else "Complete your candidate profile and add TAVILY_API_KEY before running the agent."}

@app.post("/api/agent/run")
async def agent_run(s: Session=Depends(db)):
    """Run the career agent in safe mode when autonomous submission is disabled.

    Safe mode discovers and qualifies roles and prepares application drafts; it
    never submits applications unless AUTO_SUBMIT is explicitly enabled.
    """
    from .config import settings
    profile = get_profile(s)
    query = f"{profile.headline or 'software engineer'} jobs careers {profile.preferences or 'junior graduate remote Nigeria'}"
    discovered = 0
    if settings.tavily_api_key:
        results = await SearchService().search(query, 20)
        for r in results:
            url = r.get("url", "")
            if not url or s.query(Job).filter_by(url=url).first():
                continue
            title = r.get("title", "")
            desc = r.get("content", "")
            company = r.get("company", "") or ""
            j = Job(title=title, company=company, location="", url=url,
                    source=SearchService.source_for(url), description=desc,
                    remote="remote" in (title + " " + desc).lower())
            s.add(j); discovered += 1
        s.commit()

    text = " ".join([profile.skills or "", profile.projects or "", profile.experience or "", profile.education or "", profile.preferences or ""])
    jobs = s.query(Job).order_by(Job.created_at.desc()).limit(50).all()
    qualified = 0
    drafts = 0
    for j in jobs:
        r = match_job(j.title + " " + (j.description or ""), text, profile.preferences or "")
        j.match_score = r.score
        j.qualification = json.dumps({"matched": r.matched, "gaps": r.gaps, "rationale": r.rationale})
        j.status = "qualified" if r.score >= settings.minimum_match_score else "review"
        if j.status == "qualified":
            qualified += 1
            a = s.query(Application).filter_by(job_id=j.id).first()
            if not a:
                s.add(Application(job_id=j.id, status="application_draft")); drafts += 1
    s.commit()

    if settings.auto_submit:
        execution = await automation_run(s)
        return {"mode": "autonomous", "discovered": discovered, "qualified": qualified, "drafts": drafts, **execution}
    return {"mode": "safe", "discovered": discovered, "qualified": qualified, "drafts": drafts,
            "message": "Roles discovered, scored and prepared. Submission remains off until you explicitly enable AUTO_SUBMIT."}


@app.post("/api/automation/run")
async def automation_run(s:Session=Depends(db)):
    from .config import settings
    if not settings.auto_submit:
        raise HTTPException(403,"AUTO_SUBMIT is disabled")
    today=datetime.utcnow().date()
    submitted_today=s.query(Application).filter(Application.submitted_at!=None, Application.submitted_at>=datetime.combine(today, datetime.min.time())).count()
    budget=max(0, settings.max_applications_per_day-submitted_today)
    jobs=s.query(Job).filter(Job.match_score>=settings.minimum_match_score, Job.status.in_(["qualified","application_draft"])).order_by(Job.match_score.desc()).limit(budget).all()
    p=get_profile(s); profile={c:getattr(p,c) for c in ["name","headline","email","location","skills","projects","experience","education","preferences"]}
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
    profile={c:getattr(p,c) for c in ["name","headline","email","location","skills","projects","experience","education","preferences"]}
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
    try: return await BrowserAutomation().inspect_apply_page(j.url)
    except Exception as e: raise HTTPException(400,str(e))

@app.post("/api/interviews/generate")
def interview(job_id:int,s:Session=Depends(db)):
    j=s.get(Job,job_id); p=get_profile(s)
    if not j: raise HTTPException(404,"Job not found")
    profile={c:getattr(p,c) for c in ["name","headline","skills","projects","experience","education"]}
    return json.loads(AIService().interview(profile,{"title":j.title,"company":j.company,"description":j.description}))

@app.post("/api/feedback")
def feedback(data:FeedbackIn,s:Session=Depends(db)):
    a=s.get(Application,data.application_id)
    if not a: raise HTTPException(404,"Application not found")
    s.add(Feedback(**data.model_dump())); a.status=data.outcome; s.commit(); return {"ok":True,"insight":outcome_insight(s.query(Feedback).all())}

@app.get("/api/followups")
def followups(s:Session=Depends(db)):
    now=datetime.utcnow(); rows=s.query(Application).filter(Application.follow_up_at!=None,Application.follow_up_at<=now).all()
    return [{"id":a.id,"job_id":a.job_id,"status":a.status,"follow_up_at":a.follow_up_at} for a in rows]
