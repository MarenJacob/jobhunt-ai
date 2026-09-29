"""Job discovery. Real job feeds first (structured, no guessing); web search only as a
filtered, page-verified extra. Everything returned is a single, open job posting."""
import asyncio, re, time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from ..config import settings
from . import jobfilter
from .matcher import STOP, TECH, required_years, tokens, _has

UA = {'User-Agent': 'JobHuntAI/2.0 (personal job search; contact via profile)'}
ATS_SEARCH_DOMAINS = ['boards.greenhouse.io', 'job-boards.greenhouse.io', 'jobs.lever.co', 'jobs.ashbyhq.com', 'apply.workable.com',
                      'jobs.smartrecruiters.com', 'weworkremotely.com', 'wellfound.com', 'remoteok.com', 'jobs.jobvite.com', 'careers.kula.ai']


@dataclass
class Candidate:
    title: str
    company: str
    url: str
    source: str
    location: str = ''
    description: str = ''
    remote: bool = False
    verified: bool = False
    tags: list = field(default_factory=list)


def _plain(html):
    return re.sub(r'\s+', ' ', BeautifulSoup(html or '', 'html.parser').get_text(' ')).strip()


def keywords_from_profile(profile):
    """Words that make a posting relevant: headline, skills, preferences (not generic filler)."""
    generic = STOP | {'remote', 'junior', 'graduate', 'new', 'grad', 'entry', 'level', 'nigeria', 'jos', 'and', 'developer', 'engineer', 'application'}
    bag = set()
    for txt in (profile.get('headline', ''), profile.get('skills', '')):
        bag |= {t for t in tokens(txt) if t not in generic and len(t) > 2}
    for t in TECH:
        if _has((profile.get('skills', '') + ' ' + profile.get('headline', '') + ' ' + profile.get('projects', '')).lower(), t):
            bag.add(t)
    role_words = {'developer', 'engineer', 'designer', 'analyst', 'product', 'software', 'web', 'frontend', 'backend', 'fullstack', 'full-stack', 'ai', 'data', 'ml', 'support'}
    return bag, role_words


def build_queries(profile):
    head = (profile.get('headline') or '').strip()
    skills = [x.strip() for x in re.split(r'[,\n;]', profile.get('skills') or '') if x.strip()][:4]
    base = re.sub(r'\s*&\s*', ' ', head) or 'software developer'
    qs = [f'{base} junior remote', 'graduate software developer remote', 'entry level ' + (skills[0] if skills else 'python') + ' developer remote']
    if 'ai' in (head + ' ' + ' '.join(skills)).lower():
        qs.append('junior AI engineer LLM remote')
    return list(dict.fromkeys(qs))[:4]


def relevant(c: Candidate, kw, role_words):
    hay_title = c.title.lower()
    blob = (' '.join([c.title, ' '.join(c.tags), c.description[:1500]])).lower()
    title_hit = bool(tokens(hay_title) & (kw | role_words))
    skill_hits = sum(1 for k in kw if _has(blob, k))
    return title_hit and skill_hits >= 1 or skill_hits >= 3


def hard_reject(c: Candidate):
    title = c.title.lower()
    for term in [t.strip().lower() for t in settings.blocked_role_terms.split(',') if t.strip()]:
        if _has(title, term):
            return f'Level too senior ("{term}")'
    yrs = required_years(c.description)
    if settings.max_required_years >= 0 and yrs > settings.max_required_years:
        return f'Requires {yrs}+ years of experience'
    return ''


# ---------- structured feeds ----------
_cache = {}


def clear_cache():
    _cache.clear()


async def _get_json(client, url, key=None, ttl=3 * 3600, **kw):
    now = time.time()
    if key and key in _cache and now - _cache[key][0] < ttl:
        return _cache[key][1]
    r = await client.get(url, headers=UA, timeout=25, follow_redirects=True, **kw)
    r.raise_for_status()
    data = r.json()
    if key: _cache[key] = (now, data)
    return data


async def fetch_remotive(client):
    d = await _get_json(client, 'https://remotive.com/api/remote-jobs', 'remotive')
    out = []
    for j in d.get('jobs', []):
        out.append(Candidate(j.get('title', ''), j.get('company_name', ''), j.get('url', ''), 'remotive.com', j.get('candidate_required_location', ''),
                             _plain(j.get('description', ''))[:8000], True, True, list(j.get('tags') or []) + [j.get('category', '')]))
    return out


async def fetch_remoteok(client):
    d = await _get_json(client, 'https://remoteok.com/api', 'remoteok')
    out = []
    for j in d if isinstance(d, list) else []:
        if not isinstance(j, dict) or not j.get('position'): continue
        u = j.get('url') or ''
        if u.startswith('/'): u = 'https://remoteok.com' + u
        out.append(Candidate(j.get('position', ''), j.get('company', ''), u, 'remoteok.com', j.get('location', '') or 'Remote',
                             _plain(j.get('description', ''))[:8000], True, True, list(j.get('tags') or [])))
    return out


async def fetch_arbeitnow(client):
    out = []
    for page in (1, 2):
        d = await _get_json(client, 'https://www.arbeitnow.com/api/job-board-api', f'arbeitnow{page}', params={'page': page})
        for j in d.get('data', []):
            if not j.get('remote'): continue
            out.append(Candidate(j.get('title', ''), j.get('company_name', ''), j.get('url', ''), 'arbeitnow.com', j.get('location', ''),
                                 _plain(j.get('description', ''))[:8000], True, True, list(j.get('tags') or [])))
    return out


async def fetch_board(client, kind, token):
    out = []
    if kind == 'greenhouse':
        d = await _get_json(client, f'https://boards-api.greenhouse.io/v1/boards/{token}/jobs', f'gh{token}', params={'content': 'true'})
        for j in d.get('jobs', []):
            loc = (j.get('location') or {}).get('name', '')
            out.append(Candidate(j.get('title', ''), jobfilter.pretty_company(token), j.get('absolute_url', ''), 'greenhouse.io', loc,
                                 _plain(_unescape(j.get('content', '')))[:8000], 'remote' in loc.lower(), True))
    elif kind == 'lever':
        d = await _get_json(client, f'https://api.lever.co/v0/postings/{token}', f'lv{token}', params={'mode': 'json'})
        for j in d if isinstance(d, list) else []:
            cat = j.get('categories') or {}
            out.append(Candidate(j.get('text', ''), jobfilter.pretty_company(token), j.get('hostedUrl', ''), 'lever.co', cat.get('location', ''),
                                 (j.get('descriptionPlain') or _plain(j.get('description', '')))[:8000], (j.get('workplaceType') == 'remote'), True))
    elif kind == 'ashby':
        d = await _get_json(client, f'https://api.ashbyhq.com/posting-api/job-board/{token}', f'ab{token}')
        for j in d.get('jobs', []):
            out.append(Candidate(j.get('title', ''), jobfilter.pretty_company(token), j.get('jobUrl', ''), 'ashbyhq.com', j.get('location', ''),
                                 (j.get('descriptionPlain') or _plain(j.get('descriptionHtml', '')))[:8000], bool(j.get('isRemote')), True))
    return out


def _unescape(s):
    import html
    return html.unescape(s or '')


# ---------- web search (filtered + verified) ----------
async def search_web(client, queries, report):
    if not settings.tavily_api_key:
        return []
    raw = []
    for q in queries:
        try:
            r = await client.post('https://api.tavily.com/search', timeout=35, json={
                'api_key': settings.tavily_api_key, 'query': q, 'search_depth': 'advanced', 'max_results': 15,
                'include_domains': ATS_SEARCH_DOMAINS, 'include_answer': False})
            r.raise_for_status()
            raw += r.json().get('results', [])
        except Exception as e:
            report['errors'].append(f'Web search "{q}": {str(e)[:120]}')
    seen, cands = set(), []
    for r in raw:
        url = r.get('url', '')
        if not url or url in seen: continue
        seen.add(url)
        verdict = jobfilter.classify(url, r.get('title', ''), r.get('content', ''))
        if not verdict['ok']:
            report['rejected'].append({'title': (r.get('title') or url)[:90], 'url': url, 'reason': verdict['reasons'][0] if verdict['reasons'] else 'Not a job posting'})
            continue
        company = jobfilter.company_from_url(url)
        title, company = jobfilter.clean_title(r.get('title', ''), company)
        cands.append(Candidate(title, company, url, jobfilter.source_host(url) if hasattr(jobfilter, 'source_host') else urlparse(url).netloc.replace('www.', ''),
                               '', r.get('content', ''), False, False))
    sem = asyncio.Semaphore(6)

    async def check(c):
        async with sem:
            jp, page_text, status = await jobfilter.verify_page(client, c.url)
        if status in (404, 410) or jobfilter.looks_expired(page_text):
            return c, 'Posting is closed or no longer available'
        if jp:
            if jp['expired']: return c, 'Posting has expired'
            c.title = jp['title'] or c.title; c.company = jp['company'] or c.company; c.location = jp['location'] or c.location
            c.description = jp['description'] or c.description; c.remote = jp['remote'] or c.remote; c.verified = True
            return c, ''
        v = jobfilter.classify(c.url, c.title, page_text)  # re-score using the whole page
        if not (v['ok'] or (v['strong'] and status == 0)):
            return c, v['reasons'][0] if v['reasons'] else 'Page is not a job posting'
        if page_text: c.description = page_text[:8000]
        c.verified = bool(v['strong'] and page_text)
        return c, ''

    kept = []
    for c, why in await asyncio.gather(*(check(c) for c in cands)):
        if why: report['rejected'].append({'title': c.title[:90], 'url': c.url, 'reason': why})
        else: kept.append(c)
    return kept


# ---------- orchestrator ----------
async def discover(profile: dict, known_urls: set, transport=None):
    """Returns (candidates, report). Candidates are unsaved, deduped, relevant, level-appropriate."""
    report = {'sources': {}, 'rejected': [], 'errors': [], 'queries': build_queries(profile)}
    kw, role_words = keywords_from_profile(profile)
    async with httpx.AsyncClient(transport=transport) as client:
        jobs = []
        feeds = {'remotive': fetch_remotive, 'remoteok': fetch_remoteok, 'arbeitnow': fetch_arbeitnow}
        wanted = [x.strip().lower() for x in settings.job_sources.split(',') if x.strip()]
        tasks, names = [], []
        for n in wanted:
            if n in feeds: tasks.append(feeds[n](client)); names.append(n)
        for spec in [x.strip() for x in settings.job_boards.split(',') if ':' in x]:
            kind, token = spec.split(':', 1)
            tasks.append(fetch_board(client, kind.strip().lower(), token.strip())); names.append(spec)
        for name, res in zip(names, await asyncio.gather(*tasks, return_exceptions=True)):
            if isinstance(res, Exception):
                report['sources'][name] = {'fetched': 0, 'error': str(res)[:120]}; report['errors'].append(f'{name}: {str(res)[:120]}')
            else:
                report['sources'][name] = {'fetched': len(res)}; jobs += res
        if settings.tavily_api_key:
            web = await search_web(client, report['queries'], report)
            report['sources']['web search'] = {'fetched': len(web)}; jobs += web
    out, seen = [], set()
    dropped = {'duplicate': 0, 'not_relevant': 0, 'level': 0}
    for c in jobs:
        if not c.url or not c.title or c.url in seen or c.url in known_urls:
            dropped['duplicate'] += 1; continue
        seen.add(c.url)
        why = hard_reject(c)
        if why:
            dropped['level'] += 1; report['rejected'].append({'title': c.title[:90], 'url': c.url, 'reason': why}); continue
        if not relevant(c, kw, role_words):
            dropped['not_relevant'] += 1; continue
        out.append(c)
    report['dropped'] = dropped
    report['rejected'] = report['rejected'][:25]
    return out, report
