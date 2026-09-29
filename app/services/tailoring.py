import re
from collections import Counter

STOP=set('the and for with from that this your you are our into have has will can a an to of in on is be as by or it at we team role looking join help also across while including includes here there where when what who how why not no yes more most some any all each other than then so if but do does did done make made using used use very just about over under out up down new well like get gets getting working work works part every own between within without through per each such those these its it s'.split())

def tokens(text):
    return [x.lower() for x in re.findall(r'[A-Za-z][A-Za-z+#.-]{1,}',text or '') if x.lower() not in STOP and len(x)>2]

def keyword_alignment(resume: str, job: str):
    rt=Counter(tokens(resume)); jt=Counter(tokens(job));
    important=[w for w,c in jt.most_common() if len(w)>2]
    matched=[w for w in important if rt[w]]
    missing=[w for w in important if not rt[w]]
    score=round((len(matched)/max(1,len(important)))*100,1)
    return {'score':score,'matched':matched[:40],'missing':missing[:40]}

def align_bullets(bullets, job_text):
    job_tokens=set(tokens(job_text)); out=[]
    for bullet in bullets:
        words=tokens(bullet); overlap=[w for w in words if w in job_tokens]
        out.append({'original':bullet,'alignment_score':round(len(set(overlap))/max(1,len(set(words)))*100,1),'matched_terms':overlap[:12]})
    return out
