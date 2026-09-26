from app.services.submission import SubmissionService
from app.services.browser import BrowserAutomation
from types import SimpleNamespace

def test_policy_blocks_low_match():
    svc=SubmissionService(None)
    job=SimpleNamespace(title='Junior AI Engineer', description='0-2 years', url='https://greenhouse.io/jobs/1', match_score=20)
    profile=SimpleNamespace()
    r=svc.policy(job, profile)
    assert not r['allowed']
    assert 'match_score_below_threshold' in r['reasons']

def test_policy_blocks_senior():
    svc=SubmissionService(None)
    job=SimpleNamespace(title='Senior AI Engineer', description='5 years', url='https://greenhouse.io/jobs/1', match_score=90)
    r=svc.policy(job, SimpleNamespace())
    assert not r['allowed']
    assert 'blocked_role_term' in r['reasons']
