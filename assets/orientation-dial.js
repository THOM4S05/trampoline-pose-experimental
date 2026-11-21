/* Clock marks and opposing arrows follow the frame-timed torso axis. */
(() => {
'use strict';
const $ = id => document.getElementById(id), video = $('result-video'), panel = $('orientation-panel');
if (!video || !panel) return;
let jobId = null, generation = 0, samples = [], callback = null;

function unavailable(message) {
  $('orientation-needle').style.visibility = 'hidden';
  $('orientation-dial').setAttribute('aria-label', message);
}
function render(time = video.currentTime) {
  if (!samples.length) return;
  // The frame at its source timestamp remains visible until the next PTS.
  // Do not interpolate across missing poses or assume a nominal frame rate.
  let lo = 0, hi = samples.length;
  while (lo < hi) { const mid = (lo + hi) >>> 1; if (samples[mid][1] <= time + 1e-7) lo = mid + 1; else hi = mid; }
  const row = samples[Math.max(0, lo - 1)], angle = row[2];
  if (Number.isFinite(angle)) {
    $('orientation-needle').style.visibility = 'visible';
    $('orientation-needle').setAttribute('transform', `rotate(${angle} 50 50)`);
    const state = angle < 30 || angle > 330 ? 'Upright' : angle > 150 && angle < 210 ? 'Inverted' : angle < 180 ? 'Leaning right' : 'Leaning left';
    $('orientation-dial').setAttribute('aria-label', `Frame ${row[0] + 1} · ${row[1].toFixed(3)} s. Torso ${Math.round(angle)} degrees clockwise from upright. ${state}. Green arrow towards shoulders; half-length orange arrow towards hips, with a fine line to the rim. Twelve clock positions mark kickout timing.`);
  } else unavailable(row[5] === 'uncertain' ? 'Tracking uncertain' : 'No reliable torso pose');
}
function stop() {
  if (!callback) return;
  if (callback.kind === 'video') video.cancelVideoFrameCallback?.(callback.id);
  else window.cancelAnimationFrame?.(callback.id);
  callback = null;
}
function schedule() {
  if (callback || video.paused || video.ended) return;
  const tick = (_now, metadata) => { callback = null; render(metadata?.mediaTime ?? video.currentTime); schedule(); };
  if (video.requestVideoFrameCallback) callback = {kind:'video', id:video.requestVideoFrameCallback(tick)};
  else if (window.requestAnimationFrame) callback = {kind:'animation', id:window.requestAnimationFrame(tick)};
}
function clear() {
  generation++; jobId = null; samples = []; stop(); panel.hidden = true;
  unavailable('Choose a tracked video');
}
async function select(id) {
  if (jobId === id) { render(); schedule(); return; }
  clear(); jobId = id; const version = generation; panel.hidden = false;
  unavailable('Loading orientation…');
  try {
    const response = await fetch(window.viewerData.asset(id, 'orientation.json'));
    if (!response.ok) throw new Error('Orientation unavailable');
    const data = await response.json();
    if (generation !== version || jobId !== id) return;
    samples = Array.isArray(data.samples) ? data.samples : [];
    if (!samples.length) { unavailable('No orientation evidence'); return; }
    render(); schedule();
  } catch (_) {
    if (generation === version && jobId === id) unavailable('Orientation unavailable');
  }
}
for (const event of ['timeupdate','seeked','loadeddata','loadedmetadata']) video.addEventListener(event, () => render());
video.addEventListener('play', schedule);
video.addEventListener('pause', () => { stop(); render(); });
video.addEventListener('ended', () => { stop(); render(); });
video.addEventListener('emptied', () => { stop(); if (!video.getAttribute('src')) clear(); else render(); });
window.orientationDial = {select, clear};
})();
