import base64, os, tempfile
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from playwright.async_api import async_playwright

app=FastAPI(title='JobHunt AI Browser Worker', version='1.0.0')
SECRET=os.getenv('BROWSER_WORKER_SECRET','')
PROFILE_DIR=os.getenv('BROWSER_PROFILE_DIR','/data/browser-profile')
ALLOW=[x.strip().lower() for x in os.getenv('ALLOWED_DOMAINS','greenhouse.io,lever.co,ashbyhq.com,smartrecruiters.com,workday.com,myworkdayjobs.com').split(',') if x.strip()]

class Execute(BaseModel):
    action: str='inspect'
    url: str
    profile: dict = Field(default_factory=dict)
    cover_letter: str=''
    dry_run: bool=False
    resume_base64: str=''
    resume_filename: str='resume.pdf'

def allowed(url):
    h=urlparse(url).netloc.lower().split(':')[0].replace('www.','')
    return any(h==d or h.endswith('.'+d) for d in ALLOW)

def auth(v):
    if SECRET and v != 'Bearer '+SECRET: raise HTTPException(401,'Unauthorized browser worker')

async def inspect(page):
    body=(await page.locator('body').inner_text())[:30000].lower()
    blocked=[x for x in ('captcha','recaptcha','verify you are human','two-factor','2fa','security code') if x in body]
    login=any(x in body for x in ('sign in to apply','log in to apply','login to apply','sign in to continue'))
    controls=page.locator("input, textarea, select, [role='combobox'], [contenteditable='true']")
    fields=[]
    for i in range(min(await controls.count(),250)):
        e=controls.nth(i)
        fields.append({'index':i,'tag':await e.evaluate('el=>el.tagName.toLowerCase()'),'type':await e.get_attribute('type'),'name':await e.get_attribute('name'),'id':await e.get_attribute('id'),'label':await e.get_attribute('aria-label'),'placeholder':await e.get_attribute('placeholder'),'autocomplete':await e.get_attribute('autocomplete'),'required':await e.get_attribute('required') is not None})
    return {'url':page.url,'title':await page.title(),'fields':fields,'blocked_signals':blocked,'login_required':login,'ready_for_submission':not blocked and not login}

ALIASES={'first_name':['first name','firstname','given name'],'last_name':['last name','lastname','surname'],'email':['email','e-mail'],'phone':['phone','mobile','telephone'],'address':['address','street'],'city':['city','town'],'state':['state','province','region'],'country':['country'],'linkedin':['linkedin'],'github':['github'],'website':['website','portfolio'],'resume':['resume','cv','curriculum vitae'],'cover_letter':['cover letter','additional information'],'education':['education','school','university'],'degree':['degree'],'work_authorization':['work authorization','authorized to work'],'sponsorship':['sponsorship','visa sponsorship']}
def canonical(f):
 t=' '.join(str(f.get(k) or '') for k in ('label','name','id','placeholder','autocomplete')).lower().replace('_',' ')
 for k,vals in ALIASES.items():
  if any(v in t for v in vals): return k
 return None

def split_name(n):
 p=(n or '').split(); return (p[0] if p else '', ' '.join(p[1:]))
def split_loc(v):
 p=[x.strip() for x in (v or '').replace('|',',').split(',') if x.strip()]; return {'city':p[0] if p else '', 'state':p[1] if len(p)>2 else '', 'country':p[-1] if len(p)>1 else (p[0] if p else '')}
def val(profile,key,cover):
 f,l=split_name(profile.get('name','')); loc=split_loc(profile.get('location',''))
 return {'first_name':f,'last_name':l,'email':profile.get('email',''),'phone':profile.get('phone',''),'address':profile.get('address',''),'city':loc['city'],'state':loc['state'],'country':loc['country'],'linkedin':profile.get('linkedin',''),'github':profile.get('github',''),'website':profile.get('website',''),'education':profile.get('education',''),'degree':profile.get('degree',''),'cover_letter':cover or '','work_authorization':profile.get('work_authorization',''),'sponsorship':profile.get('sponsorship','')}.get(key,'')

@app.get('/health')
async def health(): return {'status':'ok','worker':'playwright','profile_dir':PROFILE_DIR}

@app.post('/execute')
async def execute(req:Execute, authorization: str|None=Header(default=None)):
    auth(authorization)
    if not allowed(req.url): raise HTTPException(403,'URL is not on the browser worker allowlist')
    Path(PROFILE_DIR).mkdir(parents=True,exist_ok=True)
    tmp=None
    async with async_playwright() as p:
        context=await p.chromium.launch_persistent_context(PROFILE_DIR,headless=os.getenv('BROWSER_HEADLESS','true').lower()=='true')
        page=await context.new_page()
        try:
            await page.goto(req.url,wait_until='domcontentloaded',timeout=60000); await page.wait_for_timeout(1200)
            info=await inspect(page)
            if req.action=='inspect' or req.dry_run:
                return info if req.action=='inspect' else {'submitted':False,'dry_run':True,'page':info}
            if info['blocked_signals']: raise HTTPException(409,'Human action required: '+', '.join(info['blocked_signals']))
            if info['login_required']: raise HTTPException(409,'Login required. Authenticate the persistent browser session, then retry.')
            controls=page.locator("input, textarea, select, [role='combobox'], [contenteditable='true']")
            unresolved=[]; filled=[]
            resume_file=None
            if req.resume_base64:
                suffix=Path(req.resume_filename).suffix or '.pdf'; f=tempfile.NamedTemporaryFile(delete=False,suffix=suffix); f.write(base64.b64decode(req.resume_base64)); f.close(); resume_file=f.name
            for f in info['fields']:
                key=canonical(f); value=val(req.profile,key,req.cover_letter) if key else ''
                if key=='resume' and f.get('type')=='file':
                    if resume_file: await controls.nth(f['index']).set_input_files(resume_file); filled.append(key)
                    elif f.get('required'): unresolved.append(f.get('label') or f.get('name') or 'Resume')
                    continue
                if not value:
                    if f.get('required') and key not in ('work_authorization','sponsorship'): unresolved.append(f.get('label') or f.get('name') or f.get('id') or 'required field')
                    continue
                e=controls.nth(f['index'])
                try:
                    if f.get('tag')=='select': await e.select_option(label=value)
                    elif f.get('type') in ('checkbox','radio'):
                        continue
                    else: await e.fill(value)
                    filled.append(key)
                except Exception:
                    if f.get('required'): unresolved.append(f.get('label') or f.get('name') or 'required field')
            body=(await page.locator('body').inner_text()).lower()
            for risk in ('i certify','i attest','application fee','payment required','credit card','work authorization'):
                if risk in body: raise HTTPException(409,'Human review required for legal/work-authorization/payment content')
            if unresolved: raise HTTPException(409,'Required fields need human input: '+', '.join(unresolved[:20]))
            buttons=page.locator("button[type='submit'],input[type='submit'],button:has-text('Submit application'),button:has-text('Submit'),button:has-text('Apply')")
            button=None
            for i in range(min(await buttons.count(),5)):
                b=buttons.nth(i)
                if await b.is_visible() and await b.is_enabled(): button=b; break
            if not button: raise HTTPException(409,'No safe submit button detected')
            await button.click(); await page.wait_for_timeout(1800)
            body=(await page.locator('body').inner_text())[:12000].lower()
            confirmation=next((x for x in ('application submitted','application received','thank you for applying','thanks for applying','application complete') if x in body),'page changed after submission')
            return {'submitted':True,'url':page.url,'filled':filled,'confirmation':confirmation}
        finally:
            if tmp and os.path.exists(tmp): os.unlink(tmp)
            await context.close()
