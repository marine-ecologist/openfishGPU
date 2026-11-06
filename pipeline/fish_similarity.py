"""Bounded crop sampling, offline DINOv2 embeddings and deterministic grouping."""
import json
import os
from pathlib import Path
import numpy as np

MODEL = 'facebook/dinov2-small'

class CropSampler:
    """Keep the best confident crop in each of four temporal slots per track."""
    def __init__(self, output, fps):
        self.output = Path(output) / 'similarity_samples'
        self.fps = fps
        self.scores = {}

    def add(self, ident, frame_no, confidence, crop):
        import cv2
        if crop.size == 0 or min(crop.shape[:2]) < 16:
            return
        # Rotating slots retain several views without unbounded disk/memory usage.
        slot = int(frame_no / max(1, self.fps)) % 4
        key = (ident, slot)
        score = confidence * min(crop.shape[0] * crop.shape[1], 250000) ** .5
        if score <= self.scores.get(key, -1):
            return
        folder = self.output / str(ident)
        folder.mkdir(parents=True, exist_ok=True)
        if cv2.imwrite(str(folder / f'{slot}.jpg'), crop):
            self.scores[key] = score


def aggregate(vectors):
    values = np.asarray(vectors, dtype=float)
    if values.ndim != 2 or not len(values) or not np.isfinite(values).all():
        raise ValueError('Invalid embeddings')
    norms = np.linalg.norm(values, axis=1)
    if np.any(norms < 1e-12):
        raise ValueError('Empty embedding')
    mean = (values / norms[:, None]).mean(axis=0)
    norm = np.linalg.norm(mean)
    if norm < 1e-12:
        raise ValueError('Degenerate track embedding')
    return mean / norm


def cluster(embeddings, threshold=.25):
    """Complete-link cosine clustering avoids chains of dissimilar fish."""
    ids = sorted(embeddings)
    if not ids:
        return []
    if len(ids) == 1:
        return [ids]
    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import pdist
    vectors = np.stack([aggregate([embeddings[i]]) for i in ids])
    labels = fcluster(linkage(np.clip(pdist(vectors, metric='cosine'), 0, 2), method='complete'), threshold, criterion='distance')
    groups = {}
    for ident, label in zip(ids, labels):
        groups.setdefault(int(label), []).append(ident)
    return sorted(groups.values(), key=lambda g: g[0])


class DinoEncoder:
    def __init__(self):
        import torch
        from transformers import AutoImageProcessor, AutoModel
        self.torch = torch
        torch.set_num_threads(4)
        local = Path(__file__).resolve().parent / 'models' / 'dinov2-small'
        model = os.environ.get('OPENFISHID_SIMILARITY_MODEL', str(local) if (local / 'config.json').exists() else MODEL)
        self.processor = AutoImageProcessor.from_pretrained(model, local_files_only=True)
        self.model = AutoModel.from_pretrained(model, local_files_only=True).eval()

    def __call__(self, paths):
        from PIL import Image
        images = []
        for path in paths:
            try:
                with Image.open(path) as image:
                    images.append(image.convert('RGB'))
            except (OSError, ValueError):
                continue
        if not images:
            raise ValueError('No readable crops')
        with self.torch.inference_mode():
            inputs = self.processor(images=images, return_tensors='pt')
            return self.model(**inputs).last_hidden_state[:, 0].cpu().numpy()


def build_similarity(out, tracks, encoder_factory=DinoEncoder):
    out = Path(out)
    result = dict(version=1, model=os.environ.get('OPENFISHID_SIMILARITY_MODEL', MODEL), threshold=.25, status='unavailable', groups=[], embeddings={}, missing=[], message='')
    try:
        encoder = encoder_factory() if tracks else None
        for track in tracks:
            ident = int(track['track_id'])
            raw = track.get('raw_tracker_id', ident)
            paths = sorted((out / 'similarity_samples' / str(raw)).glob('*.jpg'))
            if not paths:
                paths = [out / 'crops' / f'fish_{ident:04d}.jpg']
            try:
                result['embeddings'][ident] = aggregate(encoder(paths)).tolist()
            except Exception:
                result['missing'].append(ident)
        result['groups'] = cluster(result['embeddings'])
        result['status'] = 'ready' if result['embeddings'] else 'unavailable'
        result['message'] = 'Groups reflect appearance, not species or unique individuals.' if result['embeddings'] else 'Visual similarity unavailable: no usable fish embeddings.'
    except Exception as exc:
        result['missing'] = [int(t['track_id']) for t in tracks]
        result['message'] = 'Visual similarity unavailable. Install/cache the DINOv2 model locally, then rebuild the gallery.'
        result['error'] = f'{type(exc).__name__}: {exc}'
    (out / 'similarity.json').write_text(json.dumps(result, indent=2))
    return result
