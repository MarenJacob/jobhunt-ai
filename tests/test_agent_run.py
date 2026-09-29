"""End-to-end tests for job discovery: real feeds, non-job rejection, staleness.

Uses the app's actual configured database (see conftest) and clears the jobs
table between tests so runs don't interfere with each other.
"""
import httpx, respx
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import Job

client = TestClient(app)

GH_JOB = '''<html><script type="application/ld+json">{"@type":"JobPosting","title":"Junior AI Engineer",
"hiringOrganization":{"name":"Acme"},"jobLocationType":"TELECOMMUTE",
"description":"Responsibilities: build with Python and FastAPI. Requirements: 0-2 years experience. Apply now."}
</script></html>'''


def setup_function(_):
    from app.services.sources import clear_cache
    clear_cache()
    s = SessionLocal()
    s.query(Job).delete(); s.commit(); s.close()
    client.post('/api/profile', json={"name": "Test User", "headline": "AI Application Developer", "email": "t@example.com",
                                       "skills": "Python, FastAPI, SQL", "location": "Jos, Nigeria", "preferences": "remote junior"})


def _empty_feeds(route):
    route.get('https://remotive.com/api/remote-jobs').mock(return_value=httpx.Response(200, json={'jobs': []}))
    route.get('https://remoteok.com/api').mock(return_value=httpx.Response(200, json=[{}]))
    route.get('https://www.arbeitnow.com/api/job-board-api').mock(return_value=httpx.Response(200, json={'data': []}))


def test_agent_run_stores_real_jobs_only():
    route = respx.mock(assert_all_called=False)
    route.get('https://remotive.com/api/remote-jobs').mock(return_value=httpx.Response(200, json={'jobs': [
        {'title': 'Junior Python Developer', 'company_name': 'RemoteCo', 'url': 'https://remotive.com/remote-jobs/software-dev/junior-python-developer-99001',
         'candidate_required_location': 'Worldwide', 'description': 'Responsibilities: Python, FastAPI, SQL. Requirements: entry level.', 'tags': ['python'], 'category': 'dev'}]}))
    route.get('https://remoteok.com/api').mock(return_value=httpx.Response(200, json=[{}]))
    route.get('https://www.arbeitnow.com/api/job-board-api').mock(return_value=httpx.Response(200, json={'data': []}))
    route.get(url__regex=r'.*').mock(return_value=httpx.Response(404))
    with route:
        r = client.post('/api/agent/run')
    assert r.status_code == 200
    body = r.json()
    assert body['discovered'] == 1
    jobs = client.get('/api/jobs').json()
    assert jobs[0]['source'] == 'remotive.com' and jobs[0]['verified'] is True


def test_agent_run_rejects_non_job_pages(monkeypatch):
    monkeypatch.setattr('app.config.settings.tavily_api_key', 'test-key')
    route = respx.mock(assert_all_called=False)
    _empty_feeds(route)
    route.post('https://api.tavily.com/search').mock(return_value=httpx.Response(200, json={'results': [
        {'url': 'https://en.wikipedia.org/wiki/Software_engineer', 'title': 'Software engineer - Wikipedia', 'content': 'A software engineer designs software'},
        {'url': 'https://jobs.lever.co/acme/0a1b2c3d-1111-2222-3333-444455556666', 'title': 'Junior AI Engineer at Acme', 'content': 'Responsibilities apply now'},
    ]}))
    route.get('https://jobs.lever.co/acme/0a1b2c3d-1111-2222-3333-444455556666').mock(return_value=httpx.Response(200, text=GH_JOB))
    route.get(url__regex=r'.*wikipedia.*').mock(return_value=httpx.Response(200, text='<html><body>A software engineer designs software systems. In this article we explore career paths.</body></html>'))
    with route:
        r = client.post('/api/agent/run')
    body = r.json()
    assert body['discovered'] == 1
    assert body['rejected_total'] == 1
    assert 'wikipedia' in body['rejected_examples'][0]['url']
    jobs = client.get('/api/jobs').json()
    assert all('wikipedia' not in j['url'] for j in jobs)


def test_agent_run_expires_stale_postings():
    s = SessionLocal()
    s.add(Job(title='Old Role', company='OldCo', url='https://jobs.lever.co/oldco/aaaaaaaa-1111-2222-3333-444455556666',
               source='lever.co', description='Responsibilities: Python. Requirements 0-2 years', verified=True,
               created_at=datetime.utcnow() - timedelta(days=30), last_checked_at=datetime.utcnow() - timedelta(days=20)))
    s.commit(); s.close()
    route = respx.mock(assert_all_called=False)
    _empty_feeds(route)
    route.get('https://jobs.lever.co/oldco/aaaaaaaa-1111-2222-3333-444455556666').mock(return_value=httpx.Response(404))
    with route:
        r = client.post('/api/agent/run')
    body = r.json()
    assert body['rechecked'] == 1 and body['expired'] == 1
    jobs = client.get('/api/jobs').json()
    assert all(j['title'] != 'Old Role' for j in jobs)
    jobs_all = client.get('/api/jobs', params={'include_expired': True}).json()
    assert any(j['title'] == 'Old Role' and j['expired'] for j in jobs_all)
