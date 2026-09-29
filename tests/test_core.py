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


def test_resume_persists_across_profile_save_and_reload(tmp_path):
    """Uploading a resume, then saving the profile form (which doesn't include
    resume fields), then reloading, must not lose the resume."""
    import io
    from docx import Document
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    doc = Document(); [doc.add_paragraph(l) for l in ['Maren Danjuma', 'AI Application Developer', 'EDUCATION', 'B.Sc. Computer Science, Plateau State University, Bokkos', '2019 - 2024', 'SKILLS', 'Python, FastAPI, SQL']]
    buf = io.BytesIO(); doc.save(buf); buf.seek(0)
    r = c.post('/api/profile/import-resume', files={'file': ('resume.docx', buf, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert r.status_code == 200 and r.json()['profile']['filename'] == 'resume.docx'
    # Saving the profile form (no resume fields in this payload) must not wipe it.
    c.post('/api/profile', json={'name': 'Maren Danjuma', 'email': 'm@example.com'})
    got = c.get('/api/profile').json()
    assert got['resume_filename'] == 'resume.docx'


def test_browser_endpoints_never_500_when_worker_unconfigured(monkeypatch):
    """The app must never crash with an unhandled 500 when BROWSER_WORKER_URL
    is unset — it should degrade to a clear, actionable error."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.config import settings
    monkeypatch.setattr(settings, 'browser_worker_url', '')
    c = TestClient(app)
    c.post('/api/profile', json={'name': 'Test User', 'email': 't3@example.com'})
    c.post('/api/jobs', json={'title': 'Junior Dev', 'company': 'Acme', 'url': 'https://jobs.lever.co/acme/bbbbbbbb-1111-2222-3333-444455556666'})
    job_id = c.get('/api/jobs').json()[-1]['id']
    app_id = c.post('/api/applications', json={'job_id': job_id}).json()['id']
    r1 = c.post(f'/api/applications/{app_id}/browser/execute', params={'dry_run': False})
    r2 = c.post(f'/api/applications/{app_id}/inspect')
    for r in (r1, r2):
        assert r.status_code < 500
        assert 'BROWSER_WORKER_URL' in r.json().get('detail', '')
