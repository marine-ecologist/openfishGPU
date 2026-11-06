"""Operator-only recovery. Stop the API before running; never dispatches work."""
import argparse
from shared.drive import API, Drive
from server.store import Store
import os
import re
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['scan', 'reconcile', 'manifest'])
    parser.add_argument('job_id', nargs='?')
    parser.add_argument('value', nargs='?')
    args = parser.parse_args()
    drive, store = Drive(), Store()
    root = os.environ['GOOGLE_DRIVE_JOB_ROOT_ID']
    if args.command == 'scan':
        page = None; restored = 0
        while True:
            folders = drive.children(root, page)
            for folder in folders['files']:
                if folder['mimeType'] != 'application/vnd.google-apps.folder': continue
                try: uuid.UUID(folder['name'])
                except ValueError: continue
                if store.get(folder['name']): continue
                children = drive.children(folder['id'])
                metadata = next((f for f in children['files'] if f['name'] == 'job.json'), None)
                if not metadata: continue
                record = drive.request('GET', f"{API}/{metadata['id']}", params={'alt': 'media', 'supportsAllDrives': 'true'}).json()
                if record.get('id') != folder['name'] or record.get('folderId') != folder['id']: raise ValueError('Invalid job metadata')
                record['metadataId'] = metadata['id']; store.save(record); restored += 1
            page = folders.get('nextPageToken')
            if not page: break
        print(f'Restored {restored} missing job records; no jobs submitted.')
        return
    if not args.job_id or not args.value: parser.error('job_id and value are required')
    job = store.get(str(uuid.UUID(args.job_id)))
    if not job: raise ValueError('Job not found; run scan first')
    if args.command == 'reconcile':
        if job['state'] not in {'submitting', 'submission_unknown'}: raise ValueError('Job is not awaiting reconciliation')
        if not re.fullmatch(r'[A-Za-z0-9_-]{3,200}', args.value): raise ValueError('Invalid provider ID')
        job.update(runpodId=args.value, state='queued', stage='Provider submission reconciled')
    else:
        if not drive.under(args.value, job['outputFolderId']): raise ValueError('Manifest is outside job output')
        manifest = drive.request('GET', f'{API}/{args.value}', params={'alt': 'media', 'supportsAllDrives': 'true'}).json()
        if manifest.get('jobId') != job['id'] or not isinstance(manifest.get('assets'), list): raise ValueError('Invalid manifest')
        job.update(state='completed', stage='Results recovered from Drive', progress=100, result=manifest)
    job.pop('error', None)
    store.save(job)
    drive.put_json(job, job['folderId'], job['metadataId'])
    print('Job record reconciled; no job submitted.')

if __name__ == '__main__': main()
