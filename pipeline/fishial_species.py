"""Fishial v0.10.2 TorchScript adapter using the bundle's own class mapping.

Preprocessing and scoring follow the inference.py distributed with that bundle:
RGB, OpenCV linear resize, ImageNet normalization, softmax of ArcFace logits.
Cosine scores are available separately; they are never converted to probabilities.
"""
import json
from pathlib import Path


class FishialClassifier:
    def __init__(self, folder):
        import torch
        self.torch = torch
        self.folder = Path(folder)
        self.device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
        torch.set_num_threads(4)
        self.model = torch.jit.load(str(self.folder/'model.pt'), map_location=self.device).eval()
        self.manifest = json.loads((self.folder/'species_manifest.json').read_text())
        mapping = json.loads(bytes(self.model.class_mapping_json_bytes.cpu().tolist()))
        self.labels = [mapping[str(i)]['label'].lower().replace(' ', '_') for i in range(len(mapping))]
        if self.labels != self.manifest['labels']:
            raise ValueError('Manifest differs from embedded model class mapping')
        self.mean = torch.tensor([.485, .456, .406]).reshape(3,1,1).to(self.device)
        self.std = torch.tensor([.229, .224, .225]).reshape(3,1,1).to(self.device)
        self.centroids = torch.nn.functional.normalize(self.model.natural_centroids.float(), dim=1)
        self.centroid_labels = self.model.natural_labels.long()
        self.cache = {}

    def score(self, path):
        import cv2
        from PIL import Image
        import numpy as np
        torch = self.torch
        key = str(Path(path).resolve())
        if key in self.cache:
            return self.cache[key]
        with Image.open(path) as image:
            rgb = np.array(image.convert('RGB'))
        height, width = self.manifest['input_size']
        rgb = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_LINEAR)
        tensor = torch.from_numpy(rgb.transpose(2,0,1).copy()).float()/255
        tensor = ((tensor-self.mean)/self.std).unsqueeze(0)
        with torch.inference_mode():
            embedding, logits = self.model(tensor.to(self.device))
            if logits.shape != (1,len(self.labels)):
                raise ValueError('Unexpected Fishial output shape')
            probabilities = logits.softmax(-1)[0]
            embedding = torch.nn.functional.normalize(embedding, dim=1)
            similarities = (embedding @ self.centroids.T)[0]
            cosine = torch.full((len(self.labels),), -1., device=self.device)
            cosine.scatter_reduce_(0, self.centroid_labels, similarities, reduce='amax', include_self=False)
        result = dict(softmax=dict(zip(self.labels, probabilities.tolist())),
                      cosine=dict(zip(self.labels, cosine.tolist())))
        self.cache[key] = result
        return result

    def __call__(self, path):
        return self.score(path)['softmax']
