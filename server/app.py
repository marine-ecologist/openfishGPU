import hashlib
import hmac
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeTimedSerializer, BadSignature
from pydantic import BaseModel, Field
from shared.drive import Drive, CloudError, API
from server.store import Store

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = json.loads((ROOT / 'versions.json').read_text())
VIDEO = {'.mp4', '.mov', '.mkv', '.avi', '.m4v'}
TERMINAL = {'completed', 'failed', 'cancelled'}

drive = Drive()
store = None
sync_lock = threading.Lock()
login_attempts = {}

@asynccontextmanager
async def lifespan(app):
    global store
    for name in ['SESSION_SECRET', 'APP_PASSWORD', 'PUBLIC_ORIGIN']:
        if not os.environ.get(name): raise RuntimeError(f'{name} is required')
    if len(os.environ['SESSION_SECRET']) < 32: raise RuntimeError('SESSION_SECRET needs at least 32 characters')
    if len(os.environ['APP_PASSWORD']) < 16: raise RuntimeError('APP_PASSWORD needs at least 16 characters')
    store = Store()
    yield

app = FastAPI(title='openfishGPU', version=VERSIONS['openfishGPU'], lifespan=lifespan)

def now(): return datetime.now(timezone.utc).isoformat()
def signer(): return URLSafeTimedSerializer(os.environ['SESSION_SECRET'], salt='openfishgpu-session-v1')
def secure(): return os.environ['PUBLIC_ORIGIN'].startswith('https://')

def fail(code, message): raise HTTPException(code, message)

def drive_id(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{5,200}', value): fail(400, 'Invalid Drive ID')
    return value

def job_for(ident):
    job = store.get(ident)
    if not job: fail(404, 'Job not found')
    return job

def public(job):
    hidden = {'metadataId', 'folderId', 'outputFolderId', 'source', 'runpodId'}
    return {key: value for key, value in job.items() if key not in hidden}

def persist(job):
    job['updatedAt'] = now()
    store.save(job)  # Local state is retained even when Drive is temporarily unavailable.
    drive.put_json(job, job['folderId'], job['metadataId'])

@app.middleware('http')
async def guard(request: Request, call_next):
    path = request.url.path
    if path.startswith('/api/'):
        if request.method not in {'GET', 'HEAD'} and request.headers.get('origin') != os.environ.get('PUBLIC_ORIGIN'):
            return JSONResponse({'detail': 'Request origin is not allowed'}, status_code=403)
        if path != '/api/login':
            try:
                if signer().loads(request.cookies.get('session', ''), max_age=43200) != 'workspace': raise BadSignature('session')
            except BadSignature:
                return JSONResponse({'detail': 'Sign in to your workspace'}, status_code=401)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self'; connect-src 'self' https://*.googleapis.com; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response

@app.exception_handler(CloudError)
async def cloud_error(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=502)

class Login(BaseModel):
    password: str = Field(max_length=1000)

@app.post('/api/login')
def login(body: Login, request: Request):
    ip = request.client.host if request.client else 'unknown'
    with sync_lock:
        attempts = [t for t in login_attempts.get(ip, []) if t > time.time() - 300]
        if len(attempts) >= 10: fail(429, 'Too many sign-in attempts. Try again in five minutes.')
        attempts.append(time.time())
        login_attempts[ip] = attempts
    # Fixed-length digests avoid leaking length through comparison.
    if not hmac.compare_digest(hashlib.sha256(body.password.encode()).digest(), hashlib.sha256(os.environ['APP_PASSWORD'].encode()).digest()):
        fail(401, 'Incorrect workspace password')
    response = JSONResponse({'ok': True})
    response.set_cookie('session', signer().dumps('workspace'), httponly=True, secure=secure(), samesite='strict', max_age=43200)
    return response

@app.post('/api/logout')
def logout():
    r = JSONResponse({'ok': True}); r.delete_cookie('session'); return r

@app.get('/api/config')
def config():
    return {'versions': VERSIONS, 'maxBytes': max_bytes(), 'storage': 'Google Drive', 'workspace': 'Shared team workspace'}

def max_bytes(): return int(os.environ.get('MAX_VIDEO_BYTES', str(20 * 1024**3)))

@app.get('/api/drive')
def browse(folder: str | None = None, page: str | None = None):
    root = os.environ['GOOGLE_DRIVE_SOURCE_ROOT_ID']
    folder = drive_id(folder or root)
    if not drive.under(folder, root): fail(403, 'Folder is outside the configured video library')
    data = drive.children(folder, page)
    data['files'] = [f for f in data['files'] if f['mimeType'] == 'application/vnd.google-apps.folder' or Path(f['name']).suffix.lower() in VIDEO]
    return data

class Create(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    fileName: str | None = Field(default=None, max_length=180)
    size: int | None = Field(default=None, gt=0)
    driveFileId: str | None = None
    confidence: float = Field(default=.10, ge=.01, le=.10)
    imageSize: int = 1024

@app.post('/api/jobs', status_code=201)
def create(body: Create):
    if body.imageSize not in (640, 1024, 1536): fail(400, 'Choose a supported resolution')
    if not body.name.strip(): fail(400, 'Enter a job name')
    if bool(body.driveFileId) == bool(body.fileName): fail(400, 'Choose either an upload or a Drive video')
    source = None
    if body.driveFileId:
        ident = drive_id(body.driveFileId)
        if not drive.under(ident, os.environ['GOOGLE_DRIVE_SOURCE_ROOT_ID']): fail(403, 'Video is outside the library')
        source = drive.get(ident)
        name, size = source['name'], int(source.get('size', 0))
    else:
        name, size = body.fileName, body.size or 0
        if '/' in name or '\\' in name or any(ord(c) < 32 for c in name): fail(400, 'Invalid filename')
    if Path(name).suffix.lower() not in VIDEO: fail(400, 'Choose an MP4, MOV, MKV, AVI or M4V video')
    if not 0 < size <= max_bytes(): fail(413, 'Video exceeds the configured size limit or is empty')
    ident = str(uuid.uuid4())
    folder = drive.folder(ident, os.environ['GOOGLE_DRIVE_JOB_ROOT_ID'])
    output = drive.folder('output', folder)
    job = {'schemaVersion': 1, 'id': ident, 'name': body.name.strip(), 'state': 'uploading', 'stage': 'Ready to submit' if source else 'Uploading video',
           'progress': 0, 'createdAt': now(), 'updatedAt': now(), 'fileName': name, 'size': size,
           'source': source, 'folderId': folder, 'outputFolderId': output, 'versions': VERSIONS,
           'settings': {'tracking': {'confidence': body.confidence, 'imgsz': body.imageSize}}}
    job['metadataId'] = drive.put_json(job, folder)
    store.save(job)
    upload = drive.upload_session(name, folder, size, 'application/octet-stream') if not source else None
    return {'job': public(job), 'uploadUrl': upload}

@app.get('/api/jobs')
def history(offset: int = 0):
    if offset < 0: fail(400, 'Invalid offset')
    return {'jobs': [public(j) for j in store.list(offset)]}

@app.post('/api/jobs/{ident}/start', status_code=202)
def start(ident: str):
    job = job_for(ident)
    if job['state'] != 'uploading': fail(409, 'This job has already been submitted')
    if not job['source']:
        data = drive.children(job['folderId'])
        sources = [f for f in data['files'] if f['name'] == job['fileName'] and int(f.get('size', 0)) == job['size']]
        if len(sources) != 1: fail(409, 'Video upload is not complete')
        job['source'] = sources[0]
    else:
        current = drive.get(job['source']['id'])
        if int(current.get('size', 0)) != job['size'] or not drive.under(current['id'], os.environ['GOOGLE_DRIVE_SOURCE_ROOT_ID']):
            fail(409, 'Source video changed or moved; create a new job')
    if not store.claim(ident): fail(409, 'Submission is already in progress')
    job['state'], job['stage'] = 'submitting', 'Submitting to GPU'
    try:
        result = provider('run', {'input': {'schema_version': 1, 'job_id': ident, 'source_id': job['source']['id'],
                     'source_size': job['size'], 'folder_id': job['folderId'], 'output_folder_id': job['outputFolderId'],
                     'settings': job['settings'], 'versions': VERSIONS},
                     'policy': {'executionTimeout': int(os.environ.get('RUNPOD_EXECUTION_TIMEOUT_MS', '7200000')), 'ttl': 86400000}})
        job['runpodId'] = result['id']
        job['state'], job['stage'] = 'queued', 'Waiting for a GPU'
    except (CloudError, KeyError):
        job['state'], job['stage'] = 'submission_unknown', 'Submission needs operator review'
        job['error'] = 'The provider did not confirm submission. Check RunPod before creating another job to avoid duplicate charges.'
    persist(job)
    return public(job)

def provider(route, payload=None):
    endpoint = os.environ['RUNPOD_ENDPOINT_ID']
    try:
        r = requests.request('POST' if payload is not None else 'GET', f'https://api.runpod.ai/v2/{endpoint}/{route}',
                             headers={'Authorization': f"Bearer {os.environ['RUNPOD_API_KEY']}"}, json=payload, timeout=45)
    except requests.RequestException:
        raise CloudError('RunPod is unavailable; try checking status again') from None
    if not r.ok: raise CloudError(f'RunPod request failed (HTTP {r.status_code})')
    try: return r.json()
    except ValueError: raise CloudError('RunPod returned an invalid response') from None

@app.get('/api/jobs/{ident}')
def status(ident: str):
    with sync_lock:
        job = job_for(ident)
        if job['state'] in {'queued', 'running'}:
            try:
                result = provider(f"status/{job['runpodId']}")
            except CloudError:
                # Result records can expire at the provider. The worker's final
                # Drive manifest remains durable and can recover completion.
                manifests = [f for f in drive.children(job['outputFolderId'])['files'] if f.get('name') == 'manifest.json']
                if len(manifests) != 1: raise
                result = {'status': 'COMPLETED', 'output': {'state': 'completed', 'manifestId': manifests[0]['id']}}
            state = result.get('status')
            if state == 'IN_PROGRESS':
                job['state'] = 'running'
                detail = result.get('output')
                if isinstance(detail, dict):
                    job['stage'] = str(detail.get('stage', 'Processing video'))[:120]
                    job['progress'] = min(99, max(0, int(detail.get('progress', 1))))
                else: job['stage'] = 'Processing video'
            elif state == 'COMPLETED':
                output = result.get('output', {})
                # Provider completion alone does not prove results were persisted.
                if not isinstance(output, dict) or output.get('state') != 'completed' or not output.get('manifestId'):
                    job['state'], job['stage'], job['error'] = 'failed', 'GPU processing failed', 'Worker returned no complete result manifest'
                else:
                    manifest_id = drive_id(output['manifestId'])
                    if not drive.under(manifest_id, job['outputFolderId']): raise CloudError('Worker result is outside the job folder')
                    response = drive.request('GET', f'{API}/{manifest_id}', params={'alt': 'media', 'supportsAllDrives': 'true'})
                    manifest = response.json()
                    if manifest.get('jobId') != ident: raise CloudError('Result manifest belongs to a different job')
                    job.update(state='completed', stage='Ready to review', progress=100, result=manifest)
            elif state in {'FAILED', 'TIMED_OUT', 'CANCELLED'}:
                job.update(state='cancelled' if state == 'CANCELLED' else 'failed', stage='Processing stopped', error='GPU processing stopped. Check the private RunPod worker logs.')
            persist(job)
        return public(job)

@app.post('/api/jobs/{ident}/cancel')
def cancel(ident: str):
    with sync_lock:
        job = job_for(ident)
        if job['state'] not in {'queued', 'running'}: fail(409, 'Job cannot be cancelled in its current state')
        provider(f"cancel/{job['runpodId']}", {})
        # Keep polling until RunPod confirms a terminal state.
        job['stage'] = 'Cancellation requested'
        persist(job)
        return public(job)

@app.get('/api/jobs/{ident}/assets/{asset_id}')
def asset(ident: str, asset_id: str, request: Request):
    job = job_for(ident)
    assets = job.get('result', {}).get('assets', [])
    entry = next((a for a in assets if a['id'] == asset_id), None)
    if job['state'] != 'completed' or not entry: fail(404, 'Result not found')
    headers = {}
    if request.headers.get('range'): headers['Range'] = request.headers['range']
    r = drive.request('GET', f'{API}/{drive_id(asset_id)}', params={'alt': 'media', 'supportsAllDrives': 'true'}, headers=headers, stream=True)
    def chunks():
        with r:
            yield from r.iter_content(1024 * 1024)
    forwarded = {k: r.headers[k] for k in ['Content-Length', 'Content-Range', 'Accept-Ranges'] if k in r.headers}
    forwarded['Content-Disposition'] = 'inline' if entry['name'].endswith(('.jpg', '.mp4', '.json')) else 'attachment'
    return StreamingResponse(chunks(), status_code=r.status_code, media_type=entry.get('mimeType', 'application/octet-stream'), headers=forwarded)

@app.get('/')
def index(): return FileResponse(ROOT / 'web/index.html')
app.mount('/static', StaticFiles(directory=ROOT / 'web'), name='static')
