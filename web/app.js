'use strict';
const $ = id => document.getElementById(id);
let mode = 'upload', selectedDrive = null, currentJob = null, pollTimer = null, galleryRows = [], folderPage = null, currentFolder = null, historyOffset = 0, busy = false;
const show = (id, visible = true) => $(id).hidden = !visible;
function notice(message) { $('notice').textContent = message; show('notice', !!message); }
function element(tag, text, className) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (className) e.className = className; return e; }
async function api(path, options = {}) {
  const response = await fetch('/api' + path, { credentials: 'same-origin', ...options, headers: { 'Content-Type': 'application/json', ...options.headers } });
  if (response.status === 401) { show('login'); show('workspace', false); show('logout', false); clearTimeout(pollTimer); }
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Please check the entered values.');
  return result;
}
const post = (path, body = {}) => api(path, { method: 'POST', body: JSON.stringify(body) });
async function enter() {
  const config = await api('/config');
  show('login', false); show('workspace'); show('logout');
  $('version').textContent = 'openfishGPU ' + config.versions.openfishGPU;
  await history();
}
$('login-form').addEventListener('submit', async e => {
  e.preventDefault(); const button = e.submitter; button.disabled = true;
  try { await post('/login', { password: $('password').value }); $('password').value = ''; notice(''); await enter(); }
  catch (error) { notice(error.message); } finally { button.disabled = false; }
});
$('logout').onclick = async () => { try { await post('/logout'); location.reload(); } catch (e) { notice(e.message); } };
async function setMode(value) {
  mode = value; $('upload-tab').classList.toggle('selected', mode === 'upload'); $('drive-tab').classList.toggle('selected', mode === 'drive');
  show('upload-pane', mode === 'upload'); show('drive-pane', mode === 'drive');
  if (mode === 'drive') { try { await browse(); } catch (e) { notice(e.message); } }
}
$('upload-tab').onclick = () => setMode('upload'); $('drive-tab').onclick = () => setMode('drive');
$('video').onchange = () => {
  const file = $('video').files[0]; $('file-label').textContent = file ? file.name : 'Choose underwater footage';
  if (file && !$('job-name').value) $('job-name').value = file.name.replace(/\.[^.]+$/, '').slice(0, 80);
};
async function browse(folder = null, append = false) {
  currentFolder = folder;
  const query = new URLSearchParams(); if (folder) query.set('folder', folder); if (append && folderPage) query.set('page', folderPage);
  const result = await api('/drive?' + query);
  if (!append) $('drive-list').replaceChildren();
  folderPage = result.nextPageToken; show('drive-more', !!folderPage);
  if (!result.files.length && !append) $('drive-list').append(element('p', 'No videos or folders here.', 'empty'));
  for (const file of result.files) {
    const folderItem = file.mimeType === 'application/vnd.google-apps.folder';
    const button = element('button', (folderItem ? '↳ ' : '▷ ') + file.name); button.type = 'button';
    button.onclick = async () => {
      if (folderItem) { try { $('folder-label').textContent = file.name; await browse(file.id); } catch (e) { notice(e.message); } }
      else { selectedDrive = file; $('selected-drive').textContent = 'Selected: ' + file.name; if (!$('job-name').value) $('job-name').value = file.name.slice(0, 80); for (const b of $('drive-list').children) b.classList.remove('selected'); button.classList.add('selected'); }
    };
    $('drive-list').append(button);
  }
}
$('drive-back').onclick = () => { $('folder-label').textContent = 'Video library'; browse().catch(e => notice(e.message)); };
$('drive-more').onclick = () => browse(currentFolder, true).catch(e => notice(e.message));

async function upload(url, file) {
  const chunkSize = 8 * 1024 * 1024;
  let offset = 0, failures = 0;
  while (offset < file.size) {
    const end = Math.min(offset + chunkSize, file.size);
    try {
      const response = await fetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/octet-stream', 'Content-Range': `bytes ${offset}-${end - 1}/${file.size}` }, body: file.slice(offset, end) });
      if (response.ok) { offset = file.size; break; }
      if (response.status !== 308) throw new Error('Drive upload failed. Reselect the video and retry from the job detail.');
      const range = response.headers.get('Range');
      if (range) offset = Number(range.split('-')[1]) + 1; else offset = end;
      failures = 0;
    } catch (error) {
      if (++failures > 3) throw error;
      await new Promise(resolve => setTimeout(resolve, 1000 * failures));
      const probe = await fetch(url, { method: 'PUT', headers: { 'Content-Range': `bytes */${file.size}` } });
      if (probe.ok) { offset = file.size; break; }
      if (probe.status !== 308) throw error;
      const range = probe.headers.get('Range'); offset = range ? Number(range.split('-')[1]) + 1 : 0;
    }
    $('submit').textContent = `Uploading to Drive · ${Math.round(offset / file.size * 100)}%`;
  }
}
let pendingUpload = null;
$('job-form').onsubmit = async e => {
  e.preventDefault(); if (busy) return; busy = true; $('submit').disabled = true; notice('');
  try {
    const file = $('video').files[0];
    if (mode === 'upload' && !file) throw new Error('Choose a video to upload.');
    if (mode === 'drive' && !selectedDrive) throw new Error('Select a Drive video first.');
    const body = { name: $('job-name').value, imageSize: Number($('resolution').value), ...(mode === 'drive' ? { driveFileId: selectedDrive.id } : { fileName: file.name, size: file.size }) };
    const result = await post('/jobs', body); currentJob = result.job;
    if (result.uploadUrl) { pendingUpload = { id: result.job.id, url: result.uploadUrl, file }; await upload(result.uploadUrl, file); }
    await post(`/jobs/${result.job.id}/start`); pendingUpload = null;
    await history(); await detail(result.job.id); $('detail').scrollIntoView({ behavior: 'smooth' });
  } catch (error) { notice(error.message); await history().catch(() => {}); if (currentJob) await detail(currentJob.id).catch(() => {}); }
  finally { busy = false; $('submit').disabled = false; $('submit').replaceChildren(document.createTextNode('Start GPU analysis '), element('span', '→')); }
};
async function history(append = false) {
  if (!append) historyOffset = 0;
  const result = await api('/jobs?offset=' + historyOffset);
  if (!append) $('job-list').replaceChildren();
  if (!result.jobs.length && !append) $('job-list').append(element('div', 'Your next discovery starts here. Submit a video to begin.', 'empty'));
  for (const job of result.jobs) {
    const button = element('button', undefined, 'job-row'); const text = element('div');
    text.append(element('strong', job.name), element('small', new Date(job.createdAt).toLocaleString() + ' · ' + job.fileName));
    button.append(text, element('span', job.state.replaceAll('_', ' '), 'badge ' + job.state));
    button.onclick = () => detail(job.id).then(() => $('detail').scrollIntoView({ behavior: 'smooth' })).catch(e => notice(e.message));
    $('job-list').append(button);
  }
  historyOffset += result.jobs.length; show('history-more', result.jobs.length === 50);
}
$('refresh').onclick = () => history().catch(e => notice(e.message));
$('history-more').onclick = () => history(true).catch(e => notice(e.message));
function assetUrl(job, asset) { return `/api/jobs/${encodeURIComponent(job.id)}/assets/${encodeURIComponent(asset.id)}`; }
async function detail(id) {
  clearTimeout(pollTimer);
  const job = await api('/jobs/' + encodeURIComponent(id)); currentJob = job;
  show('detail'); $('detail-name').textContent = job.name; $('detail-state').textContent = job.state.replaceAll('_', ' '); $('detail-state').className = 'badge ' + job.state;
  $('detail-stage').textContent = job.error || job.stage; $('progress').value = job.progress;
  show('cancel', ['queued', 'running'].includes(job.state)); show('resume-upload', job.state === 'uploading' && pendingUpload?.id === job.id);
  $('downloads').replaceChildren(); $('gallery').replaceChildren(); show('result-video', false); $('result-video').removeAttribute('src'); show('gallery-tools', false);
  if (job.state === 'uploading' && !pendingUpload) $('detail-stage').textContent = 'Upload was not submitted. To retry after closing this page, create a new analysis; this incomplete job does not incur GPU charges.';
  if (job.result) {
    for (const asset of job.result.assets.filter(a => !a.name.endsWith('.jpg'))) {
      const link = element('a', asset.name); link.href = assetUrl(job, asset); link.download = asset.name; $('downloads').append(link);
    }
    const video = job.result.assets.find(a => a.name === 'tracked.mp4');
    if (video) { $('result-video').src = assetUrl(job, video); show('result-video'); }
    const gallery = job.result.assets.find(a => a.name === 'gallery.json');
    if (gallery) {
      const response = await fetch(assetUrl(job, gallery)); if (!response.ok) throw new Error('Could not load the gallery.');
      const data = await response.json(); galleryRows = data.tracks; show('gallery-tools'); renderGallery();
    }
  }
  if (['queued', 'running'].includes(job.state)) pollTimer = setTimeout(() => detail(id).catch(e => { notice(e.message); pollTimer = setTimeout(() => detail(id).catch(e => notice(e.message)), 15000); }), 6000);
}
function renderGallery() {
  $('gallery').replaceChildren(); const search = $('gallery-search').value.toLowerCase();
  const rows = galleryRows.filter(row => `${row.track_id} ${row.species_id} ${row.scientific_name}`.toLowerCase().includes(search));
  for (const row of rows) {
    const card = element('article', undefined, 'fish-card'); const crop = currentJob.result.assets.find(a => a.name === row.crop);
    if (crop) { const img = element('img'); img.src = assetUrl(currentJob, crop); img.loading = 'lazy'; img.alt = 'Track ' + row.track_id + ' fish crop'; card.append(img); }
    const body = element('div'); body.append(element('h3', row.scientific_name || row.species_id.replaceAll('_', ' ')), element('p', `Track ${row.track_id} · ${row.first_s}–${row.last_s}s`), element('p', row.status.replaceAll('_', ' ') + (row.confidence == null ? ' · no model score' : ` · score ${Number(row.confidence).toFixed(3)}`)), element('p', row.reason.replaceAll('_', ' ')));
    card.append(body); $('gallery').append(card);
  }
  if (!rows.length) $('gallery').append(element('p', 'No matching tracks.', 'muted'));
}
$('gallery-search').oninput = renderGallery;
$('cancel').onclick = async () => { $('cancel').disabled = true; try { await post(`/jobs/${currentJob.id}/cancel`); await detail(currentJob.id); } catch (e) { notice(e.message); } finally { $('cancel').disabled = false; } };
$('resume-upload').onclick = async () => { if (!pendingUpload) return; $('resume-upload').disabled = true; try { await upload(pendingUpload.url, pendingUpload.file); await post(`/jobs/${pendingUpload.id}/start`); pendingUpload = null; await history(); await detail(currentJob.id); } catch (e) { notice(e.message); } finally { $('resume-upload').disabled = false; } };
enter().catch(e => { if (!e.message.includes('Sign in')) notice(e.message); });
