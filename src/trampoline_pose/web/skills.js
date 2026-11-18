(() => {
'use strict';
const $ = id => document.getElementById(id);
const embedded = !!$('embedded-skills');
let pendingSeek = null, renderedResult = null, selectedSpan = null, analyzedSkills = [], markerSignature = null;
let frameTimes = [], frameTimesJob = null, frameTimesRequest = null;
let jobs = [], selectedId = null, requestVersion = 0, polling = false, showContext = false, submitting = false, noticeTimer;
const stateNames = {not_started:'Not started', queued:'Queued', running:'Analysing', done:'Ready to review', error:'Needs attention'};
function notice(text) { $('notice').textContent = text; $('notice').hidden = false; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => $('notice').hidden = true, 8000); }
function lock() { clearSelection(); window.reviewVideo.clear(); requestVersion++; selectedId = null; jobs = []; $('job-list').replaceChildren(); $('skill-list').replaceChildren(); $('workspace').hidden = true; $('logout').hidden = true; $('login-panel').hidden = false; }
function unlock() { $('login-panel').hidden = true; $('workspace').hidden = false; $('logout').hidden = false; }
async function api(path, options = {}) {
  const response = await fetch('/api' + path, {...options, headers:{'X-Portal-Request':'1', ...options.headers}});
  const data = await response.json();
  if (!response.ok) { if (response.status === 401) lock(); throw new Error(data.error || 'Request failed'); }
  return data;
}
function clearSelection() {
  requestVersion++; selectedId = null; pendingSeek = null; renderedResult = null;
  frameTimes = []; frameTimesJob = null; frameTimesRequest = null;
  selectedSpan = null; analyzedSkills = []; markerSignature = null; updateTimeline();
  $('analysis-panel').hidden = true; $('skill-list').replaceChildren();
  if ($('empty-selection')) $('empty-selection').hidden = false;
}
function applySeek() {
  const video = $('result-video');
  if (!pendingSeek || video.readyState < 1) return;
  const {id, seconds} = pendingSeek;
  pendingSeek = null;
  if (id !== selectedId) return;
  video.currentTime = Math.max(0, Math.min(seconds, Number.isFinite(video.duration) ? video.duration : seconds));
}
function updateTimeline() {
  const video = $('result-video'), duration = video.duration;
  const ready = video.readyState >= 1 && Number.isFinite(duration) && duration > 0;
  $('skill-seek').disabled = !ready;
  $('skill-seek').max = ready ? duration : 1;
  $('skill-seek').value = ready ? video.currentTime : 0;
  $('skill-seek').style.setProperty('--played', `${ready ? video.currentTime / duration * 100 : 0}%`);
  const bufferedStops = ['#ffffff22 0%'];
  if (ready && video.buffered) for (let i=0; i<video.buffered.length; i++) {
    const start=Math.min(100, Math.max(0, video.buffered.start(i)/duration*100));
    const end=Math.min(100, Math.max(start, video.buffered.end(i)/duration*100));
    bufferedStops.push(`#ffffff22 ${start}%`, `#ffffff88 ${start}%`, `#ffffff88 ${end}%`, `#ffffff22 ${end}%`);
  }
  bufferedStops.push('#ffffff22 100%');
  $('skill-seek').style.setProperty('--buffer-track', `linear-gradient(to right,${bufferedStops.join(',')})`);
  const clock = seconds => { const n = Math.max(0, Math.floor(seconds || 0)); return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')}`; };
  $('video-time').textContent = `${clock(video.currentTime)} / ${clock(ready ? duration : 0)}`;
  renderTimelineMarkers(ready ? duration : null);
  const skill = skillAtTime(video.currentTime);
  const stamp = tightestTime(skill);
  const button = $('jump-current-tightest');
  button.disabled = !ready || !Number.isFinite(stamp);
  button.title = !skill ? 'No skill at the current video time' : !Number.isFinite(stamp) ? 'No tightest point available for this skill' : `Flight ${skill.skill_index} · ${time(stamp)}${skill.execution?.review_shape_timestamp_seconds != null ? ' · candidate needs review' : ''}`;
  $('current-skill-label').textContent = skill ? `Flight ${skill.skill_index}` : '';
  const description = skill ? `Seek video · Flight ${skill.skill_index}` : 'Seek video';
  $('skill-seek').title = description;
  $('skill-seek').setAttribute('aria-label', description);
}
function tightestTime(skill) {
  return skill?.execution?.review_shape_timestamp_seconds ?? skill?.execution?.shape_timestamp_seconds;
}
function skillAtTime(seconds) {
  if (!Number.isFinite(seconds)) return null;
  // Contacts belong to the next skill; the final endpoint belongs to the last.
  return analyzedSkills.find(skill => {
    const start = skill.start_seconds ?? skill.visible_start_seconds;
    const end = skill.end_seconds ?? skill.visible_end_seconds;
    return Number.isFinite(start) && Number.isFinite(end) && seconds >= start && (seconds < end || (skill === analyzedSkills[analyzedSkills.length - 1] && seconds === end));
  }) || null;
}
function renderTimelineMarkers(duration) {
  const signature = JSON.stringify([duration, analyzedSkills.map(skill => [skill.skill_index, skill.start_seconds ?? skill.visible_start_seconds, skill.end_seconds ?? skill.visible_end_seconds])]);
  if (signature === markerSignature) return;
  markerSignature = signature;
  const points = new Map();
  if (Number.isFinite(duration) && duration > 0) for (const skill of analyzedSkills) for (const edge of ['start', 'end']) {
    const stamp = skill[edge + '_seconds'] ?? skill['visible_' + edge + '_seconds'];
    if (!Number.isFinite(stamp) || stamp < 0 || stamp > duration) continue;
    const key = stamp.toFixed(6);
    if (!points.has(key)) points.set(key, {stamp, labels:[]});
    points.get(key).labels.push(`Flight ${skill.skill_index} ${edge}`);
  }
  $('skill-markers').replaceChildren(...Array.from(points.values()).map(({stamp, labels}) => {
    const marker = document.createElement('span'); marker.className = 'video-skill-marker';
    const fraction = stamp / duration;
    marker.style.left = `calc(${fraction * 100}% + ${6 - fraction * 12}px)`;
    marker.title = `${labels.join(' / ')} · ${time(stamp)}`;
    return marker;
  }));
}
$('jump-current-tightest').onclick = () => {
  const skill = skillAtTime($('result-video').currentTime), stamp = tightestTime(skill);
  if (!Number.isFinite(stamp)) return;
  seekVideo(stamp);
};
function seekVideo(seconds) {
  if (!selectedId || !Number.isFinite(seconds)) return;
  pendingSeek = {id:selectedId, seconds}; applySeek(); updateTimeline();
}
function jumpToSkill(seconds, end, label, partial, target = seconds) {
  selectedSpan = {start:seconds, end, label, partial};
  updateTimeline();
  if (!selectedId || !Number.isFinite(target)) return;
  pendingSeek = {id: selectedId, seconds:target};
  applySeek();
  updateTimeline();
  $('result-video').scrollIntoView({behavior:'smooth', block:'center'});
  $('result-video').focus({preventScroll:true});
}
$('result-video').addEventListener('loadedmetadata', () => { applySeek(); updateTimeline(); });
for (const event of ['durationchange', 'timeupdate', 'seeked', 'emptied', 'progress', 'loadeddata']) $('result-video').addEventListener(event, updateTimeline);
$('skill-seek').oninput = event => seekVideo(Number(event.target.value));
function frameIndexAt(seconds) {
  let low=0, high=frameTimes.length;
  while(low<high) {const middle=(low+high)>>1;if(frameTimes[middle]<seconds)low=middle+1;else high=middle;}
  return low;
}
async function loadFrameTimes() {
  if (!selectedId) return [];
  if (frameTimesJob === selectedId) return frameTimes;
  if (frameTimesRequest?.id === selectedId) return frameTimesRequest.promise;
  const id=selectedId;
  const promise=api(`/jobs/${id}`).then(data => {
    if(id!==selectedId) return [];
    frameTimes=Array.isArray(data.timestamps) ? data.timestamps.filter(Number.isFinite) : [];
    frameTimesJob=id;frameTimesRequest=null;return frameTimes;
  }).catch(error=>{if(id===selectedId)frameTimesRequest=null;throw error;});
  frameTimesRequest={id,promise};return promise;
}
function updateFrameStatus() {
  if(!frameTimes.length) {$('video-frame-status').textContent='Frame —';return;}
  const current=$('result-video').currentTime;
  let index=frameIndexAt(current+.0005)-1;
  index=Math.max(0,Math.min(frameTimes.length-1,index));
  $('video-frame-status').textContent=`Frame ${index+1} / ${frameTimes.length}`;
}
async function stepFrame(direction) {
  const video=$('result-video');
  if(!selectedId || video.readyState<1)return;
  video.pause();
  try {
    const times=await loadFrameTimes();
    if(!times.length) {notice('Frame times are unavailable for this video.');return;}
    let index;
    if(direction>0) index=frameIndexAt(video.currentTime+.0005);
    else index=frameIndexAt(video.currentTime-.0005)-1;
    index=Math.max(0,Math.min(times.length-1,index));
    video.currentTime=times[index];updateTimeline();updateFrameStatus();
  } catch(error) {notice(error.message);}
}
$('video-prev-frame').onclick=()=>stepFrame(-1);
$('video-next-frame').onclick=()=>stepFrame(1);
document.addEventListener('keydown',event=>{
  if(!['ArrowLeft','ArrowRight'].includes(event.key)||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey)return;
  const tag=event.target?.tagName;
  if(['TEXTAREA','SELECT'].includes(tag)||(tag==='INPUT'&&event.target?.id!=='skill-seek'))return;
  if(!selectedId||$('result-video').readyState<1)return;
  event.preventDefault();stepFrame(event.key==='ArrowRight'?1:-1);
});
// Keep native controls as a fallback until the custom control handlers are ready.
function syncPlaybackControls() {
  const video = $('result-video');
  $('video-play').textContent = video.paused ? '▶' : '❚❚';
  $('video-play').setAttribute('aria-label', video.paused ? 'Play video' : 'Pause video');
  $('video-mute').textContent = video.muted ? 'Unmute' : 'Mute';
  $('video-mute').setAttribute('aria-label', video.muted ? 'Unmute video' : 'Mute video');
}
$('video-play').onclick = async () => {
  const video = $('result-video');
  try { if (video.paused) await video.play(); else video.pause(); }
  catch { notice('Could not play the video. Try again once it has loaded.'); }
};
$('video-speed').onchange = event => {
  const rate = Number(event.target.value);
  if (![1, .75, .5, .25, .1].includes(rate)) return;
  $('result-video').defaultPlaybackRate = rate;
  $('result-video').playbackRate = rate;
};
$('result-video').addEventListener('ratechange', () => { $('video-speed').value = String($('result-video').playbackRate); });
$('video-mute').onclick = () => { $('result-video').muted = !$('result-video').muted; syncPlaybackControls(); };
$('video-fullscreen').onclick = async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await $('video-player').requestFullscreen();
  } catch { notice('Fullscreen is not available in this browser.'); }
};
$('video-fullscreen').hidden = !document.fullscreenEnabled;
for (const event of ['play', 'pause', 'ended', 'volumechange']) $('result-video').addEventListener(event, syncPlaybackControls);
$('result-video').addEventListener('seeked',updateFrameStatus);
$('result-video').controls = false;
$('video-controls').hidden = false;
syncPlaybackControls();
function field(dl, label, value, review = false) {
  const container = document.createElement('div'), dt = document.createElement('dt'), dd = document.createElement('dd');
  if (review) container.className = 'review';
  dt.textContent = label; dd.textContent = value; container.append(dt, dd); dl.append(container);
}
function time(value) { return value == null ? 'Outside clip / unknown' : `${Number(value).toFixed(3)} s`; }
function angle(value) { return value == null ? 'Unknown' : `${Number(value).toFixed(1)}°`; }
function frame(value) { return value == null ? 'Outside clip / unknown' : String(value + 1); }
// Names use measured fields only; reference labels never supply missing evidence.
// Single-somersault terminology: FIG Trampoline Code of Points 2025–2028.
function supportedTwist(skill) {
  const evidence = skill.twist;
  // Legacy numeric/count-only exports remain readable. Explicit experimental
  // statuses must support the count; candidates never enter the naming path.
  const allowed = typeof evidence === 'number' || (evidence && typeof evidence === 'object' &&
    (evidence.status == null || ['supported', 'supported_conditional'].includes(evidence.status)));
  const count = typeof evidence === 'number' ? evidence : evidence?.count;
  return allowed && Number.isFinite(count) && count >= 0 ? count : null;
}
function bestGuess(skill) {
  const rotation = skill.rotation || {};
  const quarters = rotation.somersault_quarters ?? (Number.isFinite(rotation.somersault_count) ? rotation.somersault_count * 4 : null);
  const twists = supportedTwist(skill);
  if ((Number.isFinite(quarters) && quarters > 4) || (twists != null && twists > 1)) return {name:'Outside naming range', note:'Names cover up to 1 somersault and 1 twist.'};
  if (!Number.isInteger(quarters) || quarters < 0 || (twists != null && ![0, .5, 1].includes(twists))) return {name:'Unknown', note:'Not enough supported rotation or twist data to name this skill.'};
  if (skill.start_clipped || skill.end_clipped) return {name:'Unknown — partial skill', note:'The complete skill is not visible.'};
  const positions = {feet:'feet', standing:'feet', upright:'feet', seat:'seat', seated:'seat', front:'front', back:'back'};
  const start = positions[skill.takeoff_position ?? skill.seat_transition?.takeoff_position], end = positions[skill.landing_position ?? skill.seat_transition?.landing_position];
  const shape = {straight_like:'Straight', pike_like:'Pike', tuck_like:'Tuck', straddle_like:'Straddle'}[skill.execution?.execution_position];
  const direction = {forward:'Front', backward:'Back'}[rotation.direction];
  const twistLabel = twists === .5 ? 'Half twist' : twists === 1 ? 'Full twist' : '';
  let name;
  if (quarters === 0) {
    if (end === 'seat' && start === 'feet') name = 'Seat drop';
    else if (start && start !== 'feet' && end === 'feet') name = 'Return to feet';
    else if (start && start !== 'feet') name = `Rebound from ${start}${end ? ' to ' + end : ''}`;
    else name = shape ? `${shape} jump` : 'Jump';
    if (twistLabel) name = `${twistLabel}${name === 'Return to feet' ? ' to feet' : ' · ' + name.toLowerCase()}`;
  } else if (quarters === 4 && start === 'feet' && end === 'feet' && direction === 'Front' && twists === .5) {
    name = 'Barani';
  } else if (quarters === 4 && start === 'feet' && end === 'feet' && direction === 'Back' && twists === 1) {
    name = 'Back full';
  } else if (quarters === 1 && start === 'feet' && (end === 'front' || end === 'back')) {
    name = `${end === 'front' ? 'Front' : 'Back'} drop${twistLabel ? ' · ' + twistLabel.toLowerCase() : ''}`;
  } else if (quarters === 1 && (start === 'front' || start === 'back') && end === 'feet') {
    name = `${twistLabel ? twistLabel + ' to feet' : 'Return to feet'} from ${start}`;
  } else {
    const amount = {1:'¼ ', 2:'½ ', 3:'¾ ', 4:''}[quarters];
    name = `${amount}${direction ? direction.toLowerCase() + ' ' : ''}somersault`;
    name = name.charAt(0).toUpperCase() + name.slice(1);
    if (twistLabel) name += ` · ${twistLabel.toLowerCase()}`;
    if (start && start !== 'feet') name += ` from ${start}`;
    if (end && end !== 'feet') name += ` to ${end}`;
  }
  if (quarters > 0 && shape) name += ` (${shape.toLowerCase()})`;
  const missing = [];
  if (!start) missing.push('starting position');
  if (!end) missing.push('landing position');
  if (twists == null) missing.push('twist');
  if (!shape) missing.push('shape');
  if (quarters > 0 && !direction) missing.push('rotation direction');
  return {name, note:missing.length ? `Unconfirmed: ${missing.join(', ')}. Name may change when these are known.` : 'Estimated from starting position, landing position, shape, rotation, and twist.'};
}
function renderSkills(skills, images, reference) {
  if (!showContext && reference.routine_start_seconds != null) skills = skills.filter(skill => skill.visible_start_seconds >= reference.routine_start_seconds && (reference.routine_end_seconds == null || skill.visible_start_seconds < reference.routine_end_seconds));
  $('skill-list').replaceChildren(...skills.map((skill, index) => {
    const card = document.createElement('article'); card.className = 'skill-card';
    const title = document.createElement('h3');
    title.textContent = `Flight ${skill.skill_index}${skill.start_clipped || skill.end_clipped ? ' · partial clip' : ''}`;
    const supplied = (reference.skills || []).find(item => item.skill_index === skill.skill_index);
    if (supplied?.routine_index) title.textContent = `Routine skill ${supplied.routine_index} · Flight ${skill.skill_index}`;
    else if (!showContext && reference.routine_start_seconds != null) title.textContent = `Routine skill ${index + 1} · Flight ${skill.skill_index}${skill.start_clipped || skill.end_clipped ? ' · partial clip' : ''}`;
    const dl = document.createElement('dl'), rotation = skill.rotation || {}, shape = skill.execution || {};
    const supported = rotation.somersault_count == null ? 'Unknown / needs review' : `${rotation.somersault_count} ${rotation.direction || 'unknown'}`;
    const shapeNames = {straight_like:'Straight', pike_like:'Pike', tuck_like:'Tuck', flexed_or_open_shape:'Flexed / open', unknown:'Unknown / needs review'};
    const flightTiming = skill.time_of_flight || {};
    const flightSeconds = skill.time_of_flight_seconds ?? flightTiming.seconds;
    field(dl, 'Rotations', supported);
    field(dl, 'Shape (estimate)', shapeNames[shape.execution_position] || 'Unknown / needs review');
    const difficulty = skill.difficulty;
    field(dl, 'Difficulty (FIG 2025–2028 estimate)', Number.isFinite(difficulty?.value)
      ? `${difficulty.value.toFixed(1)} · provisional`
      : 'Unavailable — ' + (difficulty?.reasons || ['missing flight evidence']).join(', ').replaceAll('_', ' '), true);
    if (Number.isFinite(difficulty?.value)) field(dl, 'Difficulty breakdown', Object.entries(difficulty.components || {})
      .filter(([,value]) => value > 0).map(([key,value]) => `${key.replaceAll('_', ' ')} ${value.toFixed(1)}`).join(' + ') || 'Straight bounce: 0.0', true);
    field(dl, 'Time of flight (video estimate)', Number.isFinite(flightSeconds) && flightSeconds > 0 ? time(flightSeconds) : skill.start_clipped || skill.end_clipped ? 'Unavailable — partial skill' : 'Unavailable — take-off / landing needs review', true);
    const twistCount = supportedTwist(skill);
    field(dl, 'Twist (supported)', twistCount == null ? 'Unknown / needs review' : `${twistCount} turns`);
    if (Number.isFinite(flightSeconds) && flightSeconds > 0) field(dl, 'Estimated take-off / landing', `${time(flightTiming.takeoff_seconds)} → ${time(flightTiming.landing_seconds)}`);
    const contact = skill.landing_contact;
    field(dl, 'Landing on bed', Number.isFinite(contact?.timestamp_seconds) ? `${time(contact.timestamp_seconds)} · frame ${frame(contact.frame_index)}` : 'Not detected — review the video', true);
    if (contact?.interval_seconds) field(dl, 'Landing review window', contact.interval_seconds.map(time).join(' → '));
    if (flightTiming.interval_seconds) field(dl, 'Flight-time range', flightTiming.interval_seconds.map(time).join(' – '));
    const candidateTwist = skill.twist?.candidate_count ?? skill.seat_transition?.candidate_twist_count ?? skill.seat_transition?.twist_count;
    if (twistCount == null && Number.isFinite(candidateTwist)) field(dl, 'Tentative twist — needs review', `${candidateTwist} turns`, true);
    field(dl, 'Start / end frames', `${frame(skill.start_frame)} → ${frame(skill.end_frame)}`);
    field(dl, 'Skill analysis boundaries', `${time(skill.start_seconds)} → ${time(skill.end_seconds)}`);
    field(dl, 'Quarter somersaults', rotation.somersault_quarters == null ? 'Unknown / needs review' : `${rotation.somersault_quarters} × ¼ · ${rotation.direction}`);
    if (rotation.somersault_quarters == null && rotation.candidate_somersault_quarters != null) field(dl, 'Tentative rotation — needs review', `${rotation.candidate_somersault_quarters} × ¼ · ${rotation.candidate_direction}`);
    field(dl, 'Time of tightest supported held shape', time(shape.shape_timestamp_seconds));
    if (shape.tightest_shape_review_interval_seconds) field(dl, 'Possible tighter shape — needs review', shape.tightest_shape_review_interval_seconds.map(time).join(' → '), true);
    field(dl, 'Hip / knee angles', `${angle(shape.sustained_hip_angle_degrees)} / ${angle(shape.sustained_knee_angle_degrees)}`);
    field(dl, 'Intended skill', 'Unconfirmed — review the video');
    if (supplied) field(dl, 'User-supplied reference', `${supplied.skill_identity} · ${supplied.somersault_quarters} × ¼ ${supplied.direction}${supplied.twist_count != null ? ' · twist ' + supplied.twist_count + ' (reference annotation)' : ''}`, true);
    const reasons = [...(rotation.reasons || []), ...(shape.reasons || []), ...(skill.twist?.reasons || [])];
    if (rotation.contact_outage_excluded) reasons.push('Tracking outage near body contact was excluded; check the contact time');
    field(dl, 'Items to review', reasons.length ? reasons.join(', ') : 'Check estimated contact times and body shape', true);
    const flightLabel = title.textContent, guess = bestGuess(skill);
    title.textContent = `Best guess: ${guess.name}`;
    const heading = document.createElement('div'); heading.className = 'skill-card-heading';
    const jump = document.createElement('button'); jump.type = 'button'; jump.className = 'primary'; jump.textContent = 'Jump to skill';
    const start = skill.start_seconds ?? skill.visible_start_seconds;
    jump.disabled = !Number.isFinite(start);
    jump.setAttribute('aria-label', `Jump to ${flightLabel.toLowerCase()}${jump.disabled ? ' (time unavailable)' : ' at ' + time(start)}`);
    jump.onclick = () => jumpToSkill(start, skill.end_seconds ?? skill.visible_end_seconds, flightLabel, skill.start_clipped || skill.end_clipped);
    const titleBlock = document.createElement('div'), flight = document.createElement('p'), uncertainty = document.createElement('p');
    flight.className = 'small skill-flight-number'; flight.textContent = flightLabel;
    uncertainty.className = 'small'; uncertainty.textContent = guess.note + (supplied?.user_confirmed ? ` Your confirmed reference: ${supplied.skill_identity}.` : '');
    titleBlock.append(title, flight, uncertainty);
    const tightest = shape.review_shape_timestamp_seconds ?? shape.shape_timestamp_seconds;
    const tightestButton = document.createElement('button');
    tightestButton.type = 'button'; tightestButton.className = 'primary'; tightestButton.textContent = 'Jump to tightest point';
    tightestButton.disabled = !Number.isFinite(tightest);
    const review = shape.review_shape_timestamp_seconds != null;
    tightestButton.title = tightestButton.disabled ? 'No tightest-shape timestamp available' : `${time(tightest)}${review ? ' · candidate needs review' : ''}`;
    tightestButton.setAttribute('aria-label', `Jump to tightest point of ${flightLabel.toLowerCase()}${review ? ' (candidate needs review)' : ''}`);
    tightestButton.onclick = () => jumpToSkill(start, skill.end_seconds ?? skill.visible_end_seconds, flightLabel, skill.start_clipped || skill.end_clipped, tightest);
    heading.append(titleBlock, jump, tightestButton); card.append(heading);
    if (Number.isFinite(contact?.timestamp_seconds)) {
      const landingButton = document.createElement('button');
      landingButton.type = 'button'; landingButton.className = 'secondary'; landingButton.textContent = 'Jump to landing';
      landingButton.setAttribute('aria-label', `Review landing for ${flightLabel.toLowerCase()} at ${time(contact.timestamp_seconds)}`);
      landingButton.onclick = () => { $('result-video').pause(); jumpToSkill(start, skill.end_seconds ?? skill.visible_end_seconds, flightLabel, skill.start_clipped || skill.end_clipped, contact.timestamp_seconds); };
      heading.append(landingButton);
    }
    const evidence = images[String(skill.skill_index)];
    if (evidence?.available) {
      card.classList.add('has-image');
      const figure = document.createElement('figure'), image = document.createElement('img'), caption = document.createElement('figcaption'), heading = document.createElement('h4');
      heading.className = 'shape-image-title'; heading.textContent = 'Tightest shape during skill';
      image.src = `/api/jobs/${selectedId}/skill-images/${skill.skill_index}.jpg`;
      image.alt = `Flight ${skill.skill_index} pose overlay at the selected shape`; image.loading = 'lazy';
      caption.textContent = `Preview frame ${evidence.frame_index + 1} · ${time(evidence.timestamp_seconds)}. ${evidence.selection_method?.startsWith('occluded_shape_review') ? 'Review candidate during missing-joint interval; exact tightest time is unverified. Angles below come from the supported held shape.' : 'Angles are measured across the held shape, not just this frame.'}`;
      figure.append(heading, image, caption); card.append(figure);
    } else {
      const note = document.createElement('p'); note.className = 'small'; note.textContent = evidence?.message || 'No preview available for this flight.'; card.append(note);
    }
    card.append(dl); return card;
  }));
}
function renderJobs() {
  if (embedded) return;
  const tracked = jobs.filter(job => job.state === 'done'); $('empty-list').hidden = tracked.length > 0;
  $('job-list').replaceChildren(...tracked.map(job => {
    const button = document.createElement('button'); button.className = 'job-card' + (job.id === selectedId ? ' selected' : '');
    const name = document.createElement('strong'), status = document.createElement('span'); name.textContent = job.display_name || job.name; status.textContent = stateNames[job.analysis?.state || 'not_started']; button.append(name, status);
    button.onclick = () => selectJob(job.id).catch(error => notice(error.message)); return button;
  }));
}
async function selectJob(id) { clearSelection(); showContext = false; if ($('show-context')) $('show-context').checked = false; selectedId = id; const version = ++requestVersion; renderJobs(); await refreshSelected(version); }
async function refreshSelected(version = requestVersion) {
  if (!selectedId) return;
  const id = selectedId, job = jobs.find(item => item.id === id);
  if (!job || job.state !== 'done') { clearSelection(); if (!embedded) window.reviewVideo.clear(); return; }
  if (!embedded) {
    $('video-name').textContent = job.display_name || job.name;
    window.reviewVideo.setSource(`/api/jobs/${id}/results/overlay.mp4`);
    if ($('empty-selection')) $('empty-selection').hidden = true;
    $('analysis-panel').hidden = false;
  }
  const data = await api(`/jobs/${id}/analysis`);
  if (version !== requestVersion || id !== selectedId) return;
  const analysis = data.analysis;
  if ($('empty-selection')) $('empty-selection').hidden = true;
  $('analysis-panel').hidden = false; $('analysis-state').textContent = stateNames[analysis.state] || analysis.state; $('analysis-message').textContent = analysis.message;
  $('start-analysis').hidden = !['not_started', 'error', 'done'].includes(analysis.state); $('start-analysis').textContent = analysis.state === 'done' ? 'Redo analysis' : 'Run skill analysis'; $('start-analysis').disabled = submitting;
  $('analysis-results').hidden = analysis.state !== 'done';
  if (analysis.state === 'done') {
    analyzedSkills = data.skills || [];
    updateTimeline();
    let context = $('routine-context');
    if (!context) {
      context = document.createElement('div'); context.id = 'routine-context'; context.className = 'routine-context';
      const label = document.createElement('label'), checkbox = document.createElement('input'), note = document.createElement('p'); checkbox.type = 'checkbox'; checkbox.id = 'show-context';
      checkbox.onchange = () => { showContext = checkbox.checked; refreshSelected().catch(error => notice(error.message)); }; label.append(checkbox, document.createTextNode('Show preparation and outbounces')); note.id = 'routine-note'; note.className = 'small'; context.append(label, note); $('skill-list').before(context);
    }
    context.hidden = data.reference?.routine_start_seconds == null;
    $('routine-note').textContent = data.reference?.routine_start_seconds != null ? `Routine starts at ${time(data.reference.routine_start_seconds)} (${data.reference.window_provenance === 'agent_proposed_from_video' ? 'proposed from video; needs review' : 'user reference'}). End and sequence alignment are proposed and need review.` : '';
    const signature = JSON.stringify([id, showContext, data.skills, data.shape_images, data.reference]);
    if (signature !== renderedResult) {
      renderSkills(data.skills || [], data.shape_images || {}, data.reference || {});
      renderedResult = signature;
    }
    $('download-skills-json').href = `/api/jobs/${id}/results/skills.json`; $('download-skills-csv').href = `/api/jobs/${id}/results/skills.csv`;
  } else { analyzedSkills = []; updateTimeline(); $('skill-list').replaceChildren(); renderedResult = null; }
}
async function refresh() { if (polling) return; polling = true; try { const data = await api('/jobs'); unlock(); jobs = data.jobs; renderJobs(); await refreshSelected(); } finally { polling = false; } }
if (!embedded) {
$('login-form').onsubmit = async event => { event.preventDefault(); try { await api('/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({key:$('access-key').value.trim()})}); $('access-key').value = ''; await refresh(); } catch (error) { notice(error.message); } };
$('logout').onclick = async () => { try { await api('/logout', {method:'POST'}); lock(); } catch (error) { notice(error.message); } };
}
$('start-analysis').onclick = async () => {
  if (!selectedId || submitting) return;
  const id = selectedId; submitting = true; $('start-analysis').disabled = true;
  try { await api(`/jobs/${id}/analysis`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({redo:true})}); await refreshSelected(); }
  catch (error) { notice(error.message); }
  finally { submitting = false; $('start-analysis').disabled = false; }
};
if (!embedded) {
refresh().catch(error => { if (error.message !== 'Unlock the inbox first') notice(error.message); });
setInterval(() => { if ($('workspace').hidden) return; refresh().catch(error => notice(error.message)); }, 2500);

} else {
  window.skillAnalysis = {
    clear: clearSelection,
    async select(job) {
      if (!job || job.state !== 'done') { clearSelection(); return; }
      jobs = [job];
      if (selectedId !== job.id) await selectJob(job.id);
      else await refreshSelected();
    }
  };
}
})();
