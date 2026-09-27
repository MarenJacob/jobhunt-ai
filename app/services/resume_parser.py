import io, json, re
from pypdf import PdfReader
from docx import Document

def extract_text(filename,data):
    low=filename.lower()
    if low.endswith('.pdf'):
        reader=PdfReader(io.BytesIO(data)); return '\n'.join((p.extract_text() or '') for p in reader.pages)
    if low.endswith('.docx'):
        doc=Document(io.BytesIO(data)); return '\n'.join(p.text for p in doc.paragraphs)+ '\n' + '\n'.join(' | '.join(c.text for c in row.cells) for t in doc.tables for row in t.rows)
    raise ValueError('Unsupported resume format')

def _section(text,names):
    lines=text.splitlines(); start=None; end=len(lines)
    pats=[re.compile(r'^\s*(?:'+ '|'.join(re.escape(x) for x in names)+r')\s*$',re.I)]
    for i,l in enumerate(lines):
        if any(p.match(l.strip()) for p in pats): start=i+1; break
    if start is None:return ''
    headings={'professional summary','summary','profile','professional experience','experience','work experience','employment','education','projects','selected projects','technical skills','skills','core competencies','certifications','training'}
    for i in range(start,len(lines)):
        if lines[i].strip().lower() in headings and i>start: end=i; break
    return '\n'.join(lines[start:end]).strip()

def parse_resume(text,ai=None):
    clean=re.sub(r'\r','',text); lines=[x.strip() for x in clean.splitlines() if x.strip()]
    top='\n'.join(lines[:25])
    email=(re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',clean) or ["",""])[0]
    phone=(re.search(r'(?:\+?\d[\d ()-]{7,}\d)',clean) or ["",""])[0].strip()
    name=lines[0] if lines else ''
    # Prefer a likely all-name line before a title/summary line.
    for line in lines[:10]:
        if '@' in line or 'linkedin' in line.lower() or 'github' in line.lower(): continue
        words=line.split()
        if 2<=len(words)<=5 and not any(k in line.lower() for k in ['engineer','developer','specialist','resume','curriculum','ai ']): name=line; break
    profile={'name':name,'headline':'','email':email,'phone':phone,'location':'','skills':_section(clean,['technical skills','skills','core competencies']),'projects':_section(clean,['selected projects','selected ai & software projects','projects']),'experience':_section(clean,['professional experience','experience','work experience']),'education':_section(clean,['education','education & training']),'preferences':'','address':'','linkedin':'','github':'','website':''}
    m=re.search(r'(https?://(?:www\.)?linkedin\.com/[^\s|]+|linkedin\.com/[^\s|]+)',clean,re.I); profile['linkedin']=m.group(1) if m else ''
    m=re.search(r'(https?://(?:www\.)?github\.com/[^\s|]+|github\.com/[^\s|]+)',clean,re.I); profile['github']=m.group(1) if m else ''
    # AI enhancement is optional; deterministic extraction remains the fallback.
    if ai:
        try:
            raw=ai.generate_json('Parse this resume into JSON keys: name, headline, email, phone, location, address, linkedin, github, website, skills, projects, experience, education, preferences. Never invent data. Resume:\n'+clean[:24000])
            if isinstance(raw,dict): profile.update({k:v for k,v in raw.items() if k in profile and v})
        except Exception: pass
    return profile
