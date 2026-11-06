"""Google Drive v3 storage. OAuth secrets never leave the server/worker."""
import json
import os
import threading
import time
from pathlib import Path
import requests

API = 'https://www.googleapis.com/drive/v3/files'
UPLOAD = 'https://www.googleapis.com/upload/drive/v3/files'
FIELDS = 'id,name,mimeType,size,parents,trashed'

class CloudError(RuntimeError):
    pass

class Drive:
    def __init__(self):
        self.token = None
        self.expires = 0
        self.lock = threading.Lock()

    def headers(self):
        with self.lock:
            if time.time() >= self.expires:
                r = requests.post('https://oauth2.googleapis.com/token', data={
                    'client_id': os.environ['GOOGLE_CLIENT_ID'],
                    'client_secret': os.environ['GOOGLE_CLIENT_SECRET'],
                    'refresh_token': os.environ['GOOGLE_REFRESH_TOKEN'],
                    'grant_type': 'refresh_token'}, timeout=30)
                if not r.ok:
                    raise CloudError('Drive authorization failed; check server OAuth configuration')
                payload = r.json()
                self.token = payload['access_token']
                self.expires = time.time() + int(payload['expires_in']) - 60
        return {'Authorization': f'Bearer {self.token}'}

    def request(self, method, url, **kwargs):
        headers = {**self.headers(), **kwargs.pop('headers', {})}
        r = requests.request(method, url, headers=headers, timeout=120, **kwargs)
        if not r.ok:
            r.close()
            raise CloudError(f'Drive {method} failed (HTTP {r.status_code})')
        return r

    def get(self, ident):
        return self.request('GET', f'{API}/{ident}', params={'fields': FIELDS, 'supportsAllDrives': 'true'}).json()

    def children(self, parent, page=None):
        # IDs are validated before interpolation; escape for Drive query syntax too.
        parent = parent.replace('\\', '\\\\').replace("'", "\\'")
        params = {'q': f"'{parent}' in parents and trashed = false", 'fields': f'nextPageToken,files({FIELDS})',
                  'pageSize': 100, 'supportsAllDrives': 'true', 'includeItemsFromAllDrives': 'true', 'orderBy': 'folder,name'}
        if page: params['pageToken'] = page
        return self.request('GET', API, params=params).json()

    def under(self, ident, root):
        """Constrain selection to a configured storage root, including shared drives."""
        current = ident
        for _ in range(50):
            item = self.get(current)
            if item.get('trashed'): return False
            if current == root: return True
            parents = item.get('parents', [])
            if not parents: return False
            current = parents[0]
        return False

    def folder(self, name, parent):
        return self.request('POST', API, params={'fields': FIELDS, 'supportsAllDrives': 'true'}, json={
            'name': name, 'parents': [parent], 'mimeType': 'application/vnd.google-apps.folder'}).json()['id']

    def upload_session(self, name, parent, size, mime):
        r = self.request('POST', UPLOAD, params={'uploadType': 'resumable', 'supportsAllDrives': 'true', 'fields': FIELDS},
                         headers={'X-Upload-Content-Length': str(size), 'X-Upload-Content-Type': mime},
                         json={'name': name, 'parents': [parent]})
        return r.headers['Location']

    def put_file(self, path, parent, name=None):
        path = Path(path)
        import mimetypes
        mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        session = self.upload_session(name or path.name, parent, path.stat().st_size, mime)
        with path.open('rb') as stream:
            r = requests.put(session, data=stream, headers={'Content-Type': mime, 'Content-Length': str(path.stat().st_size)}, timeout=1800)
        if not r.ok: raise CloudError('Drive result upload failed')
        return r.json()

    def put_json(self, value, parent, ident=None):
        payload = json.dumps(value, allow_nan=False).encode()
        if ident:
            self.request('PATCH', f'{UPLOAD}/{ident}', params={'uploadType': 'media', 'supportsAllDrives': 'true'},
                         headers={'Content-Type': 'application/json'}, data=payload)
            return ident
        session = self.upload_session('job.json', parent, len(payload), 'application/json')
        r = requests.put(session, data=payload, headers={'Content-Type': 'application/json'}, timeout=120)
        if not r.ok: raise CloudError('Drive metadata upload failed')
        return r.json()['id']

    def download(self, ident, destination):
        r = self.request('GET', f'{API}/{ident}', params={'alt': 'media', 'supportsAllDrives': 'true'}, stream=True)
        with r, Path(destination).open('wb') as stream:
            for chunk in r.iter_content(8 * 1024 * 1024): stream.write(chunk)
