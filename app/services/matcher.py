import re
from dataclasses import dataclass, field

STOP = set('the and or for with from that this are you your our will have has into using use a an to of in on is be as at by we it not can all any more who what when where how their they them about role job work team company years year experience'.split())

TECH = ['python', 'javascript', 'typescript', 'java', 'php', 'sql', 'postgresql', 'mysql', 'mongodb', 'react', 'vue', 'angular', 'node', 'nodejs', 'django', 'flask',
        'fastapi', 'laravel', 'html', 'css', 'tailwind', 'docker', 'kubernetes', 'aws', 'azure', 'gcp', 'git', 'linux', 'rest', 'graphql', 'llm', 'openai', 'prompt engineering',
        'machine learning', 'deep learning', 'nlp', 'pytorch', 'tensorflow', 'langchain', 'rag', 'generative ai', 'ai agents', 'figma', 'ui', 'ux', 'product design',
        'branding', 'go', 'rust', 'c#', '.net', 'swift', 'kotlin', 'flutter', 'react native', 'android', 'ios', 'devops', 'ci/cd', 'terraform', 'data analysis', 'pandas',
        'excel', 'power bi', 'tableau', 'wordpress', 'seo', 'content', 'marketing', 'sales', 'customer support', 'product management', 'agile', 'scrum']

ENTRY = ['junior', 'graduate', 'entry level', 'entry-level', 'intern', 'internship', 'trainee', 'associate', 'apprentice', 'new grad', 'early career', 'no experience', '0-2 years', '0-1 years', '1-2 years', 'fresh']
SENIOR = ['senior', 'sr.', 'staff', 'principal', 'lead', 'director', 'head of', 'vp ', 'vice president', 'manager', 'architect', 'chief']
OPEN_LOC = ['remote', 'worldwide', 'anywhere', 'work from anywhere', 'africa', 'nigeria', 'emea', 'global', 'distributed', 'fully remote']
RESTRICT_LOC = ['us only', 'u.s. only', 'united states only', 'usa only', 'must be located in the us', 'must reside in', 'us residents', 'u.s. residents', 'canada only',
                'uk only', 'eu only', 'europe only', 'must be authorized to work in the united states', 'us citizens', 'us-based', 'u.s.-based', 'north america only', 'within the us']


@dataclass
class MatchResult:
    score: float
    matched: list
    gaps: list
    rationale: str
    flags: dict = field(default_factory=dict)


def tokens(text: str):
    return {x for x in re.findall(r"[a-zA-Z0-9+#.]{2,}", (text or '').lower()) if x not in STOP}


def _has(text, term):
    return re.search(r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])', text) is not None


def skill_list(profile_text):
    parts = [p.strip().lower() for p in re.split(r'[,\n;|/•]+', profile_text or '') if 1 < len(p.strip()) <= 32]
    return list(dict.fromkeys(parts))


def required_years(text):
    found = [int(x) for x in re.findall(r'(\d{1,2})\s*\+?\s*(?:-\s*\d+\s*)?(?:years?|yrs?)\s+(?:of\s+)?(?:relevant\s+|professional\s+|hands-on\s+|commercial\s+)?(?:experience|exp)', (text or '').lower())]
    return max(found) if found else 0


def match_job(job_text: str, profile_text: str, preferences: str = '', title: str = '', headline: str = '', location: str = '') -> MatchResult:
    jt_low = (job_text or '').lower()
    title_low = (title or jt_low[:120]).lower()
    prof_low = (profile_text or '').lower()
    skills = skill_list(profile_text)
    tech_in_profile = [t for t in TECH if _has(prof_low, t)]
    known = list(dict.fromkeys(skills + tech_in_profile))
    matched = [k for k in known if _has(jt_low, k)]
    denom = max(4, min(len(known), 10))
    skill_part = min(1.0, len(matched) / denom) * 50
    # title/role alignment
    role_tokens = tokens(headline) - {'and', 'application', 'developer'} | tokens(headline)
    ttoks = tokens(title_low)
    title_hits = len(role_tokens & ttoks)
    title_part = min(1.0, title_hits / max(1, min(len(role_tokens), 3))) * 20 if role_tokens else 8
    score = 12 + skill_part + title_part
    flags = {}
    if any(_has(jt_low, e) or e in title_low for e in ENTRY):
        score += 10; flags['entry_level'] = True
    if any(_has(title_low, s.strip()) for s in SENIOR):
        score -= 30; flags['senior_title'] = True
    yrs = required_years(jt_low)
    flags['required_years'] = yrs
    if yrs >= 5: score -= 30
    elif yrs >= 3: score -= 15
    loc_low = (location or '').lower()
    if any(o in jt_low[:3000] or o in loc_low for o in OPEN_LOC):
        score += 8; flags['open_location'] = True
    if any(r in jt_low or r in loc_low for r in RESTRICT_LOC) and 'nigeria' not in jt_low and 'africa' not in jt_low:
        score -= 25; flags['location_restricted'] = True
    tech_in_job = [t for t in TECH if _has(jt_low, t)]
    gaps = [t for t in tech_in_job if t not in known][:10]
    score = round(max(0, min(97, score)), 1)
    bits = []
    if matched: bits.append(f"Matches {len(matched)} of your skills ({', '.join(matched[:5])}).")
    else: bits.append('None of your listed skills appear in this posting.')
    if flags.get('entry_level'): bits.append('Entry-level friendly.')
    if flags.get('senior_title'): bits.append('Senior-level title.')
    if yrs >= 3: bits.append(f'Asks for {yrs}+ years of experience.')
    if flags.get('location_restricted'): bits.append('Location looks restricted to another country.')
    elif flags.get('open_location'): bits.append('Open to remote / your region.')
    if gaps: bits.append(f"Not in your profile: {', '.join(gaps[:4])}.")
    return MatchResult(score, matched[:30], gaps, ' '.join(bits), flags)
