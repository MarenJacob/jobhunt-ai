"""JobHunt AI browser worker (Playwright).

Runs separately from the web app (Railway/Fly/any Docker host). It opens a real
application page, reads the form, fills ONLY what the candidate profile truthfully
contains, and stops for a human on anything else (CAPTCHA, 2FA, login, legal
attestations, payment, unknown required questions). It never tries to bypass
anti-bot checks.
"""
import asyncio, base64, os, re, tempfile
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from playwright.async_api import async_playwright

app = FastAPI(title='JobHunt AI Browser Worker', version='2.0.0')
SECRET = os.getenv('BROWSER_WORKER_SECRET', '')
ALLOW = ['localhost']
PROFILE_DIR = os.getenv('BROWSER_PROFILE_DIR', '/tmp/browser-profile')
PERSIST = os.getenv('BROWSER_PERSIST', 'false').lower() == 'true'
HEADLESS = os.getenv('BROWSER_HEADLESS', 'true').lower() == 'true'
EXECUTABLE = os.getenv('BROWSER_EXECUTABLE', '') or None
RUN_LIMIT = int(os.getenv('WORKER_RUN_TIMEOUT', '110'))
LOW_MEMORY_ARGS = ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--disable-extensions',
                   '--disable-background-networking', '--mute-audio', '--no-first-run', '--js-flags=--max-old-space-size=256']
_lock = asyncio.Semaphore(int(os.getenv('WORKER_CONCURRENCY', '1')))  # free tiers: one browser at a time


class Execute(BaseModel):
    action: str = 'inspect'          # inspect | submit
    url: str
    profile: dict = Field(default_factory=dict)
    cover_letter: str = ''
    dry_run: bool = False            # fill the form on the real page, then stop before sending
    resume_base64: str = ''
    resume_filename: str = 'resume.pdf'


def allowed(url):
    h = (urlparse(url).hostname or '').lower().replace('www.', '')
    return any(h == d or h.endswith('.' + d) for d in ALLOW)


def auth(v):
    if SECRET and v != 'Bearer ' + SECRET:
        raise HTTPException(401, 'Unauthorized browser worker')


def normalize_url(url):
    """Send the browser straight to the application form where the ATS has a known apply URL."""
    u = urlparse(url); host = u.netloc.lower(); path = u.path.rstrip('/')
    if host.endswith('jobs.lever.co') and re.fullmatch(r'/[^/]+/[0-9a-f-]{20,}', path):
        return url.split('?')[0].rstrip('/') + '/apply'
    if host.endswith('jobs.ashbyhq.com') and re.fullmatch(r'/[^/]+/[0-9a-f-]{20,}', path):
        return url.split('?')[0].rstrip('/') + '/application'
    if host.endswith('apply.workable.com') and re.fullmatch(r'/[^/]+/j/[A-Z0-9]+', path):
        return url.split('?')[0].rstrip('/') + '/apply/'
    return url


# ------------------------------------------------------------------ reading the form
COLLECT_JS = r"""
() => {
  const out = []; let i = 0;
  const txt = n => ((n && (n.innerText || n.textContent)) || '').replace(/\s+/g, ' ').trim();
  const els = [...document.querySelectorAll('input, textarea, select')];
  for (const el of els) {
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (['hidden','submit','button','image','reset'].includes(type)) continue;
    const cs = getComputedStyle(el);
    const visible = !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length) && cs.visibility !== 'hidden' && cs.display !== 'none';
    if (!visible && type !== 'file') continue;
    let label = '';
    if (el.labels && el.labels.length && type !== 'radio' && type !== 'checkbox') label = [...el.labels].map(txt).join(' ');
    if (!label && el.getAttribute('aria-labelledby')) label = el.getAttribute('aria-labelledby').split(' ').map(id => txt(document.getElementById(id))).join(' ');
    if (!label) label = el.getAttribute('aria-label') || '';
    let group = '';
    const fs = el.closest('fieldset, [role=radiogroup], [role=group]');
    if (fs) { const lg = fs.querySelector('legend') || fs.querySelector('[class*=label], label'); group = fs.getAttribute('aria-label') || txt(lg); }
    if (!label && (type === 'radio' || type === 'checkbox')) label = group;
    if (!label) { const w = el.closest('label, [class*=field], [class*=question], [class*=form-group], li, div'); if (w) label = txt(w).slice(0, 160); }
    if (!label) label = el.getAttribute('placeholder') || '';
    let option = '';
    if (type === 'radio' || type === 'checkbox') option = (el.labels && el.labels.length) ? txt(el.labels[0]) : txt(el.parentElement).slice(0, 100);
    const required = !!el.required || el.getAttribute('aria-required') === 'true' || /\*\s*$/.test(label) || /\brequired\b/i.test(label);
    el.setAttribute('data-jh', String(i));
    out.push({ i, tag: el.tagName.toLowerCase(), type, name: el.getAttribute('name') || '', id: el.id || '', label: label.slice(0, 200), group: group.slice(0, 200),
      option: option.slice(0, 100), required, autocomplete: el.getAttribute('autocomplete') || '', placeholder: el.getAttribute('placeholder') || '',
      options: el.tagName === 'SELECT' ? [...el.options].map(o => ({ value: o.value, text: o.text.trim() })).filter(o => o.value !== '' && o.text) : [] });
    i++;
  }
  return out;
}
"""

SIGNALS_JS = r"""
() => {
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const body = (document.body.innerText || '').slice(0, 40000).toLowerCase();
  const captcha = [...document.querySelectorAll('iframe[src*="recaptcha/api2/anchor"], iframe[src*="hcaptcha.com"], iframe[src*="challenges.cloudflare.com"], .g-recaptcha, .h-captcha, .cf-turnstile')].some(vis)
                  || /verify you are human|i'?m not a robot|complete the security check|prove you are human/.test(body);
  const password = [...document.querySelectorAll('input[type=password]')].some(vis);
  const codeField = [...document.querySelectorAll('input')].some(e => vis(e) && /verification|security code|one[- ]time|otp|2fa/i.test((e.name||'') + (e.id||'') + (e.placeholder||'') + (e.getAttribute('aria-label')||'')));
  const loginText = /sign in to apply|log in to apply|login to apply|sign in to continue|create an account to apply/.test(body);
  const legal = ['i certify', 'i attest', 'under penalty of perjury', 'application fee', 'payment required', 'credit card', 'social security number'].filter(k => body.includes(k));
  const errors = [...document.querySelectorAll('[aria-invalid="true"], .error, .errors, .field-error, [class*="error-message"], [role=alert]')].filter(vis).map(e => (e.innerText||'').trim()).filter(Boolean).slice(0, 6);
  return { captcha, twofa: codeField, login: password || loginText, legal, errors, body: body.slice(0, 6000) };
}
"""

# ------------------------------------------------------------------ field meaning
RULES = [  # order matters: first match wins
    ('eeo', r'gender|\brace\b|ethnic|veteran|disabilit|hispanic|latino|sexual orientation|pronoun|transgender|demographic|self[- ]identif'),
    ('work_authorization', r'authori[sz]ed to work|work authori[sz]ation|legally (eligible|authori[sz]ed|permitted)|right to work|eligible to work|work permit|work visa status'),
    ('sponsorship', r'sponsor'),
    ('cover_letter', r'cover letter|letter of motivation|why (do you want|are you interested)'),
    ('resume', r'r[eé]sum[eé]|\bcv\b|curriculum vitae'),
    ('first_name', r'first\s*name|given\s*name|forename|preferred first'),
    ('last_name', r'last\s*name|surname|family\s*name'),
    ('email', r'e-?mail'),
    ('phone', r'phone|mobile|telephone|whatsapp|contact number'),
    ('linkedin', r'linkedin'),
    ('github', r'github'),
    ('website', r'website|portfolio|personal (site|url)|\burl\b|other link'),
    ('salary', r'salary|compensation|expected pay|pay expectation'),
    ('city', r'\bcity\b|\btown\b'),
    ('location', r'location|where are you (based|located)|current (city|country)|country|address'),
    ('full_name', r'^(your |full |legal |candidate )?name\b|full name|_systemfield_name|\bname\b'),
]


def classify_field(f):
    text = ' '.join([f.get('label', ''), f.get('group', ''), f.get('name', ''), f.get('id', ''), f.get('placeholder', ''), f.get('autocomplete', '')]).lower().replace('_', ' ')
    if f.get('type') == 'file':
        return 'cover_letter' if re.search(r'cover', text) else ('resume' if re.search(RULES_RESUME, text) or not re.search(r'other|additional|transcript|portfolio', text) else None)
    for key, rx in RULES:
        if re.search(rx, text):
            return key
    return None


RULES_RESUME = r'r[eé]sum[eé]|\bcv\b|curriculum|attach|upload|file'


def split_name(n):
    p = (n or '').split()
    return (p[0] if p else '', ' '.join(p[1:]))


def profile_value(profile, key, cover):
    first, last = split_name(profile.get('name', ''))
    loc = [x.strip() for x in re.split(r'[,|]', profile.get('location', '') or '') if x.strip()]
    vals = {'first_name': first, 'last_name': last, 'full_name': profile.get('name', ''), 'email': profile.get('email', ''), 'phone': profile.get('phone', ''),
            'linkedin': profile.get('linkedin', ''), 'github': profile.get('github', ''), 'website': profile.get('website', '') or profile.get('github', ''),
            'salary': profile.get('salary', ''), 'city': loc[0] if loc else '', 'location': profile.get('location', ''), 'cover_letter': cover,
            'work_authorization': profile.get('work_authorization', ''), 'sponsorship': profile.get('sponsorship', '')}
    return (vals.get(key) or '').strip()


def yes_no(value):
    v = value.strip().lower()
    if v.startswith(('yes', 'y', 'true', 'authori')): return 'yes'
    if v.startswith(('no', 'n', 'false', 'not')): return 'no'
    return ''


def pick_option(options, value, key):
    """Choose a <select> option that matches a truthful value. Returns option text or ''."""
    v = value.lower(); yn = yes_no(value) if key in ('work_authorization', 'sponsorship') else ''
    for o in options:
        t = o['text'].lower()
        if t == v or (yn and t.startswith(yn)) or (len(v) > 2 and (v in t or t in v)):
            return o['text']
    return ''


def decline_option(options):
    for o in options:
        if re.search(r"decline|prefer not|don'?t wish|do not wish|not to (say|answer|disclose)", o['text'].lower()):
            return o['text']
    return ''


def plan_fields(fields, profile, cover, has_resume):
    """Decide what to do with each control. Returns (plan, unresolved)."""
    plan, unresolved, seen_groups = [], [], set()
    for f in fields:
        key = classify_field(f); label = (f.get('group') or f.get('label') or f.get('name') or f.get('id') or 'field').strip()[:90]
        typ = f.get('type')
        if typ in ('radio', 'checkbox'):
            gname = f.get('name') or f.get('id')
            if typ == 'radio' and gname in seen_groups: continue
            if typ == 'radio': seen_groups.add(gname)
        item = {'i': f['i'], 'label': label, 'key': key, 'required': f['required'], 'field': f, 'action': 'skip', 'value': ''}
        if key == 'eeo':
            d = decline_option(f['options']) if f['tag'] == 'select' else ''
            if d: item.update(action='select', value=d)
            elif f['required']: unresolved.append(label + ' (demographic question)'); item['action'] = 'needs_you'
        elif typ == 'file':
            if key == 'resume' and has_resume: item.update(action='upload')
            elif key == 'resume' and f['required']: unresolved.append('Resume upload — no resume saved in your profile'); item['action'] = 'needs_you'
            elif f['required']: unresolved.append(label); item['action'] = 'needs_you'
        elif typ == 'checkbox':
            if f['required']: unresolved.append(label + ' (consent checkbox — you must tick this yourself)'); item['action'] = 'needs_you'
        else:
            value = profile_value(profile, key, cover) if key else ''
            if value:
                item.update(action='fill' if typ != 'radio' and f['tag'] != 'select' else ('radio' if typ == 'radio' else 'select'), value=value)
            elif f['required']:
                unresolved.append(label); item['action'] = 'needs_you'
        plan.append(item)
    return plan, unresolved


# ------------------------------------------------------------------ running
async def screenshot(page):
    try:
        b = await page.screenshot(type='jpeg', quality=45, full_page=False, timeout=8000)
        return base64.b64encode(b).decode('ascii')
    except Exception:
        return ''


MIN_FORM_FIELDS = 1  # a real application form has at least one field; emptiness is what disqualifies a page


async def has_submit(target):
    return await find_submit(target) is not None


async def find_form_frame(page):
    """The application form may be inside an embedded ATS iframe."""
    best, best_n = page, len(await page.evaluate(COLLECT_JS))
    if best_n >= MIN_FORM_FIELDS and (best_n >= 2 or await has_submit(page)):
        return best, best_n
    for fr in page.frames:
        if fr == page.main_frame or not re.search(r'greenhouse|lever|ashby|workable|smartrecruiters|bamboohr|recruitee|breezy|jobvite|teamtailor', fr.url or ''): continue
        try:
            n = len(await fr.evaluate(COLLECT_JS))
        except Exception:
            continue
        if n > best_n: best, best_n = fr, n
    return best, best_n


async def open_apply_form(page):
    """Some job pages show the form only after pressing Apply."""
    target, n = await find_form_frame(page)
    if n >= MIN_FORM_FIELDS and (n >= 2 or await has_submit(target)):
        return target, n
    for sel in ["a:has-text('Apply for this job')", "button:has-text('Apply for this job')", "a:has-text('Apply now')", "button:has-text('Apply now')", "a:has-text('Apply')", "button:has-text('Apply')"]:
        loc = page.locator(sel)
        try:
            if await loc.count() and await loc.first.is_visible():
                await loc.first.click(timeout=5000); await page.wait_for_timeout(1800); break
        except Exception:
            continue
    return await find_form_frame(page)


async def do_fill(target, page, plan, resume_file):
    filled, failed = [], []
    for it in plan:
        f = it['field']; a = it['action']
        if a not in ('fill', 'select', 'radio', 'upload'): continue
        loc = target.locator(f'[data-jh="{f["i"]}"]').first
        try:
            if a == 'upload':
                await loc.set_input_files(resume_file)
            elif a == 'fill':
                await loc.fill(it['value'], timeout=6000)
                if f['tag'] == 'input' and f['type'] not in ('email', 'tel', 'url', 'number') and (f.get('autocomplete') or '').startswith('address'):
                    pass
            elif a == 'select':
                text = it['value'] if it['key'] == 'eeo' else pick_option(f['options'], it['value'], it['key'])
                if not text: raise ValueError('no matching option')
                await loc.select_option(label=text, timeout=6000)
            elif a == 'radio':
                want = yes_no(it['value']); chosen = None
                for g in [x['field'] for x in plan if x['field'].get('name') == f.get('name') and x['field']['type'] == 'radio'] or [f]:
                    pass
                group = [x for x in plan_group(plan, f)]
                for g in group:
                    o = g['option'].lower()
                    if (want and o.startswith(want)) or (it['value'].lower() in o):
                        chosen = g; break
                if not chosen: raise ValueError('no matching option')
                await target.locator(f'[data-jh="{chosen["i"]}"]').first.check(timeout=6000)
            filled.append(it['label'])
        except Exception as e:
            failed.append(f"{it['label']} ({str(e)[:40]})")
    return filled, failed


_ALL_FIELDS = {}


def plan_group(plan, f):
    return _ALL_FIELDS.get(id(plan), {}).get(f.get('name'), [f])


async def find_submit(target):
    for sel in ["button[type='submit']", "input[type='submit']", "button:has-text('Submit application')", "button:has-text('Submit Application')", "button:has-text('Submit')", "button:has-text('Send application')"]:
        loc = target.locator(sel)
        for i in range(min(await loc.count(), 5)):
            b = loc.nth(i)
            try:
                if await b.is_visible() and await b.is_enabled(): return b
            except Exception:
                pass
    return None


def blocked(reason, **extra):
    return {'status': 'needs_human', 'submitted': False, 'reason': reason, **extra}


async def run_job(req: Execute):
    url = normalize_url(req.url)
    tmp = None
    async with async_playwright() as p:
        launch = dict(headless=HEADLESS, args=LOW_MEMORY_ARGS)
        if EXECUTABLE: launch['executable_path'] = EXECUTABLE
        if PERSIST:
            Path(PROFILE_DIR).mkdir(parents=True, exist_ok=True)
            ctx = await p.chromium.launch_persistent_context(PROFILE_DIR, **launch); browser = None
        else:
            browser = await p.chromium.launch(**launch)
            ctx = await browser.new_context(viewport={'width': 1200, 'height': 900}, locale='en-US')
        try:
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=45000)
                await page.wait_for_timeout(1500)
            except Exception as e:
                return blocked(f'Could not open the page: {str(e)[:120]}')
            target, n = await open_apply_form(page)
            sig = await target.evaluate(SIGNALS_JS)
            psig = await page.evaluate(SIGNALS_JS) if target != page else sig
            for k in ('captcha', 'twofa', 'login'): sig[k] = sig[k] or psig[k]
            sig['legal'] = sorted(set(sig['legal']) | set(psig['legal']))
            fields = await target.evaluate(COLLECT_JS)
            grouped = {}
            for f in fields:
                if f['type'] == 'radio': grouped.setdefault(f['name'], []).append(f)
            has_resume = bool(req.resume_base64)
            plan, unresolved = plan_fields(fields, req.profile, req.cover_letter, has_resume)
            _ALL_FIELDS[id(plan)] = grouped
            summary = [{'label': it['label'], 'kind': it['key'] or 'unknown', 'required': it['required'], 'action': it['action']} for it in plan]
            stops = []
            if sig['captcha']: stops.append('a CAPTCHA / human check is on the page')
            if sig['twofa']: stops.append('a verification-code (2FA) step')
            if sig['login']: stops.append('the site wants you to sign in or create an account first')
            if sig['legal']: stops.append('legal or payment text (' + ', '.join(sig['legal'][:3]) + ')')
            base = {'url': page.url, 'title': await page.title(), 'field_count': len(fields), 'fields': summary, 'stops': stops}
            if n < MIN_FORM_FIELDS or (n < 2 and not await has_submit(target)):
                return blocked('No application form found on this page (it may need a login or a different link).', **base, screenshot=await screenshot(page))
            if req.action == 'inspect':
                return {'status': 'inspected', 'submitted': False, 'ready_for_submission': not stops and not unresolved, 'unresolved': unresolved,
                        **base, 'screenshot': await screenshot(page)}
            if stops:
                return blocked('Stopped for you: ' + '; '.join(stops), **base, unresolved=unresolved, screenshot=await screenshot(page))
            resume_file = None
            if has_resume:
                suffix = Path(req.resume_filename).suffix or '.pdf'
                f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix); f.write(base64.b64decode(req.resume_base64)); f.close(); tmp = resume_file = f.name
            filled, failed = await do_fill(target, page, plan, resume_file)
            unresolved += [x for x in failed if any(it['label'] in x and it['required'] for it in plan)]
            await page.wait_for_timeout(500)
            if unresolved:
                return blocked('These required questions need your own answer: ' + '; '.join(unresolved[:12]), **base, filled=filled, unresolved=unresolved, screenshot=await screenshot(page))
            if req.dry_run:
                return {'status': 'dry_run', 'submitted': False, **base, 'filled': filled, 'unresolved': [], 'screenshot': await screenshot(page)}
            button = await find_submit(target)
            if not button:
                return blocked('No safe submit button found.', **base, filled=filled, screenshot=await screenshot(page))
            await button.click(timeout=8000)
            try:
                await page.wait_for_load_state('networkidle', timeout=9000)
            except Exception:
                pass
            await page.wait_for_timeout(1500)
            after = await (await find_form_frame(page))[0].evaluate(SIGNALS_JS) if not page.is_closed() else {'errors': [], 'captcha': False, 'body': ''}
            body = after.get('body', '') + ' ' + (await page.evaluate('()=>(document.body.innerText||"").slice(0,6000).toLowerCase()'))
            confirmed = next((k for k in ('application submitted', 'application received', 'thank you for applying', 'thanks for applying', 'application complete',
                                          'successfully submitted', 'we have received your application', 'your application has been') if k in body), '')
            if not confirmed and re.search(r'confirm|thank|success|submitted', page.url.lower()): confirmed = 'confirmation page'
            if after.get('captcha'):
                return blocked('A human check appeared after pressing submit. Finish it yourself on the employer page.', **base, filled=filled, screenshot=await screenshot(page))
            if after.get('errors') and not confirmed:
                return blocked('The employer form rejected the application: ' + '; '.join(after['errors'][:4]), **base, filled=filled, screenshot=await screenshot(page))
            if not confirmed:
                return blocked('I pressed submit but could not confirm it went through. Check the employer page before assuming it was sent.', **base, filled=filled, screenshot=await screenshot(page))
            return {'status': 'submitted', 'submitted': True, 'confirmation': confirmed, 'url': page.url, 'filled': filled, 'screenshot': await screenshot(page)}
        finally:
            _ALL_FIELDS.clear()
            if tmp and os.path.exists(tmp): os.unlink(tmp)
            await ctx.close()
            if browser: await browser.close()


@app.get('/health')
async def health():
    return {'status': 'ok', 'worker': 'playwright', 'allowed_domains': ALLOW, 'persistent_profile': PERSIST, 'busy': _lock.locked()}


@app.post('/execute')
async def execute(req: Execute, authorization: str | None = Header(default=None)):
    auth(authorization)
    if not allowed(req.url):
        raise HTTPException(403, 'URL is not on the browser worker allowlist')
    if _lock.locked():
        return blocked('The browser worker is busy with another application. Try again in a minute.')
    async with _lock:
        try:
            return await asyncio.wait_for(run_job(req), timeout=RUN_LIMIT)
        except asyncio.TimeoutError:
            return blocked(f'The page took longer than {RUN_LIMIT}s. Try again or apply manually.')
        except Exception as e:
            return blocked(f'Browser error: {str(e)[:160]}')
