"""Portable Fish Gallery; can also rebuild existing completed runs."""
import base64
import csv
import html
import json
from pathlib import Path
from fish_similarity import build_similarity
from species import build_species, export_species


def write_gallery(out, tracks, run, species_result=None, similarity_result=None):
    out = Path(out)
    similarity = similarity_result if similarity_result is not None else build_similarity(out, tracks)
    policy_path = out / 'species_predictions.json'
    policy = json.loads(policy_path.read_text()) if policy_path.exists() else {}
    species = species_result if species_result is not None else build_species(out, tracks, threshold=policy.get('threshold', .8), margin=policy.get('margin', .2))
    species_rows = {r["track_id"]: r for r in export_species(out, species)}
    ordered = sorted(tracks, key=lambda t: (float(t['first_s']), int(t['track_id'])))
    group_by_id = {ident: n for n, group in enumerate(similarity['groups'], 1) for ident in group}
    cards = []
    for track in ordered:
        ident = int(track['track_id'])
        crop = out / 'crops' / f'fish_{ident:04d}.jpg'
        try:
            image = '<img alt="Fish crop" src="data:image/jpeg;base64,' + base64.b64encode(crop.read_bytes()).decode() + '">'
        except OSError:
            image = '<p>Crop unavailable</p>'
        detail = html.escape(f"{track['first_s']}–{track['last_s']} seconds · {track['detections']} detections · peak confidence {track['best_confidence']}")
        if int(track['detections']) < 15:
            detail += ' · brief track'
        review = species_rows[ident]
        prediction = next(r for r in species['tracks'] if r['track_id'] == ident)
        ranked = sorted(prediction['scores'], key=lambda k: (-prediction['scores'][k], k))[:3]
        suggestions = ', '.join(f"{species['catalog'].get(k, {}).get('scientific_name', k)} {prediction['scores'][k]:.3f}" for k in ranked)
        views = ''
        for sample in prediction['samples']:
            try:
                data = base64.b64encode((out / sample['path']).read_bytes()).decode()
                views += f'<img alt="Additional track view" src="data:image/jpeg;base64,{data}">'
            except OSError:
                pass
        options = '<option value="unidentified">Unidentified / unknown</option>' + ''.join(f'<option value="{html.escape(k, quote=True)}">{html.escape(v["scientific_name"])}</option>' for k, v in sorted(species['catalog'].items()))
        control = f'<p class="suggestions"><strong>Model suggestions</strong><br>{html.escape(suggestions or prediction["reason"])}</p><details><summary>Model suggestions and track views</summary><p>{html.escape(suggestions or prediction["reason"])}</p>{views}</details><p>{html.escape(species["catalog"].get(review["species_id"], {}).get("scientific_name", review["species_id"]))} · {html.escape(review["status"])} · model score {format(review["model_confidence"], '.3f') if review["model_confidence"] is not None else "unavailable"}</p><label>Review species <select class="species-choice" data-track="{ident}">{options}</select></label><label>Review note <input class="review-note" data-track="{ident}"></label><button type="button" class="mark-reviewed" data-track="{ident}">Mark reviewed</button><span class="review-state" data-track="{ident}"></span>'
        cards.append(f'<article data-group="{group_by_id.get(ident, 0)}"><h2>Fish {ident:04d}</h2>{image}<p>{detail}</p>{control}</article>')
    disabled = '' if similarity['status'] == 'ready' else ' disabled'
    page = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Fish Gallery</title><style>
body{font:16px system-ui;background:#eef5f4;color:#143132;margin:32px}main{max-width:1400px;margin:auto}p{line-height:1.6}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:20px}article{background:white;padding:18px;border-radius:12px}h2{font-size:20px}img{width:100%;height:210px;object-fit:contain;background:#102a2b}.muted{color:#536d6e;font-size:14px}select{font:inherit;padding:8px}section{margin:24px 0}article{min-width:0}article select,article input{max-width:100%;box-sizing:border-box;width:100%;margin:6px 0}button,input{font:inherit;padding:8px}button{cursor:pointer}.suggestions{font-size:14px}.review-tools{background:white;padding:16px;border-radius:12px;margin:16px 0}</style></head><body><main><h1>Fish Gallery</h1>'''
    page += f'<p>{len(tracks)} provisional tracks · {run["total_frames"]/run["source_fps"]:.3f} seconds · {html.escape(run["model"])} · all {run["total_frames"]:,} frames processed.</p>'
    page += '<p>IDs identify continuous sightings. Occlusion and re-entry can create duplicate or swapped IDs. This is not a count of unique fish. Similar appearance does not establish species or individual identity.</p>'
    page += '<div class="review-tools"><p>Species scores are model outputs, not measured accuracy. Choose a species or Unidentified, then mark each track reviewed. Download reviews to preserve your edits.</p><label>Reviewer <input id="reviewer"></label><button id="download-reviews">Download reviews</button><p id="review-message" role="status"></p></div>'
    if (species.get('model') or {}).get('backend') == 'fishial_torchscript':
        page += '<p role="status"><strong>Experimental Fishial suggestions: unreliable in the Caribbean pilot. Verify every assignment before use.</strong></p>'
    if run.get('species_trial_source_run'):
        page += '<p>Review subset from your footage. Species suggestions have not been verified.</p>'
    page += f'<label for="sort-order">Sort order </label><select id="sort-order"><option value="chronological">Chronological</option><option value="similarity"{disabled}>Visual similarity</option></select><p role="status">{html.escape(similarity["message"])}</p><div id="gallery"><div class="grid">' + ''.join(cards) + '</div></div>'

    page += '<script type="application/json" id="species-data">' + json.dumps(dict(dataset_sha256=species['dataset_sha256'], tracks=list(species_rows.values()))).replace('<', r'\u003c') + '</script>'
    page += '<script>' + (Path(__file__).parent / 'species_review.js').read_text() + '</script>'
    page += '''</main><script>
const gallery = document.getElementById('gallery');
const cards = Array.from(gallery.querySelectorAll('article'));
document.getElementById('sort-order').addEventListener('change', event => {
  gallery.replaceChildren();
  if (event.target.value === 'chronological') {
    const grid = document.createElement('div'); grid.className = 'grid';
    grid.append(...cards); gallery.append(grid); return;
  }
  const groups = new Map();
  for (const card of cards) {
    const key = Number(card.dataset.group);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(card);
  }
  for (const key of Array.from(groups.keys()).sort((a,b) => (a===0)-(b===0) || a-b)) {
    const section = document.createElement('section');
    const heading = document.createElement('h2');
    heading.textContent = key ? `Appearance group ${key}` : 'Ungrouped — embedding unavailable';
    const grid = document.createElement('div'); grid.className = 'grid';
    grid.append(...groups.get(key)); section.append(heading, grid); gallery.append(section);
  }
});
</script></body></html>'''
    (out / 'fish_ID_gallery.html').write_text(page)
    return similarity


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    out = Path(args.output)
    with (out / 'tracks.csv').open() as stream:
        tracks = list(csv.DictReader(stream))
    write_gallery(out, tracks, json.loads((out / 'run.json').read_text()))
