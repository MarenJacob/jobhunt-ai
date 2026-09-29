"""Decide whether a web result is a real, single, open job posting.

The search engine happily returns blog posts, Wikipedia pages, salary guides and
"Top 10 jobs" listicles for a query like "AI engineer jobs". Those must never
enter the pipeline. This module scores a candidate from its URL, title and text,
and can verify it against the page's schema.org JobPosting markup.
"""
import json, re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

BLOCKED_HOSTS = (
    'wikipedia.org', 'wikihow.com', 'medium.com', 'quora.com', 'reddit.com', 'youtube.com', 'youtu.be', 'facebook.com',
    'instagram.com', 'x.com', 'twitter.com', 'tiktok.com', 'pinterest.com', 'substack.com', 'blogspot.com', 'wordpress.com',
    'dev.to', 'hashnode.dev', 'hashnode.com', 'towardsdatascience.com', 'geeksforgeeks.org', 'stackoverflow.com',
    'stackexchange.com', 'github.com', 'github.io', 'coursera.org', 'udemy.com', 'edx.org', 'simplilearn.com', 'w3schools.com',
    'forbes.com', 'businessinsider.com', 'investopedia.com', 'indeed.com/career-advice', 'glassdoor.com/blog',
    'linkedin.com/pulse', 'linkedin.com/posts', 'linkedin.com/in/', 'linkedin.com/company', 'linkedin.com/learning',
    'nerdwallet.com', 'britannica.com', 'ibm.com/think', 'techtarget.com', 'zety.com', 'novoresume.com', 'resume.io',
    'themuse.com/advice', 'careerfoundry.com', 'ziprecruiter.com/career', 'payscale.com', 'salary.com', 'levels.fyi',
    'naukri.com/blog', 'jobberman.com/blog', 'myjobmag.com/blog',
)

# (regex on "host/path", confidence) — a match means "this URL shape is one specific job".
ATS_JOB_URL = [
    r'greenhouse\.io/[^/]+/jobs/\d+', r'greenhouse\.io/embed/job_app\?', r'job-boards\.greenhouse\.io/[^/]+/jobs/\d+',
    r'jobs\.lever\.co/[^/]+/[0-9a-f-]{20,}', r'jobs\.ashbyhq\.com/[^/]+/[0-9a-f-]{20,}',
    r'smartrecruiters\.com/[^/]+/\d+', r'myworkdayjobs\.com/.+/job/', r'apply\.workable\.com/[^/]+/j/[A-Z0-9]+',
    r'workable\.com/j/[A-Z0-9]+', r'wellfound\.com/(company/[^/]+/)?jobs/\d+', r'weworkremotely\.com/remote-jobs/[^/]+',
    r'remotive\.com/remote-jobs/[^/]+/[^/]+-\d+', r'remoteok\.com/remote-jobs/', r'linkedin\.com/jobs/view/',
    r'indeed\.com/(viewjob|rc/clk)', r'bamboohr\.com/(careers|jobs)/(view\.php\?id=)?\d+', r'recruitee\.com/o/[^/]+',
    r'breezy\.hr/p/[0-9a-f]+', r'jobvite\.com/[^/]+/job/', r'icims\.com/jobs/\d+', r'teamtailor\.com/jobs/\d+',
    r'pinpointhq\.com/.+/postings/', r'personio\.(de|com)/job/', r'join\.com/companies/[^/]+/\d+',
    r'ziprecruiter\.com/c/[^/]+/job/', r'jobs\.jobvite\.com', r'careers\.kula\.ai', r'rippling\.com/.+/jobs/',
    r'arbeitnow\.com/jobs/', r'jobberman\.com/listings/', r'myjobmag\.com/job/',
]
GENERIC_JOB_PATH = re.compile(r'/(jobs?|careers?|positions?|openings?|vacanc(?:y|ies)|opportunit(?:y|ies)|roles?)/[^/?#]{6,}', re.I)
LISTING_URL = re.compile(r'(/jobs?[-_]in[-_]|/jobs/?\?|[?&](q|query|keywords?|search)=|/search|/category/|/categories/|/tag/|/tags/|/jobs/?$|/careers/?$|/blog/|/articles?/|/news/|/advice/|/guides?/|/resources?/|/salaries|/salary|/interview-questions)', re.I)

BAD_TITLE = re.compile(
    r"\b(how to|how do|what is|what are|why |guide|tips|tricks|best |top \d+|top ten|ultimate|roadmap|tutorial|course|bootcamp|certification|"
    r"salary|salaries|pay scale|interview questions|resume|r[ée]sum[ée] (tips|examples)|cover letter|career (advice|path|guide|change)|"
    r"ways to|things to|vs\.?|versus|explained|definition|overview|history of|trends|statistics|future of|is it worth|"
    r"\d+\s+(remote\s+|entry[- ]level\s+)?(jobs|roles|careers|positions)\b|jobs? in [A-Z]|hiring now:? \d+|job (market|outlook|search)|"
    r"blog|podcast|webinar|newsletter|review|ranking|list of)\b", re.I)
BLOG_TEXT = ('in this article', 'in this post', 'in this guide', 'read more', 'subscribe to our', 'posted by', 'leave a comment',
             'share this', 'table of contents', 'related posts', 'min read', 'written by', 'sign up for our newsletter', 'wikipedia',
             'according to the bureau', 'frequently asked questions')
JOB_TEXT = ('responsibilities', 'requirements', 'qualifications', 'we are looking for', "we're looking for", 'apply now', 'apply for this',
            'job description', 'about the role', "what you'll do", 'what you will do', 'about the job', 'benefits', 'full-time', 'full time',
            'part-time', 'contract', 'years of experience', 'salary range', 'equal opportunity', 'submit your application', 'how to apply',
            'you will be responsible', 'the role', 'your responsibilities', 'must have', 'nice to have')

ATS_HOST_RE = [(re.compile(p), n) for p, n in [
    (r'(?:job-boards(?:\.eu)?|boards(?:\.eu)?)\.greenhouse\.io/([^/?#]+)', 'greenhouse'),
    (r'jobs\.lever\.co/([^/?#]+)', 'lever'), (r'jobs\.ashbyhq\.com/([^/?#]+)', 'ashby'),
    (r'apply\.workable\.com/([^/?#]+)', 'workable'), (r'smartrecruiters\.com/([^/?#]+)', 'smartrecruiters'),
    (r'wellfound\.com/company/([^/?#]+)', 'wellfound'), (r'([a-z0-9-]+)\.bamboohr\.com', 'bamboohr'),
    (r'([a-z0-9-]+)\.recruitee\.com', 'recruitee'), (r'([a-z0-9-]+)\.breezy\.hr', 'breezy'),
    (r'([a-z0-9-]+)\.teamtailor\.com', 'teamtailor'), (r'([a-z0-9-]+)\.(?:wd\d+\.)?myworkdayjobs\.com', 'workday'),
    (r'jobs\.jobvite\.com/([^/?#]+)', 'jobvite'), (r'join\.com/companies/([^/?#]+)', 'join'),
]]


def _hostpath(url):
    p = urlparse(url)
    return (p.netloc.lower().replace('www.', '') + p.path + ('?' + p.query if p.query else '')).lower()


def pretty_company(slug):
    return re.sub(r'[-_]+', ' ', slug).strip().title() if slug else ''


def company_from_url(url):
    hp = _hostpath(url)
    for rx, _ in ATS_HOST_RE:
        m = rx.search(hp)
        if m:
            return pretty_company(m.group(1))
    return ''


def clean_title(title, company=''):
    t = re.sub(r'\s+', ' ', title or '').strip()
    m = re.match(r'^(?:Job Application for\s+)?(.+?)\s+at\s+(.+)$', t, re.I)
    if m and not company:
        t, company = m.group(1).strip(), m.group(2).strip()
    elif m:
        t = m.group(1).strip()
    t = re.sub(r'\s*[\-|–—·•]\s*(Greenhouse|Lever|Ashby|Workable|SmartRecruiters|LinkedIn|Indeed|Wellfound|We Work Remotely|Remotive|Remote OK|Careers?|Jobs?)\s*$', '', t, flags=re.I)
    if company:
        t = re.sub(r'\s*[\-|–—·•@]\s*' + re.escape(company) + r'\s*$', '', t, flags=re.I)
    return t.strip(' -|–—'), company


def classify(url, title='', text=''):
    """Return dict(ok, score, reasons, strong). ok=False means: do not store."""
    hp = _hostpath(url)
    reasons, score = [], 0
    if any(b in hp for b in BLOCKED_HOSTS):
        return {'ok': False, 'score': -99, 'strong': False, 'reasons': ['Article, wiki, forum or social page — not a job board']}
    strong = any(re.search(p, hp) for p in ATS_JOB_URL)
    if strong:
        score += 6; reasons.append('URL is a single job posting on a known job board')
    elif GENERIC_JOB_PATH.search(hp) and not LISTING_URL.search(hp):
        score += 3; reasons.append('URL looks like a careers/job page')
    if LISTING_URL.search(hp) and not strong:
        score -= 6; reasons.append('URL looks like a search, category or blog page')
    t = (title or '').strip()
    if BAD_TITLE.search(t) and not strong:
        score -= 6; reasons.append('Title reads like an article or guide')
    low = ' '.join([t, text or '']).lower()
    pos = sum(1 for k in JOB_TEXT if k in low)
    neg = sum(1 for k in BLOG_TEXT if k in low)
    if pos: score += min(pos, 4) * 1.5; reasons.append(f'{pos} job-posting phrases found')
    if neg: score -= min(neg, 3) * 2.5; reasons.append(f'{neg} blog/article phrases found')
    if not strong and pos < 2:
        score -= 3; reasons.append('Too little job-description language')
    return {'ok': score >= 4.5, 'score': round(score, 1), 'strong': strong, 'reasons': reasons}


def _flatten_ld(node):
    if isinstance(node, list):
        for x in node:
            yield from _flatten_ld(x)
    elif isinstance(node, dict):
        if '@graph' in node:
            yield from _flatten_ld(node['@graph'])
        yield node


def _txt(html):
    return re.sub(r'\s+', ' ', BeautifulSoup(html or '', 'html.parser').get_text(' ')).strip()


def parse_jobposting(html):
    """Extract a schema.org JobPosting from page HTML, or None."""
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(tag.string or tag.get_text() or '')
        except Exception:
            continue
        for n in _flatten_ld(data):
            typ = n.get('@type')
            if typ == 'JobPosting' or (isinstance(typ, list) and 'JobPosting' in typ):
                org = n.get('hiringOrganization') or {}
                loc = n.get('jobLocation') or {}
                if isinstance(loc, list) and loc: loc = loc[0]
                addr = (loc.get('address') or {}) if isinstance(loc, dict) else {}
                if isinstance(addr, str): place = addr
                else: place = ', '.join(x for x in [addr.get('addressLocality'), addr.get('addressRegion'), addr.get('addressCountry') if isinstance(addr.get('addressCountry'), str) else (addr.get('addressCountry') or {}).get('name', '')] if x)
                valid = n.get('validThrough') or ''
                expired = False
                try:
                    d = datetime.fromisoformat(str(valid).replace('Z', '+00:00'))
                    if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
                    expired = d < datetime.now(timezone.utc)
                except Exception:
                    pass
                return {'title': n.get('title', ''), 'company': org.get('name', '') if isinstance(org, dict) else str(org),
                        'location': place, 'description': _txt(n.get('description', ''))[:8000],
                        'remote': str(n.get('jobLocationType', '')).upper() == 'TELECOMMUTE', 'expired': expired,
                        'employment_type': n.get('employmentType', '')}
    return None


_HDR = {'User-Agent': 'Mozilla/5.0 (compatible; JobHuntAI/2.0; personal job search)', 'Accept': 'text/html,application/xhtml+xml'}


async def verify_page(client, url):
    """Fetch the page and return (jobposting_dict_or_None, page_text). Never raises."""
    try:
        r = await client.get(url, headers=_HDR, follow_redirects=True, timeout=12)
        if r.status_code >= 400:
            return None, '', r.status_code
        html = r.text
        jp = parse_jobposting(html)
        soup = BeautifulSoup(html, 'html.parser')
        for x in soup(['script', 'style', 'noscript', 'nav', 'footer']): x.decompose()
        return jp, ' '.join(soup.stripped_strings)[:20000], r.status_code
    except Exception:
        return None, '', 0


EXPIRED_TEXT = ('no longer accepting applications', 'this job is no longer available', 'position has been filled', 'job has expired',
                'this posting has expired', 'job not found', 'no longer available', 'this position is closed', 'the job you are looking for')


def looks_expired(text):
    low = (text or '')[:6000].lower()
    return any(k in low for k in EXPIRED_TEXT)
