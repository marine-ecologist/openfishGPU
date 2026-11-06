"""Offline species scoring, track aggregation, review audit and reproducible exports."""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dataset_identity(out):
    out = Path(out)
    # Bind corrections to both the track table and its source/run metadata.
    return hashlib.sha256((digest(out / 'tracks.csv') + (digest(out / 'run.json') if (out / 'run.json').exists() else '')).encode()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


class LocalClassifier:
    """A local Hugging Face image classifier; never downloads model files."""
    def __init__(self, folder):
        from transformers import AutoImageProcessor, AutoModelForImageClassification
        self.folder = Path(folder)
        self.manifest = json.loads((self.folder / 'species_manifest.json').read_text())
        self.labels = self.manifest['labels']
        if not self.manifest.get('model_id') or not self.manifest.get('revision'):
            raise ValueError('Manifest requires model_id and revision')
        if not self.labels or len(set(self.labels)) != len(self.labels):
            raise ValueError('Model labels must be unique catalogue IDs')
        self.processor = AutoImageProcessor.from_pretrained(folder, local_files_only=True)
        import torch
        self.device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
        self.model = AutoModelForImageClassification.from_pretrained(folder, local_files_only=True).to(self.device).eval()
        if self.model.config.num_labels != len(self.labels):
            raise ValueError('Manifest labels must match logit order and count')

    def __call__(self, path):
        import torch
        from PIL import Image
        with Image.open(path) as image, torch.inference_mode():
            inputs = self.processor(images=image.convert('RGB'), return_tensors='pt').to(self.device)
            return dict(zip(self.labels, self.model(**inputs).logits.softmax(-1)[0].tolist()))


def aggregate_scores(scores, labels):
    """Equal-weight mean across valid views. Scores are not calibrated accuracy."""
    if not scores:
        return {}
    for row in scores:
        if set(row) != set(labels) or any(not math.isfinite(v) or v < 0 or v > 1 for v in row.values()):
            raise ValueError('Invalid class scores')
        if not math.isclose(sum(row.values()), 1, abs_tol=1e-4):
            raise ValueError('Class scores must sum to one')
    return {label: sum(row[label] for row in scores) / len(scores) for label in sorted(labels)}


def build_species(out, tracks, classifier=None, threshold=.8, margin=.2):
    out = Path(out)
    if not 0 <= threshold <= 1 or not 0 <= margin <= 1:
        raise ValueError('Thresholds must be in [0, 1]')
    identity = dataset_identity(out) if (out / 'tracks.csv').exists() else hashlib.sha256(json.dumps(tracks, sort_keys=True).encode()).hexdigest()
    result = dict(schema_version=1, dataset_sha256=identity, aggregation='equal_weight_mean', threshold=threshold, margin=margin, confidence_note='Model scores, not measured accuracy or calibrated probabilities.', model=None, catalog={}, tracks=[])
    result['catalog'] = json.loads(Path(os.environ.get('OPENFISHID_SPECIES_CATALOG', Path(__file__).parent / 'catalogs/caribbean_starter.json')).read_text())
    setup_error = None
    folder = os.environ.get('OPENFISHID_SPECIES_MODEL')
    if classifier is None and folder:
        try:
            manifest_path = Path(folder) / 'species_manifest.json'
            manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
            if manifest.get('backend') == 'fishial_torchscript':
                from fishial_species import FishialClassifier
                classifier = FishialClassifier(folder)
            else:
                classifier = LocalClassifier(folder)
        except Exception as exc:
            setup_error = f'{type(exc).__name__}: {exc}'
    if classifier is not None:
        manifest = classifier.manifest
        catalog = manifest['catalog']
        if set(classifier.labels) - set(catalog) or 'unidentified' in catalog:
            raise ValueError('Every output label requires a catalogue entry; unidentified is reserved')
        result['catalog'].update(catalog)
        result['model'] = manifest
        if folder:
            result['model_files'] = {str(p.relative_to(folder)): digest(p) for p in sorted(Path(folder).rglob('*')) if p.is_file()}
    for track in sorted(tracks, key=lambda t: int(t['track_id'])):
        ident = int(track['track_id'])
        row = dict(track_id=ident, species_id='unidentified', status='needs_review', reason='model_unavailable', confidence=None, scores={}, samples=[], errors=[])
        if setup_error:
            row['errors'].append(setup_error)
        if classifier is not None:
            raw = track.get('raw_tracker_id') or ident
            paths = sorted((out / 'similarity_samples' / str(raw)).glob('*.jpg'))[:4]
            if not paths:
                paths = [out / 'crops' / f'fish_{ident:04d}.jpg']
            scores = []
            for path in paths:
                try:
                    prediction = classifier(path)
                    aggregate_scores([prediction], classifier.labels)
                    scores.append(prediction)
                    row['samples'].append(dict(path=str(path.relative_to(out)), sha256=digest(path), scores=prediction))
                except Exception as exc:
                    # Remove a prediction if the crop cannot be fingerprinted.
                    if len(scores) > len(row['samples']):
                        scores.pop()
                    row['errors'].append(f'{path.name}: {type(exc).__name__}: {exc}')
            row['scores'] = aggregate_scores(scores, classifier.labels)
            row['reason'] = 'no_usable_crops'
            if row['scores']:
                ranked = sorted(row['scores'], key=lambda k: (-row['scores'][k], k))
                best = ranked[0]
                row['confidence'] = row['scores'][best]
                row['candidate_id'] = best
                gap = row['confidence'] - (row['scores'][ranked[1]] if len(ranked) > 1 else 0)
                accepted = row['confidence'] >= threshold and gap >= margin
                row['reason'] = 'threshold_passed' if accepted else 'low_score_or_ambiguous'
                if accepted:
                    row['species_id'] = best
                    row['status'] = 'provisional'
        result['tracks'].append(row)
    # Review history is separate and survives classifier reruns with the same track table.
    reviews = out / 'species_reviews.json'
    if reviews.exists():
        audit = json.loads(reviews.read_text())
        if audit['dataset_sha256'] != identity:
            raise ValueError('Review history belongs to a different track table')
        for event in audit['events']:
            if event['species_id'] != 'unidentified' and event['species_id'] not in result['catalog']:
                result['catalog'][event['species_id']] = event['catalog_entry']
    save(out / 'species_predictions.json', result)
    export_species(out, result)
    return result


def export_species(out, predictions):
    out = Path(out)
    audit_path = out / 'species_reviews.json'
    audit = json.loads(audit_path.read_text()) if audit_path.exists() else dict(dataset_sha256=predictions['dataset_sha256'], events=[])
    if audit['dataset_sha256'] != predictions['dataset_sha256']:
        raise ValueError('Review history belongs to a different track table')
    latest = {e['track_id']: e for e in audit['events']}
    rows = []
    for prediction in predictions['tracks']:
        review = latest.get(prediction['track_id'])
        ident = review['species_id'] if review else prediction['species_id']
        rows.append(dict(track_id=prediction['track_id'], species_id=ident, scientific_name=predictions['catalog'].get(ident, {}).get('scientific_name', ''), status='reviewed' if review else prediction['status'], model_species_id=prediction['species_id'], model_confidence=prediction['confidence'], reason=prediction['reason'], reviewer=review['reviewer'] if review else '', reviewed_at=review['reviewed_at'] if review else '', note=review['note'] if review else ''))
    with (out / 'species_tracks.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['track_id', 'species_id', 'scientific_name', 'status', 'model_species_id', 'model_confidence', 'reason', 'reviewer', 'reviewed_at', 'note'])
        writer.writeheader()
        writer.writerows(rows)
    save(out / 'species_export.json', dict(predictions=predictions, review_history=audit, tracks=rows))
    return rows


def apply_reviews(out, payload):
    from datetime import datetime
    out = Path(out)
    predictions = json.loads((out / 'species_predictions.json').read_text())
    if dataset_identity(out) != predictions['dataset_sha256'] or payload['dataset_sha256'] != predictions['dataset_sha256']:
        raise ValueError('Review file belongs to a different track table')
    ids = {r['track_id'] for r in predictions['tracks']}
    events = payload['events']
    if not events:
        raise ValueError('No reviews supplied')
    validated = []
    for event in events:
        if type(event['track_id']) is not int or event['track_id'] not in ids or event['species_id'] not in {*predictions['catalog'], 'unidentified'}:
            raise ValueError('Unknown track or species')
        if not event['reviewer'].strip() or not event['reviewed_at'].strip():
            raise ValueError('Reviewer and timestamp are required')
        stamp = datetime.fromisoformat(event['reviewed_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Review timestamp requires timezone')
        validated.append(dict(track_id=event['track_id'], species_id=event['species_id'], reviewer=event['reviewer'], reviewed_at=event['reviewed_at'], note=str(event.get('note', '')), catalog_entry=predictions['catalog'].get(event['species_id'])))
    path = out / 'species_reviews.json'
    audit = json.loads(path.read_text()) if path.exists() else dict(dataset_sha256=predictions['dataset_sha256'], events=[])
    if audit['dataset_sha256'] != predictions['dataset_sha256']:
        raise ValueError('Stale review history')
    for event in validated:
        if event not in audit['events']:
            audit['events'].append(event)
    save(path, audit)
    export_species(out, predictions)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--reviews')
    parser.add_argument('--threshold', type=float, default=.8)
    parser.add_argument('--margin', type=float, default=.2)
    args = parser.parse_args()
    out = Path(args.output)
    if args.reviews:
        apply_reviews(out, json.loads(Path(args.reviews).read_text()))
    else:
        with (out / 'tracks.csv').open() as stream:
            build_species(out, list(csv.DictReader(stream)), threshold=args.threshold, margin=args.margin)
