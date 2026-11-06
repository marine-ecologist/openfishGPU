"""RunPod Serverless CUDA worker. Only durable Drive IDs cross the job queue."""
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from shared.drive import Drive, CloudError
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))


def validate_input(data):
    import uuid
    if data.get('versions') != json.loads((ROOT / 'versions.json').read_text()): raise ValueError('API and worker versions differ')
    if data.get('schema_version') != 1: raise ValueError('Unsupported job schema')
    if str(uuid.UUID(data['job_id'])) != data['job_id']: raise ValueError('Invalid job ID')
    for key in ['source_id', 'folder_id', 'output_folder_id']:
        if not re.fullmatch(r'[A-Za-z0-9_-]{5,200}', data.get(key, '')): raise ValueError('Invalid Drive ID')
    if not 0 < data['source_size'] <= int(os.environ.get('MAX_VIDEO_BYTES', str(20 * 1024**3))): raise ValueError('Invalid source size')
    from fish_settings import normalize_settings
    return normalize_settings(data.get('settings'))


def report(job, stage, progress):
    import runpod
    runpod.serverless.progress_update(job, {'stage': stage, 'progress': progress})


def run(command, job, stage, progress):
    report(job, stage, progress)
    # Stream logs locally; do not expose subprocess errors or storage URLs in API responses.
    child = subprocess.Popen(command, cwd=ROOT / 'pipeline', stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for line in child.stdout:
            print(line.rstrip(), flush=True)
        if child.wait(): raise RuntimeError(f'{stage} failed; inspect private worker logs')
    finally:
        if child.poll() is None:
            child.terminate()
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: child.kill(); child.wait()


def build_results(out, job_id, versions):
    """Keep raw tracker IDs stable across video, crops, predictions and tables."""
    from species import build_species
    tracks = list(csv.DictReader((out / 'tracks.csv').open()))
    predictions = build_species(out, tracks)
    rows = {r['track_id']: r for r in predictions['tracks']}
    gallery = []
    for track in tracks:
        ident = int(track['track_id'])
        prediction = rows[ident]
        species_id = prediction['species_id']
        entry = predictions['catalog'].get(species_id, {})
        gallery.append({**track, 'track_id': ident, 'species_id': species_id,
                        'scientific_name': entry.get('scientific_name', ''),
                        'status': prediction['status'], 'confidence': prediction['confidence'],
                        'reason': prediction['reason'], 'crop': f'fish_{ident:04d}.jpg'})
    (out / 'gallery.json').write_text(json.dumps({'tracks': gallery, 'model': predictions['model'],
        'note': 'Provisional track segments, not unique fish. Species scores require review.'}, allow_nan=False))
    run_info = json.loads((out / 'run.json').read_text())
    if not run_info['total_frames'] or run_info['processed_frames'] != run_info['total_frames']:
        raise RuntimeError('Source frame count does not match processed video')
    (out / 'summary.json').write_text(json.dumps({'jobId': job_id, 'versions': versions,
        'run': run_info, 'speciesModelConfigured': predictions['model'] is not None,
        'trackCount': len(tracks), 'note': 'Track totals are not counts of unique fish.'}, allow_nan=False))
    return gallery


def file_digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def handler(job):
    import torch
    data = job['input']
    settings = validate_input(data)
    if not torch.cuda.is_available(): raise RuntimeError('This endpoint requires a CUDA GPU')
    weights = Path(os.environ.get('OPENFISH_DETECTOR_MODEL', '/models/cfd-complete.pt'))
    expected = os.environ.get('DETECTOR_SHA256', '')
    if not weights.is_file() or not expected: raise RuntimeError('Configure detector weights and DETECTOR_SHA256')
    with weights.open('rb') as stream:
        actual_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual_digest != expected:
        raise RuntimeError('Detector weight checksum does not match the configured release')
    if settings['detector']['name'] != 'yolo': raise ValueError('Cloud release supports YOLO only')
    os.environ['OPENFISH_DETECTOR_MODEL'] = str(weights)
    drive = Drive()
    root = os.environ['GOOGLE_DRIVE_JOB_ROOT_ID']
    if not drive.under(data['folder_id'], root) or not drive.under(data['output_folder_id'], data['folder_id']):
        raise ValueError('Job storage is outside the configured root')
    source_root = os.environ['GOOGLE_DRIVE_SOURCE_ROOT_ID']
    if not (drive.under(data['source_id'], data['folder_id']) or drive.under(data['source_id'], source_root)):
        raise ValueError('Video is outside the configured roots')
    with tempfile.TemporaryDirectory(prefix='openfishgpu-') as temporary:
        work = Path(temporary)
        source = work / 'source.video'
        out = work / 'results'; out.mkdir()
        settings_path = work / 'settings.json'; settings_path.write_text(json.dumps(settings))
        report(job, 'Downloading source video', 3)
        drive.download(data['source_id'], source)
        if source.stat().st_size != data['source_size']: raise RuntimeError('Source video size changed')
        run([sys.executable, 'track_fish.py', '--source', str(source), '--output', str(out),
             '--settings', str(settings_path), '--device', 'cuda:0', '--batch', os.environ.get('GPU_BATCH', '4')], job, 'Detecting and tracking fish', 10)
        run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', str(out / 'annotated_silent.mp4'),
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '22', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
             str(out / 'tracked.mp4')], job, 'Encoding annotated video', 72)
        probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
            '-show_entries', 'stream=nb_read_frames', '-of', 'json', str(out / 'tracked.mp4')]))
        encoded_frames = int(probe['streams'][0]['nb_read_frames'])
        if encoded_frames != json.loads((out / 'run.json').read_text())['processed_frames']:
            raise RuntimeError('Encoded video frame count does not match tracking output')
        report(job, 'Identifying species across track crops', 82)
        gallery = build_results(out, data['job_id'], data['versions'])
        report(job, 'Saving results to Google Drive', 90)
        names = ['tracked.mp4', 'detections.csv', 'tracks.csv', 'run.json', 'settings.json',
                 'species_predictions.json', 'species_tracks.csv', 'summary.json', 'gallery.json']
        names += [r['crop'] for r in gallery if (out / r['crop']).exists()]
        names += [str(p.relative_to(out)) for p in sorted((out / 'similarity_samples').rglob('*.jpg'))]
        assets = []
        for name in names:
            path = out / name
            result = drive.put_file(path, data['output_folder_id'], name=name.replace('/', '__'))
            assets.append({'id': result['id'], 'name': name, 'size': path.stat().st_size,
                           'mimeType': result['mimeType'], 'sha256': file_digest(path)})
        manifest = {'schemaVersion': 1, 'jobId': data['job_id'], 'versions': data['versions'],
                    'assets': assets, 'trackCount': len(gallery)}
        manifest_path = work / 'manifest.json'; manifest_path.write_text(json.dumps(manifest, allow_nan=False))
        manifest_file = drive.put_file(manifest_path, data['output_folder_id'])
        return {'state': 'completed', 'manifestId': manifest_file['id']}

if __name__ == '__main__':
    import runpod
    runpod.serverless.start({'handler': handler})
