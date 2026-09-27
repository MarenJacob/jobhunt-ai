import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta
from .browser import BrowserAutomation, SubmissionBlocked
from ..config import settings

class SubmissionService:
    def __init__(self, db): self.db=db; self.browser=BrowserAutomation()
    def policy(self,job,profile):
        reasons=[]; title=(job.title or '').lower()
        if any(x.strip() and x.strip() in title for x in settings.blocked_role_terms.split(',')): reasons.append('blocked_role_term')
        if job.match_score < settings.minimum_match_score: reasons.append('match_score_below_threshold')
        if not self.browser.allowed(job.url): reasons.append('domain_not_allowed')
        import re
        years=[int(x) for x in re.findall(r'(\d+)\+?\s+years?',(job.description or '').lower())]
        if settings.max_required_years >= 0 and years and max(years)>settings.max_required_years: reasons.append('experience_requirement_too_high')
        return {'allowed':not reasons,'reasons':reasons}
    async def submit_application(self,application,job,profile,dry_run=False):
        policy=self.policy(job,profile)
        if not policy['allowed']: raise SubmissionBlocked('Policy blocked submission: '+', '.join(policy['reasons']))
        p=self.db.get(__import__('app.models',fromlist=['Profile']).Profile,1)
        resume_bytes=getattr(p,'resume_blob',None) if p else None
        resume_filename=getattr(p,'resume_filename','resume.pdf') if p else 'resume.pdf'
        result=await self.browser.submit(job.url,profile,settings.resume_path,resume_bytes,resume_filename,application.cover_letter,dry_run=dry_run)
        if result.get('submitted'):
            application.status='submitted'; application.submitted_at=datetime.utcnow(); application.follow_up_at=datetime.utcnow()+timedelta(days=settings.follow_up_days)
        return {'policy':policy,'result':result}
    def send_email(self,to,subject,body,resume_path=''):
        if not settings.smtp_host or not settings.smtp_user: raise RuntimeError('SMTP is not configured')
        msg=EmailMessage(); msg['From']=settings.smtp_user; msg['To']=to; msg['Subject']=subject; msg.set_content(body)
        if resume_path:
            with open(resume_path,'rb') as f: msg.add_attachment(f.read(),maintype='application',subtype='pdf',filename='resume.pdf')
        with smtplib.SMTP(settings.smtp_host,settings.smtp_port,timeout=30) as smtp:
            smtp.starttls(); smtp.login(settings.smtp_user,settings.smtp_password); smtp.send_message(msg)
        return {'sent':True,'sent_at':datetime.utcnow().isoformat()}
