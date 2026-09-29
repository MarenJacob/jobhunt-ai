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


def test_manual_browser_submit_not_blocked_by_auto_submit_policy(monkeypatch):
    """A person clicking 'Run browser worker' with Dry run off is an explicit, one-off
    instruction — it must not be rejected just because the AUTO_SUBMIT autonomy flag is off."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.config import settings
    monkeypatch.setattr(settings, 'auto_submit', False)
    monkeypatch.setattr(settings, 'browser_worker_url', '')  # no worker configured -> falls to local path (raises, not 403)
    c = TestClient(app)
    c.post('/api/profile', json={'name': 'Test User', 'email': 't2@example.com'})
    c.post('/api/jobs', json={'title': 'Junior Dev', 'company': 'Acme', 'url': 'https://jobs.lever.co/acme/aaaaaaaa-1111-2222-3333-444455556666'})
    job_id = c.get('/api/jobs').json()[0]['id']
    app_id = c.post('/api/applications', json={'job_id': job_id}).json()['id']
    r = c.post(f'/api/applications/{app_id}/browser/execute', params={'dry_run': False})
    assert r.status_code != 403  # must not be the old "AUTO_SUBMIT is disabled" block
