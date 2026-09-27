import re
from collections import Counter

STOP=set('the and for with from that this your you are our into have has will can a an to of in on is be as by or it at'.split())

def tokens(text):
    return [x.lower() for x in re.findall(r'[A-Za-z][A-Za-z+#.-]{1,}',text or '') if x.lower() not in STOP]

def keyword_alignment(resume: str, job: str):
    rt=Counter(tokens(resume)); jt=Counter(tokens(job));
    important=[w for w,c in jt.items() if c>=1 and len(w)>2]
    matched=[w for w in important if rt[w]]
    missing=[w for w in important if not rt[w]]
    score=round((len(matched)/max(1,len(important)))*100,1)
    return {'score':score,'matched':matched[:80],'missing':missing[:80]}

def align_bullets(bullets, job_text):
    job_tokens=set(tokens(job_text)); out=[]
    for bullet in bullets:
        words=tokens(bullet); overlap=[w for w in words if w in job_tokens]
        out.append({'original':bullet,'alignment_score':round(len(set(overlap))/max(1,len(set(words)))*100,1),'matched_terms':overlap[:12]})
    return out
