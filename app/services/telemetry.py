from collections import Counter

def company_telemetry(company: str, jobs: list[dict], applications: list[dict]) -> dict:
    company=(company or '').strip().lower()
    related=[j for j in jobs if str(j.get('company','')).strip().lower()==company]
    apps=[a for a in applications if str(a.get('company','')).strip().lower()==company]
    return {
      'company':company,
      'observed_open_roles':len(related),
      'observed_applications':len(apps),
      'application_statuses':dict(Counter(a.get('status','unknown') for a in apps)),
      'limitations':['Public job/application data is observational; it does not establish internal culture, turnover, hiring preferences, or causation.'],
      'requires_external_sources':['LinkedIn connection data (with user authorization)','public employee-review datasets','company career pages','public hiring reports']
    }
