import re
from urllib.parse import urlparse
from datetime import datetime

ATS_HOSTS = {
    'workday': ('myworkdayjobs.com','workday.com'),
    'greenhouse': ('greenhouse.io','boards.greenhouse.io'),
    'lever': ('lever.co','jobs.lever.co'),
    'ashby': ('ashbyhq.com','jobs.ashbyhq.com'),
    'smartrecruiters': ('smartrecruiters.com',),
}

FIELD_ALIASES = {
    'first_name': ['first name','firstname','given name'],
    'last_name': ['last name','lastname','surname','family name'],
    'email': ['email','email address'],
    'phone': ['phone','phone number','mobile','telephone'],
    'address': ['address','street address'],
    'city': ['city','town'],
    'state': ['state','province','region'],
    'postal_code': ['zip','zip code','postal code'],
    'country': ['country','country of residence'],
    'linkedin': ['linkedin','linkedin url','linkedin profile'],
    'github': ['github','github url','github profile'],
    'website': ['website','portfolio','personal website'],
    'education': ['education','school','university','college'],
    'degree': ['degree','qualification'],
    'resume': ['resume','cv','curriculum vitae'],
    'cover_letter': ['cover letter','coverletter'],
    'work_authorization': ['work authorization','authorized to work','legally authorized'],
    'sponsorship': ['sponsorship','visa sponsorship','require sponsorship'],
}

def detect_platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for name, domains in ATS_HOSTS.items():
        if any(d in host for d in domains):
            return name
    return 'generic'

def split_name(name: str):
    parts = (name or '').strip().split()
    return (parts[0] if parts else '', ' '.join(parts[1:]) if len(parts)>1 else '')

def split_location(location: str):
    raw=(location or '').strip()
    parts=[p.strip() for p in re.split(r'[,|]',raw) if p.strip()]
    return {'city':parts[0] if parts else raw,'state':parts[1] if len(parts)>1 else '','country':parts[2] if len(parts)>2 else (parts[-1] if len(parts)==2 else '')}

def normalize_date(value: str) -> str:
    if not value: return ''
    for fmt in ('%B %d, %Y','%b %d, %Y','%B %Y','%b %Y','%m/%Y','%m-%Y','%Y-%m-%d'):
        try: return datetime.strptime(value.strip(),fmt).strftime('%Y-%m-%d')
        except ValueError: pass
    m=re.search(r'(20\d{2}|19\d{2})',value)
    return f'{m.group(1)}-01-01' if m else value.strip()

def map_profile(profile: dict, fields: list[dict] | None = None) -> dict:
    first,last=split_name(profile.get('name',''))
    loc=split_location(profile.get('location',''))
    base={
      'first_name':first,'last_name':last,'email':profile.get('email',''),'phone':profile.get('phone',''),
      'address':profile.get('address',''),'city':loc['city'],'state':loc['state'],'country':loc['country'],
      'linkedin':profile.get('linkedin',''),'github':profile.get('github',''),'website':profile.get('website',''),
      'education':profile.get('education',''),'degree':profile.get('degree',''),'resume':profile.get('resume_path',''),
      'cover_letter':profile.get('cover_letter','')
    }
    if not fields: return base
    out={}
    for field in fields:
        label=str(field.get('label') or field.get('name') or '').lower().strip()
        key=field.get('name') or field.get('id') or label
        canonical=next((k for k,aliases in FIELD_ALIASES.items() if any(a in label for a in aliases)), None)
        out[key]=base.get(canonical,'') if canonical else ''
    return out

def analyze_fields(fields: list[dict]) -> dict:
    mapped=map_profile({},fields)
    required=[f for f in fields if f.get('required')]
    unresolved=[f.get('label') or f.get('name') for f in required if not mapped.get(f.get('name') or f.get('id') or f.get('label'))]
    return {'mapped_fields':len(fields)-len(unresolved),'total_fields':len(fields),'required_unresolved':unresolved,'platform':'generic'}
