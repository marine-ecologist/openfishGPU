import copy
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
import server.app as api
from server.store import Store
from shared.drive import CloudError

class FakeDrive:
    def __init__(self):
        self.files = {
            'sourceRoot': {'id': 'sourceRoot', 'name': 'Library', 'parents': [], 'mimeType': 'application/vnd.google-apps.folder'},
            'jobsRoot': {'id': 'jobsRoot', 'name': 'Jobs', 'parents': [], 'mimeType': 'application/vnd.google-apps.folder'},
            'video123': {'id': 'video123', 'name': 'reef.mp4', 'parents': ['sourceRoot'], 'size': '100', 'mimeType': 'video/mp4'},
            'outside123': {'id': 'outside123', 'name': 'private.mp4', 'parents': [], 'size': '100', 'mimeType': 'video/mp4'},
        }
        self.metadata = {}
    def get(self, ident): return copy.deepcopy(self.files[ident])
    def under(self, ident, root):
        for _ in range(10):
            if ident == root: return True
            parents = self.files.get(ident, {}).get('parents', [])
            if not parents: return False
            ident = parents[0]
        return False
    def folder(self, name, parent):
        ident = 'folder' + uuid.uuid4().hex
        self.files[ident] = {'id': ident, 'name': name, 'parents': [parent], 'mimeType': 'application/vnd.google-apps.folder'}
        return ident
    def put_json(self, value, parent, ident=None):
        ident = ident or 'meta' + uuid.uuid4().hex
        self.metadata[ident] = copy.deepcopy(value)
        return ident
    def children(self, parent, page=None): return {'files': [copy.deepcopy(f) for f in self.files.values() if parent in f['parents']]}
    def upload_session(self, *args): return 'https://www.googleapis.com/upload/fake-sensitive-session'
    def request(self, *args, **kwargs):
        class Response:
            def json(self): return {'jobId': self_job, 'assets': [], 'trackCount': 0}
        self_job = self.complete_job
        return Response()

@pytest.fixture
def client(tmp_path, monkeypatch):
    for k, v in {'SESSION_SECRET': 's' * 40, 'APP_PASSWORD': 'p' * 20, 'PUBLIC_ORIGIN': 'http://testserver',
                 'DATABASE_PATH': str(tmp_path / 'jobs.db'), 'GOOGLE_DRIVE_SOURCE_ROOT_ID': 'sourceRoot', 'GOOGLE_DRIVE_JOB_ROOT_ID': 'jobsRoot'}.items(): monkeypatch.setenv(k, v)
    fake = FakeDrive(); monkeypatch.setattr(api, 'drive', fake)
    api.login_attempts.clear()
    with TestClient(api.app, headers={'Origin': 'http://testserver'}) as c:
        assert c.post('/api/login', json={'password': 'p' * 20}).status_code == 200
        yield c, fake

def new_drive(client):
    response = client.post('/api/jobs', json={'name': 'Reef transect', 'driveFileId': 'video123'})
    assert response.status_code == 201, response.text
    return response.json()['job']

def test_auth_origin_and_headers(client):
    c, _ = client
    assert c.get('/api/config').status_code == 200
    assert c.post('/api/jobs', json={'name': 'x'}, headers={'Origin': 'https://evil.invalid'}).status_code == 403
    assert c.get('/').headers['Content-Security-Policy'].startswith("default-src 'self'")
    c.post('/api/logout')
    assert c.get('/api/jobs').status_code == 401

def test_scope_validation_and_limits(client):
    c, _ = client
    assert c.get('/api/drive?folder=outside123').status_code == 403
    assert c.post('/api/jobs', json={'name': 'x', 'driveFileId': 'outside123'}).status_code == 403
    assert c.post('/api/jobs', json={'name': 'x', 'fileName': '../x.mp4', 'size': 100}).status_code == 400
    assert c.post('/api/jobs', json={'name': 'x', 'fileName': 'x.mp4', 'size': 999999999999}).status_code == 413
    assert c.post('/api/jobs', json={'name': 'x', 'fileName': 'x.exe', 'size': 100}).status_code == 400
    assert c.post('/api/jobs', json={'name': 'x', 'driveFileId': 'video123', 'imageSize': 888}).status_code == 400

def test_upload_requires_completed_drive_file(client, monkeypatch):
    c, drive = client
    r = c.post('/api/jobs', json={'name': 'Upload', 'fileName': 'reef.mp4', 'size': 100})
    job = r.json()['job']; assert r.json()['uploadUrl']
    assert c.post(f"/api/jobs/{job['id']}/start").status_code == 409
    assert 'fake-sensitive-session' not in c.get('/api/jobs').text
    original = api.store.get(job['id'])
    drive.files['uploaded123'] = {'id': 'uploaded123', 'name': 'reef.mp4', 'parents': [original['folderId']], 'size': '100', 'mimeType': 'video/mp4'}
    monkeypatch.setattr(api, 'provider', lambda *args: {'id': 'pod123'})
    assert c.post(f"/api/jobs/{job['id']}/start").json()['state'] == 'queued'
    assert api.store.get(job['id'])['source']['id'] == 'uploaded123'

def test_lifecycle_and_duplicate_submission(client, monkeypatch):
    c, drive = client
    job = new_drive(c); ident = job['id']; calls = []
    def provider(route, payload=None):
        calls.append(route)
        if route == 'run': return {'id': 'pod123'}
        return {'status': 'IN_PROGRESS', 'output': {'stage': 'Tracking', 'progress': 40}}
    monkeypatch.setattr(api, 'provider', provider)
    assert c.post(f'/api/jobs/{ident}/start').json()['state'] == 'queued'
    assert c.post(f'/api/jobs/{ident}/start').status_code == 409
    assert calls.count('run') == 1
    assert c.get(f'/api/jobs/{ident}').json()['progress'] == 40
    drive.complete_job = ident
    output = api.store.get(ident)['outputFolderId']
    drive.files['manifest123'] = {'id': 'manifest123', 'parents': [output]}
    monkeypatch.setattr(api, 'provider', lambda *args: {'status': 'COMPLETED', 'output': {'state': 'completed', 'manifestId': 'manifest123'}})
    completed = c.get(f'/api/jobs/{ident}').json()
    assert completed['state'] == 'completed'
    assert completed['result']['trackCount'] == 0
    assert drive.metadata[api.store.get(ident)['metadataId']]['state'] == 'completed'
    assert c.get(f'/api/jobs/{ident}/assets/outside123').status_code == 404

def test_ambiguous_submission_is_not_retried(client, monkeypatch):
    c, _ = client; ident = new_drive(c)['id']
    def unavailable(*args): raise CloudError('timeout')
    monkeypatch.setattr(api, 'provider', unavailable)
    assert c.post(f'/api/jobs/{ident}/start').json()['state'] == 'submission_unknown'
    assert c.post(f'/api/jobs/{ident}/start').status_code == 409

def test_completed_without_manifest_is_failed(client, monkeypatch):
    c, _ = client; ident = new_drive(c)['id']
    monkeypatch.setattr(api, 'provider', lambda *args: {'id': 'pod123'})
    c.post(f'/api/jobs/{ident}/start')
    monkeypatch.setattr(api, 'provider', lambda *args: {'status': 'COMPLETED'})
    assert c.get(f'/api/jobs/{ident}').json()['state'] == 'failed'

@pytest.mark.parametrize('provider_state,expected', [('FAILED','failed'), ('TIMED_OUT','failed'), ('CANCELLED','cancelled')])
def test_provider_terminal_states(client, monkeypatch, provider_state, expected):
    c, _ = client; ident = new_drive(c)['id']
    monkeypatch.setattr(api, 'provider', lambda *args: {'id': 'pod123'})
    c.post(f'/api/jobs/{ident}/start')
    monkeypatch.setattr(api, 'provider', lambda *args: {'status': provider_state, 'error': 'secret provider detail'})
    response = c.get(f'/api/jobs/{ident}')
    assert response.json()['state'] == expected
    assert 'secret provider detail' not in response.text

def test_cancel_waits_for_provider_confirmation(client, monkeypatch):
    c, _ = client; ident = new_drive(c)['id']
    monkeypatch.setattr(api, 'provider', lambda *args: {'id': 'pod123'})
    c.post(f'/api/jobs/{ident}/start')
    assert c.post(f'/api/jobs/{ident}/cancel').json()['state'] == 'queued'

def test_claim_is_atomic_and_index_persists(tmp_path):
    path = str(tmp_path / 'jobs.db'); store = Store(path)
    store.save({'id': 'job', 'state': 'uploading'})
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.claim('job'), range(8)))
    assert sum(results) == 1
    assert Store(path).get('job')['state'] == 'submitting'

def test_sign_in_rate_limit(client):
    c, _ = client
    for _ in range(9): assert c.post('/api/login', json={'password': 'wrong'}).status_code == 401
    assert c.post('/api/login', json={'password': 'wrong'}).status_code == 429

def test_expired_provider_result_recovers_from_drive(client, monkeypatch):
    c, drive = client; ident = new_drive(c)['id']
    monkeypatch.setattr(api, 'provider', lambda *args: {'id': 'pod123'})
    c.post(f'/api/jobs/{ident}/start')
    drive.complete_job = ident
    output = api.store.get(ident)['outputFolderId']
    drive.files['manifest123'] = {'id': 'manifest123', 'name': 'manifest.json', 'parents': [output]}
    def expired(*args): raise CloudError('RunPod request failed (HTTP 404)')
    monkeypatch.setattr(api, 'provider', expired)
    assert c.get(f'/api/jobs/{ident}').json()['state'] == 'completed'
