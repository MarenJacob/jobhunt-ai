import re
from urllib.parse import urlparse
from datetime import datetime

ATS_HOSTS={'workday':('myworkdayjobs.com','workday.com'),'greenhouse':('greenhouse.io','boards.greenhouse.io'),'lever':('lever.co','jobs.lever.co'),'ashby':('ashbyhq.com','jobs.ashbyhq.com'),'smartrecruiters':('smartrecruiters.com',)}
FIELD_ALIASES={
'first_name':['first name','firstname','given name','forename'],'last_name':['last name','lastname','surname','family name'],'email':['email','email address','e-mail'],'phone':['phone','phone number','mobile','telephone','contact number'],'address':['address','street address','home address'],'city':['city','town'],'state':['state','province','region','state/province'],'postal_code':['zip','zip code','postal code'],'country':['country','country of residence','location country'],'linkedin':['linkedin','linkedin url','linkedin profile'],'github':['github','github url','github profile'],'website':['website','portfolio','personal website'],'education':['education','school','university','college'],'degree':['degree','qualification'],'resume':['resume','cv','curriculum vitae'],'cover_letter':['cover letter','coverletter','additional information','why do you want'],'work_authorization':['work authorization','authorized to work','legally authorized'],'sponsorship':['sponsorship','visa sponsorship','require sponsorship'],'salary':['salary','desired salary','compensation'],'job_title':['job title','position','role'],'company':['company','employer']}

def detect_platform(url):
 host=urlparse(url).netloc.lower()
 for name,domains in ATS_HOSTS.items():
  if any(d in host for d in domains): return name
 return 'generic'

def split_name(name):
 parts=(name or '').strip().split(); return (parts[0] if parts else '', ' '.join(parts[1:]) if len(parts)>1 else '')

def split_location(location):
 raw=(location or '').strip(); parts=[p.strip() for p in re.split(r'[,|]',raw) if p.strip()]
 if len(parts)>=3:return {'city':parts[0],'state':parts[1],'country':parts[2]}
 if len(parts)==2:return {'city':parts[0],'state':'','country':parts[1]}
 return {'city':parts[0] if parts else '','state':'','country':parts[0] if parts else ''}

def normalize_date(value):
 if not value:return ''
 value=value.strip()
 for fmt in ('%B %d, %Y','%b %d, %Y','%B %Y','%b %Y','%m/%Y','%m-%Y','%Y-%m-%d','%Y'):
  try:return datetime.strptime(value,fmt).strftime('%Y-%m-%d')
  except ValueError:pass
 m=re.search(r'(20\d{2}|19\d{2})',value); return f'{m.group(1)}-01-01' if m else value

def canonical_field(label,name='',id_=''):
 text=' '.join(str(x or '') for x in (label,name,id_)).lower().replace('_',' ').replace('-',' ')
 for k,aliases in FIELD_ALIASES.items():
  if any(a in text for a in aliases): return k
 return None

def canonical_value(profile,key,cover_letter=''):
 first,last=split_name(profile.get('name','')); loc=split_location(profile.get('location',''))
 base={'first_name':first,'last_name':last,'name':profile.get('name',''),'email':profile.get('email',''),'phone':profile.get('phone',''),'address':profile.get('address',''),'city':loc['city'],'state':loc['state'],'country':loc['country'],'linkedin':profile.get('linkedin',''),'github':profile.get('github',''),'website':profile.get('website',''),'education':profile.get('education',''),'degree':profile.get('degree',''),'resume':profile.get('resume_path',''),'cover_letter':cover_letter or profile.get('cover_letter',''),'work_authorization':profile.get('work_authorization',''),'sponsorship':profile.get('sponsorship',''),'salary':profile.get('salary',''),'job_title':profile.get('headline',''),'company':''}
 return base.get(key,'')

def map_profile(profile,fields=None):
 if not fields:
  return {k:canonical_value(profile,k) for k in FIELD_ALIASES}
 out={}
 for f in fields:
  label=f.get('label') or ''; key=f.get('name') or f.get('id') or label; canonical=canonical_field(label,f.get('name',''),f.get('id',''))
  out[key]=canonical_value(profile,canonical) if canonical else ''
 return out

def analyze_fields(fields):
 unresolved=[]
 for f in fields:
  c=canonical_field(f.get('label'),f.get('name'),f.get('id'))
  if f.get('required') and not c: unresolved.append(f.get('label') or f.get('name') or f.get('id') or 'unknown field')
 return {'mapped_fields':len(fields)-len(unresolved),'total_fields':len(fields),'required_unresolved':unresolved,'platform':'generic'}
