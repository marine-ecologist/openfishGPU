/* Shared ordering for the web gallery. Group IDs refer to appearance only. */
(function (root) {
  function sections(tracks, similarity, order) {
    const chronological = [...tracks].sort((a, b) => Number(a.first_s) - Number(b.first_s) || Number(a.track_id) - Number(b.track_id));
    if (order !== 'similarity' || similarity?.status !== 'ready') return [{ title: '', tracks: chronological }];
    const membership = new Map();
    (similarity.groups || []).forEach((group, index) => group.forEach(id => membership.set(Number(id), index + 1)));
    const groups = new Map();
    for (const track of chronological) {
      const group = membership.get(Number(track.track_id)) || 0;
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push(track);
    }
    return [...groups.keys()].sort((a, b) => (a === 0) - (b === 0) || a - b).map(group => ({
      title: group ? `Appearance group ${group}` : 'Ungrouped · similarity unavailable', tracks: groups.get(group)
    }));
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { sections };
  else root.OpenfishGallery = { sections };
})(globalThis);
