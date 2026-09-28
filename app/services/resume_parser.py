import io, re
from pypdf import PdfReader
from docx import Document

# ---------------------------------------------------------------- extraction

def _docx_text(data):
    """Read DOCX paragraphs AND tables in document order (two-column templates
    keep their content in tables), without repeating merged cells."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    doc = Document(io.BytesIO(data))
    out = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit('}', 1)[-1]
        if tag == 'p':
            out.append(Paragraph(child, doc).text)
        elif tag == 'tbl':
            for row in Table(child, doc).rows:
                seen = []
                for cell in row.cells:
                    if cell._tc in seen:
                        continue
                    seen.append(cell._tc)
                    out.extend(p.text for p in cell.paragraphs)
    return '\n'.join(out)


def extract_text(filename, data):
    low = filename.lower()
    if low.endswith('.pdf'):
        reader = PdfReader(io.BytesIO(data))
        return '\n'.join((p.extract_text() or '') for p in reader.pages)
    if low.endswith('.docx'):
        return _docx_text(data)
    raise ValueError('Unsupported resume format')

# ---------------------------------------------------------------- sections

SECTION_ALIASES = {
    'summary': ['summary', 'professional summary', 'profile', 'personal profile', 'career objective', 'objective', 'about me', 'about', 'personal statement', 'career summary'],
    'skills': ['skills', 'technical skills', 'key skills', 'core skills', 'core competencies', 'competencies', 'skills & tools', 'tools & technologies', 'technologies', 'tech stack', 'areas of expertise', 'expertise', 'skills & interests'],
    'projects': ['projects', 'selected projects', 'personal projects', 'key projects', 'academic projects', 'selected ai & software projects', 'portfolio', 'project experience', 'notable projects'],
    'experience': ['experience', 'work experience', 'professional experience', 'employment', 'employment history', 'work history', 'career history', 'internship', 'internships', 'internship experience', 'industrial training', 'volunteer experience', 'leadership experience', 'relevant experience'],
    'education': ['education', 'education & training', 'academic background', 'academic qualifications', 'educational background', 'qualifications', 'academic history', 'education & certifications'],
    'other': ['certifications', 'certification', 'certificates', 'training', 'courses', 'languages', 'interests', 'hobbies', 'references', 'referees', 'awards', 'achievements', 'honors', 'publications', 'activities', 'contact', 'contact information', 'personal details', 'personal information', 'links', 'declaration', 'additional information'],
}
_ALIAS_TO_KEY = {a: k for k, v in SECTION_ALIASES.items() for a in v}


def _heading_key(line):
    raw = line.strip()
    if not raw or len(raw) > 45 or len(raw.split()) > 6:
        return None
    s = re.sub(r'\s+', ' ', raw.strip(':').strip('-–—_|•*#').strip()).lower().replace(' and ', ' & ')
    return _ALIAS_TO_KEY.get(s)


def split_sections(text):
    """Split into canonical sections. EVERY known heading (including ones we do
    not store, e.g. Languages/References) closes the previous section, so text
    can never leak from one field into another."""
    sections = {'header': []}
    current = 'header'
    for line in text.replace('\r', '').splitlines():
        key = _heading_key(line)
        if key:
            current = key
            sections.setdefault(current, [])
            continue
        m = re.match(r'^\s*([A-Za-z &]{3,30})\s*[:\-–]\s*(.+)$', line)  # "Skills: Python, SQL"
        if m and _heading_key(m.group(1)) in ('skills', 'summary') and len(m.group(2)) > 3:
            sections.setdefault(_heading_key(m.group(1)), []).append(m.group(2))
            continue
        sections.setdefault(current, []).append(line)
    return {k: '\n'.join(l for l in v if l.strip()).strip() for k, v in sections.items()}


def _clean_bullets(txt):
    lines = [re.sub(r'^[\s•·▪●■◦\-–*>]+', '', l).strip() for l in (txt or '').splitlines()]
    return '\n'.join(l for l in lines if l)

# ---------------------------------------------------------------- contact

_NAME_STOP = ('resume', 'curriculum', 'vitae', 'engineer', 'developer', 'specialist', 'designer', 'manager', 'analyst', 'intern', 'graduate', 'student', 'contact', 'profile', 'summary')


def _find_email(t):
    m = re.search(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', t)
    return m.group(0) if m else ''


def _find_phone(t):
    for m in re.finditer(r'(?<![\w/])(\+?\d[\d\s().-]{8,17}\d)(?![\w/])', t):
        digits = re.sub(r'\D', '', m.group(1))
        if 10 <= len(digits) <= 14 and not re.search(r'(19|20)\d{2}\s*[-–]\s*(19|20)\d{2}', m.group(1)):
            return m.group(1).strip()
    return ''


def _find_links(t):
    def grab(pat):
        m = re.search(pat, t, re.I)
        return m.group(0).rstrip('.,;)') if m else ''
    return (grab(r'(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/[^\s|,;]+'),
            grab(r'(?:https?://)?(?:www\.)?github\.com/[^\s|,;]+'))


def _find_website(t):
    for m in re.finditer(r'https?://[^\s|,;)]+', t, re.I):
        u = m.group(0).rstrip('.')
        if not re.search(r'linkedin\.com|github\.com', u, re.I):
            return u
    return ''


def _find_name(lines):
    for line in lines[:12]:
        l = line.strip(); low = l.lower()
        if not l or '@' in l or re.search(r'\d', l) or 'http' in low or 'linkedin' in low or 'github' in low:
            continue
        words = re.findall(r"[A-Za-z][A-Za-z'.-]*", l)
        if not 2 <= len(words) <= 4 or len(words) != len(l.split()) or any(s in low for s in _NAME_STOP):
            continue
        return ' '.join(w.capitalize() if w.isupper() else w for w in words)
    return ''


_ROLE_WORDS = ('engineer', 'developer', 'designer', 'specialist', 'analyst', 'manager', 'graduate', 'student', 'scientist', 'consultant', 'intern', 'architect', 'writer', 'product', 'ai ', 'software')


def _find_headline(lines):
    for line in lines[:12]:
        l = line.strip()
        if '@' in l or 'http' in l.lower() or len(l) > 90 or re.search(r'\d{5,}', l):
            continue
        if any(s in l.lower() + ' ' for s in _ROLE_WORDS):
            return l
    return ''


def _find_location(lines, full_text):
    m = re.search(r'(?:location|address|city)\s*[:\-]\s*(.+)', full_text[:1500], re.I)
    if m:
        return m.group(1).strip()[:120]
    for line in lines[:12]:
        for part in re.split(r'[|•·]', line):
            p = part.strip()
            if not p or len(p) > 60 or re.search(r'@|http|\d{6,}', p):
                continue
            if re.match(r"^[A-Z][A-Za-z .'-]+,\s*[A-Z][A-Za-z .'-]+$", p) or re.search(r'\b(nigeria|jos|lagos|abuja|plateau)\b', p, re.I):
                return p
    return ''

# ---------------------------------------------------------------- AI merge

_FIELDS = ['name', 'headline', 'email', 'phone', 'location', 'address', 'linkedin', 'github', 'website', 'skills', 'projects', 'experience', 'education', 'preferences']
_LONG = ['skills', 'projects', 'experience', 'education']


def _as_text(v):
    if v is None:
        return ''
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (list, tuple)):
        return '\n'.join(x for x in (_as_text(i) for i in v) if x)
    if isinstance(v, dict):
        return '\n'.join(f'{k}: {_as_text(x)}' for k, x in v.items() if _as_text(x))
    return str(v).strip()


def _tokens(s):
    return set(re.findall(r'[a-z0-9+#.]{3,}', s.lower()))


def _overlap(a, b):
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / max(1, min(len(ta), len(tb)))


def _merge_ai(profile, raw, resume_text):
    """Accept AI values only when grounded in the resume and not a copy of another field."""
    if not isinstance(raw, dict):
        return profile
    ai = {k: _as_text(raw.get(k)) for k in _FIELDS}
    src = _tokens(resume_text)
    for k in _FIELDS:
        v = ai[k]
        t = _tokens(v)
        if not v or not t or len(t & src) / len(t) < 0.8:
            continue  # empty or not found in the resume -> ignore (no invented data)
        if k in ('email', 'phone', 'linkedin', 'github') and profile[k]:
            continue  # regex is more reliable for identifiers
        if k in _LONG:
            if len(t) > 3 and any(o != k and ai[o] and _overlap(v, ai[o]) > 0.9 for o in _LONG):
                continue  # same text returned for two different fields
            if profile[k] and len(v) < 0.4 * len(profile[k]):
                continue  # AI truncated content we captured fully
        profile[k] = v
    return profile


AI_PROMPT = (
    'Parse this resume into ONE JSON object with string values and these keys: name, headline, email, phone, location, address, '
    'linkedin, github, website, skills, projects, experience, education, preferences.\n'
    'Rules: skills = only skills/tools/technologies as a comma-separated list. education = ONLY schools, degrees, grades and dates. '
    'experience = ONLY jobs/internships with dates and bullets. projects = ONLY projects. '
    'Never put content of one section into another. Copy wording from the resume; never invent data; use "" if absent. '
    'Return raw JSON only, no markdown fences.\n\nResume:\n'
)


def parse_resume(text, ai=None):
    clean = re.sub(r'[ \t]+', ' ', text.replace('\r', ''))
    sec = split_sections(clean)
    header = [l for l in sec.get('header', '').splitlines() if l.strip()] or [l for l in clean.splitlines() if l.strip()][:12]
    top = '\n'.join(header[:15]) + '\n' + sec.get('other', '')[:600]
    linkedin, github = _find_links(clean)
    name = _find_name(header) or _find_name([l for l in clean.splitlines() if l.strip()])
    headline = _find_headline([l for l in header if name.lower() not in l.lower()] if name else header)
    if not headline and sec.get('summary'):
        first = re.split(r'(?<=[.!?])\s', sec['summary'])[0]
        headline = first if len(first) <= 90 else ''
    profile = {
        'name': name, 'headline': headline, 'email': _find_email(clean),
        'phone': _find_phone(top) or _find_phone(clean), 'location': _find_location(header, clean),
        'address': '', 'linkedin': linkedin, 'github': github, 'website': _find_website(clean),
        'skills': _clean_bullets(sec.get('skills', '')), 'projects': sec.get('projects', ''),
        'experience': sec.get('experience', ''), 'education': sec.get('education', ''), 'preferences': '',
    }
    if ai:
        try:
            profile = _merge_ai(profile, ai.generate_json(AI_PROMPT + clean[:24000]), clean)
        except Exception:
            pass
    return profile
