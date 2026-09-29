"""Playwright-driven tests for the browser worker's form reading, filling and stop
logic. These start a tiny local HTTP server serving fixture HTML pages and run the
worker against real Chromium, so they need Playwright's browsers installed
(`playwright install chromium`) and are skipped automatically if that's unavailable.
"""
import asyncio, base64, http.server, os, socket, threading, time
import pytest

pytestmark = pytest.mark.anyio if False else []

FORM_PLAIN = """<html><body><form>
<label>First Name<input name="first_name"></label>
<label>Last Name<input name="last_name"></label>
<label>Email<input type="email" name="email" required></label>
<label>Phone<input name="phone"></label>
<label>Resume<input type="file" name="resume" required></label>
<fieldset><legend>Authorized to work here?</legend>
 <label><input type="radio" name="auth" value="yes">Yes</label>
 <label><input type="radio" name="auth" value="no">No</label>
</fieldset>
<label><input type="checkbox" name="consent" required> I agree to the terms</label>
<button type="submit">Submit Application</button>
</form></body></html>"""

FORM_SIMPLE = """<html><body><form id="f">
<label>Full Name<input name="name" required></label>
<label>Email<input type="email" name="email" required></label>
<button type="submit">Submit Application</button>
</form>
<script>
document.getElementById('f').addEventListener('submit', function(e){
  e.preventDefault();
  document.body.innerHTML = '<h1>Thank you for applying!</h1>';
});
</script></body></html>"""

FORM_CAPTCHA = """<html><body><form>
<label>Email<input name="email"></label>
<div class="g-recaptcha" style="width:300px;height:80px;background:#eee"></div>
<button type="submit">Submit</button>
</form></body></html>"""

PAGES = {'/plain.html': FORM_PLAIN, '/simple.html': FORM_SIMPLE, '/captcha.html': FORM_CAPTCHA}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGES.get(self.path)
        if body is None:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *a):
        pass


@pytest.fixture(scope='module')
def server():
    for _ in range(50):
        port = 8700 + os.getpid() % 200
        try:
            srv = http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)
            break
        except OSError:
            continue
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    yield f'http://127.0.0.1:{port}'
    srv.shutdown()


@pytest.fixture(scope='module')
def worker_mod(monkeypatch_module=None):
    os.environ.setdefault('ALLOWED_DOMAINS', '127.0.0.1,localhost')
    import importlib
    import worker.app as w
    importlib.reload(w)
    return w


def _run(coro):
    try:
        return asyncio.run(coro)
    except Exception as e:
        if 'Executable doesn' in str(e) or 'playwright install' in str(e).lower():
            pytest.skip(f'Playwright browser not installed: {e}')
        raise


PROFILE = {'name': 'Test Candidate', 'email': 't@example.com', 'phone': '08100000000', 'work_authorization': 'Yes'}


def test_inspect_reads_fields_and_flags_required(server, worker_mod):
    r = _run(worker_mod.run_job(worker_mod.Execute(action='inspect', url=server + '/plain.html', profile=PROFILE)))
    assert r['status'] == 'inspected'
    kinds = {f['kind']: f['required'] for f in r['fields']}
    assert kinds['email'] is True and kinds['resume'] is True
    assert r['ready_for_submission'] is False  # resume + consent checkbox still need the person


def test_dry_run_blocks_without_resume(server, worker_mod):
    r = _run(worker_mod.run_job(worker_mod.Execute(action='submit', url=server + '/plain.html', profile=PROFILE, dry_run=True)))
    assert r['status'] == 'needs_human'
    assert any('Resume' in u for u in r['unresolved'])


def test_dry_run_fills_with_resume_but_still_stops_for_consent(server, worker_mod):
    resume = base64.b64encode(b'%PDF-1.4 fake').decode()
    r = _run(worker_mod.run_job(worker_mod.Execute(action='submit', url=server + '/plain.html', profile=PROFILE,
                                                     dry_run=True, resume_base64=resume, resume_filename='r.pdf')))
    assert r['status'] == 'needs_human'
    assert 'Email' in r['filled'] and 'Resume' in r['filled']
    assert any('consent' in u.lower() or 'agree' in u.lower() for u in r['unresolved'])


def test_captcha_page_is_never_submitted(server, worker_mod):
    r = _run(worker_mod.run_job(worker_mod.Execute(action='inspect', url=server + '/captcha.html', profile=PROFILE)))
    assert any('CAPTCHA' in s or 'captcha' in s for s in r['stops'])
    r2 = _run(worker_mod.run_job(worker_mod.Execute(action='submit', url=server + '/captcha.html', profile=PROFILE, dry_run=False)))
    assert r2['status'] == 'needs_human' and r2['submitted'] is False


def test_full_submit_reaches_confirmation(server, worker_mod):
    r = _run(worker_mod.run_job(worker_mod.Execute(action='submit', url=server + '/simple.html',
                                                     profile={'name': 'Test Candidate', 'email': 't@example.com'}, dry_run=False)))
    assert r['status'] == 'submitted' and r['submitted'] is True
    assert 'thank you' in (r.get('confirmation') or '').lower()
