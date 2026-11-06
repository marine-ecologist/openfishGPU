const speciesData = JSON.parse(document.getElementById('species-data').textContent);
const pendingReviews = new Map();
for (const row of speciesData.tracks) {
  document.querySelector(`.species-choice[data-track="${row.track_id}"]`).value = row.species_id;
}
for (const button of document.querySelectorAll('.mark-reviewed')) {
  button.addEventListener('click', () => {
    const reviewer = document.getElementById('reviewer').value.trim();
    if (!reviewer) { document.getElementById('review-message').textContent = 'Enter a reviewer name first.'; return; }
    const id = Number(button.dataset.track);
    pendingReviews.set(id, {track_id: id, species_id: document.querySelector(`.species-choice[data-track="${id}"]`).value,
      note: document.querySelector(`.review-note[data-track="${id}"]`).value, reviewer, reviewed_at: new Date().toISOString()});
    document.querySelector(`.review-state[data-track="${id}"]`).textContent = 'Review staged for download';
  });
}
document.getElementById('download-reviews').addEventListener('click', () => {
  if (!pendingReviews.size) { document.getElementById('review-message').textContent = 'Mark at least one track reviewed.'; return; }
  const blob = new Blob([JSON.stringify({dataset_sha256: speciesData.dataset_sha256, events: [...pendingReviews.values()]}, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob); const link = document.createElement('a');
  link.href = url; link.download = 'species_review_import.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  document.getElementById('review-message').textContent = 'Downloaded. Import with species.py --output RUN --reviews FILE, then rebuild the gallery.';
});
