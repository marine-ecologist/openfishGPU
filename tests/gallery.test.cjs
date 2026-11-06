const { test } = require('node:test');
const assert = require('node:assert/strict');
const { sections } = require('../web/gallery.js');
const tracks = [{ track_id: 3, first_s: 2 }, { track_id: 2, first_s: 1 }, { track_id: 1, first_s: 0 }, { track_id: 4, first_s: 3 }];
const similarity = { status: 'ready', groups: [[1, 3], [2]] };
test('chronological view orders sightings by time', () => {
  assert.deepEqual(sections(tracks, similarity, 'chronological')[0].tracks.map(t => t.track_id), [1, 2, 3, 4]);
});
test('similar appearances stay together and missing embeddings remain visible', () => {
  const groups = sections(tracks, similarity, 'similarity');
  assert.deepEqual(groups.map(g => g.tracks.map(t => t.track_id)), [[1, 3], [2], [4]]);
  assert.match(groups[2].title, /Ungrouped/);
});
test('search subsets retain original group names', () => {
  assert.equal(sections(tracks.filter(t => t.track_id === 2), similarity, 'similarity')[0].title, 'Appearance group 2');
});
test('older jobs without groups keep chronological review', () => {
  assert.equal(sections(tracks, null, 'similarity')[0].title, '');
  assert.deepEqual(sections([], similarity, 'similarity'), []);
});
