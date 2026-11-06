"""Exercise real multi-view species aggregation without installing GPU packages."""
import csv
import importlib.util
import json
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('species', ROOT / 'pipeline/species.py')
species = importlib.util.module_from_spec(spec); spec.loader.exec_module(species)

@pytest.fixture
def track(tmp_path):
    (tmp_path / 'tracks.csv').write_text('track_id\n7\n')
    (tmp_path / 'run.json').write_text('{}')
    sample = tmp_path / 'similarity_samples/7'; sample.mkdir(parents=True)
    for i in range(4): (sample / f'{i}.jpg').write_bytes(b'crop')
    return tmp_path

class Classifier:
    labels = ['species_a', 'species_b']
    manifest = {'model_id': 'test-model', 'revision': 'test-revision', 'catalog': {'species_a': {'scientific_name': 'A'}, 'species_b': {'scientific_name': 'B'}}}
    def __call__(self, path):
        return {'species_a': .95, 'species_b': .05}

def test_track_aggregates_four_views(track):
    result = species.build_species(track, [{'track_id': '7'}], classifier=Classifier())
    row = result['tracks'][0]
    assert row['species_id'] == 'species_a'
    assert row['status'] == 'provisional'
    assert len(row['samples']) == 4
    assert row['confidence'] == pytest.approx(.95)
    assert (track / 'species_tracks.csv').exists()

def test_no_model_stays_unidentified(track, monkeypatch):
    monkeypatch.delenv('OPENFISHID_SPECIES_MODEL', raising=False)
    row = species.build_species(track, [{'track_id': '7'}])['tracks'][0]
    assert row['species_id'] == 'unidentified'
    assert row['reason'] == 'model_unavailable'

def test_ambiguous_predictions_abstain(track):
    class Ambiguous(Classifier):
        def __call__(self, path): return {'species_a': .51, 'species_b': .49}
    row = species.build_species(track, [{'track_id': '7'}], classifier=Ambiguous())['tracks'][0]
    assert row['species_id'] == 'unidentified'
    assert row['reason'] == 'low_score_or_ambiguous'
