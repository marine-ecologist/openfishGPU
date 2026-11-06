import hashlib
import json
import sys
import types
import uuid
from pathlib import Path
import pytest
from worker import handler as worker


def data():
    return {'schema_version': 1, 'job_id': str(uuid.uuid4()), 'source_id': 'video123', 'source_size': 5,
            'folder_id': 'folder123', 'output_folder_id': 'output123', 'settings': {},
            'versions': json.loads((worker.ROOT / 'versions.json').read_text())}


def test_worker_rejects_schema_and_version_mismatch():
    value = data(); value['schema_version'] = 9
    with pytest.raises(ValueError, match='schema'): worker.validate_input(value)
    value = data(); value['versions']['openfishGPU'] = 'different'
    with pytest.raises(ValueError, match='versions'): worker.validate_input(value)


def test_worker_persists_complete_manifest(tmp_path, monkeypatch):
    value = data(); calls = []; uploads = {}
    monkeypatch.setitem(sys.modules, 'torch', types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True)))
    monkeypatch.delenv('OPENFISHID_SPECIES_MODEL', raising=False)
    model = tmp_path / 'weights.pt'; model.write_bytes(b'test weights')
    monkeypatch.setenv('OPENFISH_DETECTOR_MODEL', str(model))
    monkeypatch.setenv('DETECTOR_SHA256', hashlib.sha256(model.read_bytes()).hexdigest())
    monkeypatch.setenv('GOOGLE_DRIVE_JOB_ROOT_ID', 'jobsRoot')
    monkeypatch.setenv('GOOGLE_DRIVE_SOURCE_ROOT_ID', 'sourceRoot')
    monkeypatch.setattr(worker, 'report', lambda job, stage, progress: calls.append((stage, progress)))
    monkeypatch.setattr(worker.subprocess, 'check_output', lambda *args: b'{"streams":[{"nb_read_frames":"3"}]}')
    class Drive:
        def under(self, ident, root): return True
        def download(self, ident, destination): destination.write_bytes(b'video')
        def put_file(self, path, parent, name=None):
            key = name or path.name; uploads[key] = path.read_bytes()
            return {'id': 'asset_' + str(len(uploads)), 'mimeType': 'application/octet-stream'}
    monkeypatch.setattr(worker, 'Drive', Drive)
    def run(command, job, stage, progress):
        if 'track_fish.py' in command:
            out = Path(command[command.index('--output') + 1])
            (out / 'tracks.csv').write_text('track_id,first_s,last_s,detections,best_confidence,review_status\n7,0,1,3,.9,unreviewed\n')
            (out / 'detections.csv').write_text('frame,track_id\n0,7\n')
            (out / 'run.json').write_text(json.dumps({'processed_frames': 3, 'total_frames': 3, 'source_fps': 3, 'model': 'test-detector'}))
            (out / 'settings.json').write_text('{}')
            (out / 'fish_0007.jpg').write_bytes(b'crop')
            (out / 'annotated_silent.mp4').write_bytes(b'frames')
            sample = out / 'similarity_samples/7'; sample.mkdir(parents=True)
            (sample / '0.jpg').write_bytes(b'view')
        else: Path(command[-1]).write_bytes(b'encoded video')
    monkeypatch.setattr(worker, 'run', run)
    result = worker.handler({'input': value})
    assert result['state'] == 'completed'
    assert 'manifest.json' in uploads
    assert 'fish_ID_gallery.html' in uploads
    assert b'Visual similarity' in uploads['fish_ID_gallery.html']
    assert 'similarity.json' in uploads
    manifest = json.loads(uploads['manifest.json'])
    assert manifest['jobId'] == value['job_id']
    assert manifest['trackCount'] == 1
    assert all(len(a['sha256']) == 64 for a in manifest['assets'])
    assert 'similarity_samples__7__0.jpg' in uploads
    gallery = json.loads(uploads['gallery.json'])
    assert gallery['tracks'][0]['track_id'] == 7
    assert gallery['tracks'][0]['species_id'] == 'unidentified'
    assert calls[-1][0] == 'Saving results to Google Drive'


def test_cpu_worker_fails_before_cloud_access(monkeypatch):
    monkeypatch.setitem(sys.modules, 'torch', types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False)))
    with pytest.raises(RuntimeError, match='CUDA'): worker.handler({'input': data()})


def test_portable_html_retains_visual_groups(tmp_path, monkeypatch):
    import numpy as np
    import fish_similarity
    monkeypatch.delenv('OPENFISHID_SPECIES_MODEL', raising=False)
    original = fish_similarity.build_similarity
    class Encoder:
        def __call__(self, paths):
            ident = int(paths[0].stem.split('_')[-1])
            return np.array([[1., 0.] if ident in (1, 2) else [0., 1.]])
    monkeypatch.setattr(fish_similarity, 'build_similarity', lambda out, tracks: original(out, tracks, encoder_factory=Encoder))
    (tmp_path / 'tracks.csv').write_text('track_id,first_s,last_s,detections,best_confidence,review_status\n1,0,1,30,.9,unreviewed\n2,1,2,30,.9,unreviewed\n3,2,3,30,.9,unreviewed\n')
    (tmp_path / 'run.json').write_text(json.dumps({'processed_frames': 90, 'total_frames': 90, 'source_fps': 30, 'model': 'fixture'}))
    for ident in (1, 2, 3): (tmp_path / f'fish_{ident:04d}.jpg').write_bytes(b'fixture-crop')
    worker.build_results(tmp_path, 'test-job', {})
    similarity = json.loads((tmp_path / 'similarity.json').read_text())
    assert similarity['groups'] == [[1, 2], [3]]
    page = (tmp_path / 'fish_ID_gallery.html').read_text()
    assert '<option value="similarity">Visual similarity</option>' in page
    assert 'data-group="1"' in page and 'data-group="2"' in page
    assert 'data:image/jpeg;base64,' in page
    assert 'Chronological' in page and 'Appearance group' in page
