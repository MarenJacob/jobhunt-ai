from app.services.matcher import match_job
from app.services.browser import BrowserAutomation

def test_matcher_rewards_overlap():
    r=match_job('junior python fastapi ai engineer','python fastapi AI web development')
    assert r.score > 50
    assert 'python' in r.matched

def test_senior_penalty():
    r=match_job('senior lead engineer','python fastapi')
    assert r.score < 50

def test_browser_allowlist():
    b=BrowserAutomation()
    assert b.allowed('https://www.linkedin.com/jobs/view/123')
    assert not b.allowed('https://example.com/apply')

def test_ats_canonical_mapping():
    from app.services.ats import canonical_field, split_location, split_name
    assert canonical_field('First Name', 'candidate_first_name', '') == 'first_name'
    assert canonical_field('ZIP / Postal Code', 'postal_code', '') == 'postal_code'
    assert split_name('Ada Lovelace') == ('Ada','Lovelace')
    assert split_location('Abuja, FCT, Nigeria')['country'] == 'Nigeria'
