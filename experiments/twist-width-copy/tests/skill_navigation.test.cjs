const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '../src/trampoline_pose/web');

test('flight difficulty shows just the best estimated score', async () => {
  const ui = setup();
  ui.setData({analysis:{state:'done'}, skills:[{skill_index:1,
    difficulty:{value:1.3, status:'provisional', components:{somersault:1, position:.2, backward_bonus:.1}},
  }, {skill_index:2, difficulty:{value:null, reasons:['partial_flight']}}], reference:{}, shape_images:{}});
  await ui.api.select(ui.job);
  const fields = index => ui.elements.get('skill-list').children[index].children.find(child => child.tagName === 'dl').children;
  const find = (index, name) => fields(index).find(field => field.children[0].textContent === name).children[1].textContent;
  assert.equal(find(0, 'Difficulty'), '1.3');
  assert.ok(!fields(0).some(field => field.children[0].textContent === 'Difficulty breakdown'));
  assert.equal(find(1, 'Difficulty'), '—');
});

test('recovered rotation displays its phase evidence and retains estimate status', async () => {
  const ui = setup();
  ui.setData({analysis:{state:'done'}, skills:[{
    skill_index:1, rotation:{candidate_somersault_quarters:8, candidate_direction:'backward',
      count_method:'torso_phases_and_contact_orientation', angle_candidate_somersault_count:1.75,
      phase_evidence:{observed_inversion_count:2, takeoff_phase:'upright', landing_phase:'upright'}},
    execution:{},
  }], reference:{}, shape_images:{}});
  await ui.api.select(ui.job);
  const card = ui.elements.get('skill-list').children[0];
  const text = element => typeof element === 'string' ? element : [element.textContent || '', ...element.children.map(text)].join(' ');
  assert.match(text(card), /2 distinct upside-down passages/);
  assert.match(text(card), /Original angle estimate: 1.75 rotations/);
  const fields = card.children.find(child => child.tagName === 'dl').children;
  assert.equal(fields[1].children[1].textContent, '2 (Estimate)');
});

test('contact constraint warns without replacing the tentative rotation count', async () => {
  const ui = setup();
  ui.setData({analysis:{state:'done'}, skills:[{
    skill_index:1, rotation:{candidate_somersault_quarters:7, candidate_direction:'backward',
      contact_consistency:{status:'conflict', rule:'whole_turns', takeoff_position:'feet', landing_position:'feet', reasons:[]}},
    execution:{},
  }], reference:{}, shape_images:{}});
  await ui.api.select(ui.job);
  const card = ui.elements.get('skill-list').children[0];
  const text = element => typeof element === 'string' ? element : [element.textContent || '', ...element.children.map(text)].join(' ');
  assert.match(text(card), /count conflicts with contacts/);
  const fields = card.children.find(child => child.tagName === 'dl').children;
  assert.equal(fields[1].children[1].textContent, '1.75 (Estimate)');
});

test('headline attributes use decimal rotations, directions and half-turn passages in order', async () => {
  for (const embedded of [true, false]) {
    const ui = setup(embedded);
    if (!embedded) await new Promise(resolve => setImmediate(resolve));
    ui.setData({analysis:{state:'done'}, skills:[1, 3, 6, 7].map((quarters, i) => ({
      skill_index:i + 1, rotation:{candidate_somersault_quarters:quarters, candidate_direction:i % 2 ? 'backward' : 'forward'},
      execution:{execution_position:'tuck_like'},
      twist:{method:'shoulder_hip_width_passages_v1', completed_passages:i + 1, status:'tentative'},
    })), reference:{}, shape_images:{}});
    if (embedded) await ui.api.select(ui.job);
    else await ui.elements.get('job-list').children[0].onclick();
    ui.elements.get('skill-list').children.forEach((card, i) => {
      const fields = card.children.find(child => child.tagName === 'dl').children.slice(0, 4);
      assert.deepEqual(fields.map(field => field.children[0].textContent), ['Shape (estimate)', 'Rotations', 'Twists', 'TOF (Estimate)']);
      assert.equal(fields[1].children[1].textContent, `${[.25, .75, 1.5, 1.75][i]} (Estimate)`);
      assert.equal(fields[1].children[1].children[0].textContent, i % 2 ? 'backward' : 'forward');
      assert.equal(fields[2].children[1].textContent, `${(i + 1) / 2} (Estimate)`);
    });
  }
});

test('supported rotations and twists retain certainty; phase evidence supplies the active passage total', async () => {
  const ui = setup();
  ui.setData({analysis:{state:'done'}, skills:[{
    skill_index:1, rotation:{somersault_count:1.5, direction:'backward', candidate_somersault_quarters:7},
    twist:{method:'shoulder_hip_width_passages_v1', completed_passages:1, detected_phases:4, status:'supported', reasons:[]},
  }], reference:{}, shape_images:{}});
  await ui.api.select(ui.job);
  const fields = ui.elements.get('skill-list').children[0].children.find(child => child.tagName === 'dl').children;
  assert.equal(fields[1].children[1].textContent, '1.5');
  assert.equal(fields[2].children[1].textContent, '2');
});

test('TOF uses bed endpoints and bounds error by frame spacing and contact intervals', async () => {
  const ui = setup();
  ui.setFrameTimes(Array.from({length:61}, (_, i) => i / 25));
  ui.setData({analysis:{state:'done'}, skills:[{
    skill_index:1, time_of_flight_seconds:99,
    time_of_flight:{takeoff_seconds:.4, landing_seconds:1.6, interval_seconds:[1.18, 1.22]},
    landing_contact:{supported_sides:1},
  }, {
    skill_index:2, time_of_flight:{takeoff_seconds:.4, landing_seconds:1.6, interval_seconds:[1.1, 1.23]},
  }], reference:{}, shape_images:{}});
  await ui.api.select(ui.job);
  const values = ui.elements.get('skill-list').children.map(card => card.children.find(child => child.tagName === 'dl').children[3].children[1]);
  assert.equal(values[0].textContent, '1.200 s');
  assert.equal(values[0].children[0].textContent, '(± 0.04 s) (low fps, limited bed visibility)');
  assert.equal(values[1].children[0].textContent, '(± 0.10 s) (low fps, bed contact / release timing)');
});

test('width experiment shows half-twist candidates and seeks detected passage', async () => {
  const ui = setup();
  ui.setData({analysis:{state:'done'}, skills:[{skill_index:1,start_seconds:2,end_seconds:5,
    twist:{method:'shoulder_hip_width_passages_v1', count:null, candidate_count:.5,
      completed_passages:1, events:[{broad_seconds:3.25}], reasons:[]}, execution:{}}],reference:{},shape_images:{}});
  await ui.api.select(ui.job);
  const card = ui.elements.get('skill-list').children[0];
  const text = element => typeof element === 'string' ? element : [element.textContent || '', ...element.children.map(text)].join(' ');
  const labels = text(card.children.at(-1));
  assert.match(labels, /1 × ½ twist \(0.5 turns\)/);
  const button = card.children[0].children.find(item => item.textContent === 'Review twist passage 1');
  assert(button); button.onclick();
  assert.equal(ui.elements.get('result-video').currentTime,3.25);
});

test('unknown width estimate does not fall back to a seat-transition guess', async () => {
  const ui = setup();
  ui.setData({analysis:{state:'done'}, skills:[{skill_index:1,start_seconds:2,end_seconds:5,
    twist:{method:'shoulder_hip_width_passages_v1', count:null,candidate_count:null,
      completed_passages:0,events:[],reasons:['missing_torso_observation']},
    seat_transition:{candidate_twist_count:.5},execution:{}}],reference:{},shape_images:{}});
  await ui.api.select(ui.job);
  const card = ui.elements.get('skill-list').children[0];
  const text = element => typeof element === 'string' ? element : [element.textContent || '', ...element.children.map(text)].join(' ');
  const labels = text(card.children.at(-1));
  assert.match(labels, /Unknown — shoulder \/ hip evidence needs review/);
  assert.doesNotMatch(labels, /1 × ½ twist/);
});

test('half-twist jump candidate is displayed explicitly as experimental', async () => {
  const ui = setup();
  ui.setData({analysis:{state:'done'}, skills:[{skill_index:5,start_seconds:5,end_seconds:6.5,
    twist:{method:'shoulder_hip_width_passages_v1',status:'tentative',count:null,candidate_count:.5,
      candidate_skill_identity:'Half twist jump',completed_passages:1,events:[],reasons:[]},
    execution:{},rotation:{somersault_count:0},takeoff_position:'feet',landing_position:'feet'}],reference:{},shape_images:{}});
  await ui.api.select(ui.job);
  const text = element => typeof element === 'string' ? element : [element.textContent || '', ...element.children.map(text)].join(' ');
  const labels = text(ui.elements.get('skill-list').children[0]);
  assert.match(labels,/Experimental skill candidate Half twist jump · needs review/);
  assert.match(labels,/Twists 0.5 \(Estimate\)/);
});

test('supported zero twist is stated clearly and names the untwisted skill', async () => {
  const ui = setup();
  ui.setData({analysis:{state:'done'},skills:[{skill_index:1,start_seconds:1,end_seconds:2,
    takeoff_position:'feet',landing_position:'feet',rotation:{somersault_count:1,direction:'backward'},
    execution:{execution_position:'tuck_like'},twist:{method:'shoulder_hip_width_passages_v1',
      status:'supported_conditional',count:0,candidate_count:0,completed_passages:0,reasons:[],events:[]}}],reference:{},shape_images:{}});
  await ui.api.select(ui.job);
  const text = el => typeof el === 'string' ? el : [el.textContent || '',...el.children.map(text)].join(' ');
  const card = text(ui.elements.get('skill-list').children[0]);
  assert.match(card,/Best guess: Back somersault \(tuck\)/);
  assert.match(card,/Twists 0 /);
  assert.doesNotMatch(card,/0 × ½ twist|Unconfirmed: twist/);
});

test('clean multiple-somersault twist candidate is named with its uncertainty', async () => {
  const ui = setup();
  ui.setData({analysis:{state:'done'},skills:[{skill_index:1,start_seconds:1,end_seconds:2,
    takeoff_position:'feet',landing_position:'feet',rotation:{somersault_count:2,direction:'forward'},
    execution:{execution_position:'straight_like'},twist:{method:'shoulder_hip_width_passages_v1',
      status:'tentative',count:null,candidate_count:2.5,completed_passages:5,reasons:[],events:[]}}],reference:{},shape_images:{}});
  await ui.api.select(ui.job);
  const text = el => typeof el === 'string' ? el : [el.textContent || '',...el.children.map(text)].join(' ');
  const card = text(ui.elements.get('skill-list').children[0]);
  assert.match(card,/Best guess: Double front somersault · 2½ twists \(straight\)/);
  assert.match(card,/Twist count is tentative/);
  assert.match(card,/distribution across somersaults is unresolved/);
  assert.match(card,/Twists 2.5 \(Estimate\)/);
});

test('upright jump phase candidate keeps landing completion visible for review', async () => {
  const ui=setup();
  ui.setData({analysis:{state:'done'},skills:[{skill_index:2,start_seconds:1,end_seconds:2.6,
    takeoff_position:'feet',landing_position:'feet',rotation:{somersault_count:0},
    execution:{execution_position:'straight_like'},twist:{method:'shoulder_hip_width_passages_v1',
      status:'tentative',count:null,candidate_count:1.5,detected_phases:3,completed_passages:1,
      finish_completion_status:'needs_review',reasons:[],review_reasons:['side_on_finish_not_established'],events:[]}}],reference:{},shape_images:{}});
  await ui.api.select(ui.job);
  const text=el=>typeof el==='string'?el:[el.textContent||'',...el.children.map(text)].join(' ');
  const card=text(ui.elements.get('skill-list').children[0]);
  assert.match(card,/Best guess: 1½ twists · straight jump/);
  assert.match(card,/3 paired broad phases · checked against facing/);
  assert.match(card,/review the final rotation at bed contact/);
  assert.doesNotMatch(card,/3 completed paired width passages/);
});

function setup(embedded = true) {
  const elements = new Map();
  class Element {
    constructor(tag) { this.tagName = tag; this.children = []; this.events = {}; this.style = {setProperty(key, value){this[key] = value;}}; this.attrs = {}; this.classList = {add(){}}; this.readyState = 1; this.duration = 30; this.currentTime = 0; this.paused = true; }
    set id(value) { this._id = value; elements.set(value, this); }
    get id() { return this._id; }
    append(...items) { this.children.push(...items); }
    replaceChildren(...items) { this.children = items; }
    before() {}
    after() {}
    closest() { return this; }
    setAttribute(key, value) { this.attrs[key] = value; }
    getAttribute(key) { return this.attrs[key] ?? null; }
    removeAttribute(key) { delete this.attrs[key]; }
    cloneNode() { return new Element(this.tagName); }
    querySelector() { return new Element('g'); }
    set src(value) { this.attrs.src = value; this.sourceChanges = (this.sourceChanges || 0) + 1; }
    addEventListener(name, callback) { this.events[name] = callback; }
    scrollIntoView() { this.scrolled = true; }
    focus() { this.focused = true; }
    load() { this.currentTime = 0; }
    pause() { this.paused = true; if(this.events.pause)this.events.pause(); }
  }
  const html = fs.readFileSync(path.join(root, embedded ? 'index.html' : 'skills.html'), 'utf8');
  for (const match of html.matchAll(/id="([^"]+)"/g)) { assert(!elements.has(match[1]), 'Unique HTML IDs'); const el = new Element('div'); el.id = match[1]; }
  const job = {id:'a', state:'done', name:'Routine'};
  let data = {analysis:{state:'done', message:'Ready'}, skills:[
    {skill_index:1, start_seconds:4.25, visible_start_seconds:4.25},
    {skill_index:2, start_seconds:null, visible_start_seconds:0, start_clipped:true},
    {skill_index:3, start_seconds:null},
  ], shape_images:{}, reference:{}};
  let analysisGate = null, keydown = null, timestamps = [0,.04,.1,.15];
  const mutations = [];
  const context = {document:{getElementById:id => elements.get(id) || null, createElement:tag => new Element(tag), createTextNode:text => text, addEventListener(name,callback){if(name==='keydown')keydown=callback;}}, window:{}, setTimeout(){}, clearTimeout(){}, setInterval(){}, fetch:async (url, options) => {
    if (options?.method) mutations.push({url, ...options});
    if (analysisGate && url.endsWith('/analysis')) await analysisGate;
    return {ok:true, json:async () => url === '/api/jobs' ? {jobs:[job]} : url === '/api/jobs/a' ? {...job,timestamps} : data};
  }};
  context.window.reviewVideo = {
    setSource(src) { const video=elements.get('result-video'); if(video.getAttribute('src')!==src) video.src=src; },
    clear() { const video=elements.get('result-video'); video.removeAttribute('src'); video.load(); },
  };
  vm.runInNewContext(fs.readFileSync(path.join(root, 'video-name.js'), 'utf8'), context);
  vm.runInNewContext(fs.readFileSync(path.join(root, 'skills.js'), 'utf8'), context);
  return {elements, job, api:context.window.skillAnalysis, html, mutations, setFrameTimes(value){timestamps=value;}, keydown(event){return keydown(event);}, delayAnalysis(value){analysisGate=value;}, setData(value){data=value;}, button(index){return elements.get('skill-list').children[index].children[0].children[1];}};
}

test('kickout preview follows the tightest shape and confirms the displayed native frame', async () => {
  const ui = setup();
  const leg = {hip:{observed_degrees:173}, knee:{observed_degrees:178}};
  const opening = {status:'confirmed', flight_bounds_seconds:[0,.15], reasons:[], image:{available:true},
    selected:{frame_index:1, timestamp_seconds:.04, torso_degrees:217, left:leg, right:leg},
    fig:{status:'estimated', phase_degrees:37, opening_deduction:.1}};
  ui.setData({analysis:{state:'done'}, skills:[{skill_index:1, start_seconds:0, end_seconds:.15,
    execution:{execution_position:'tuck_like'}, rotation:{somersault_quarters:8}, twist:0, kickout:opening}],
  shape_images:{1:{available:true, frame_index:0, timestamp_seconds:0}}, reference:{}});
  await ui.api.select(ui.job);
  const card = ui.elements.get('skill-list').children[0];
  const stack = card.children.find(el => el.className === 'skill-evidence-stack');
  const [tightest, kickout] = stack.children;
  assert.equal(kickout.className, 'kickout-preview');
  assert.ok(card.children.some(el => el.tagName === 'dl'));
  assert.match(tightest.children[1].attrs.src, /skill-images\/1.jpg/);
  assert.match(kickout.children[1].attrs.src, /kickouts\/1\/automatic.jpg/);
  const text = el => typeof el === 'string' ? el : [el.textContent || '', ...el.children.map(text)].join(' ');
  assert.match(text(card), /FIG notation \(estimate\) 8 00 o/);
  assert.match(text(kickout), /Left hip 173.0° · knee 178.0°/);
  assert.match(text(kickout), /Estimated FIG opening deduction 0.1/);
  const [jump, confirm] = kickout.children.at(-1).children;
  const video = ui.elements.get('result-video');
  video.readyState = 2;
  jump.onclick();
  assert.equal(video.currentTime, .04);
  video.currentTime = .10;
  await confirm.onclick();
  assert.equal(ui.mutations[0].url, '/api/jobs/a/kickouts/1');
  assert.equal(ui.mutations[0].method, 'PUT');
  assert.deepEqual(JSON.parse(ui.mutations[0].body), {frame_index:2});
});

test('seeker buffer shows separate loaded ranges and clears when video empties', async () => {
  const ui = setup(); await ui.api.select(ui.job);
  const video = ui.elements.get('result-video'), seek = ui.elements.get('skill-seek');
  video.duration = 100;
  video.buffered = {length:2, start:i => [0,60][i], end:i => [20,80][i]};
  video.events.progress();
  assert.equal(seek.style['--buffer-track'], 'linear-gradient(to right,#ffffff22 0%,#ffffff22 0%,#ffffff88 0%,#ffffff88 20%,#ffffff22 20%,#ffffff22 60%,#ffffff88 60%,#ffffff88 80%,#ffffff22 80%,#ffffff22 100%)');
  video.readyState = 0; video.events.emptied();
  assert.equal(seek.style['--buffer-track'], 'linear-gradient(to right,#ffffff22 0%,#ffffff22 100%)');
});

test('embedded cards seek by contact time or first visible time, with disabled unknown timing', async () => {
  const ui = setup(); await ui.api.select(ui.job);
  assert(ui.html.indexOf('id="result-video"') < ui.html.indexOf('id="embedded-skills"'));
  const video = ui.elements.get('result-video');
  assert.equal(ui.button(0).textContent, 'Jump to skill');
  ui.button(0).onclick(); assert.equal(video.currentTime, 4.25); assert(video.scrolled && video.focused);
  ui.button(1).onclick(); assert.equal(video.currentTime, 0);
  assert.equal(ui.button(2).disabled, true);
});

test('each skill shows airborne time with three decimals and explains unavailable timing', async () => {
  const ui = setup();
  ui.setData({analysis:{state:'done'}, skills:[
    {skill_index:1, start_seconds:1, end_seconds:2.5, time_of_flight_seconds:1.23456,
      time_of_flight:{takeoff_seconds:1.2, landing_seconds:2.43456}},
    {skill_index:2, start_clipped:true},
    {skill_index:3, start_seconds:3, end_seconds:4.5},
  ], reference:{}, shape_images:{}});
  await ui.api.select(ui.job);
  const text = element => typeof element === 'string' ? element : [element.textContent || '', ...element.children.map(text)].join(' ');
  const cards = ui.elements.get('skill-list').children.map(text);
  assert(cards[0].includes('TOF (Estimate) 1.235 s'));
  assert(cards[0].includes('Estimated take-off / landing 1.200 s → 2.435 s'));
  assert(cards[1].includes('Unavailable — partial skill'));
  assert(cards[2].includes('Unavailable — take-off / landing needs review'));
});

test('landing button pauses at the detected bed-contact frame rather than the old pose boundary', async () => {
  const ui = setup();
  ui.setData({analysis:{state:'done'}, skills:[{skill_index:1,start_seconds:.2,end_seconds:1.54,
    landing_contact:{timestamp_seconds:1.475,frame_index:354,interval_seconds:[1.46,1.49]}}],reference:{},shape_images:{}});
  await ui.api.select(ui.job);
  const heading=ui.elements.get('skill-list').children[0].children[0];
  const button=heading.children.find(child=>child.textContent==='Jump to landing');
  assert(button);
  const video=ui.elements.get('result-video'); video.paused=false;
  button.onclick();
  assert.equal(video.currentTime,1.475);
  assert.equal(video.paused,true);
});

test('seeking waits for metadata and clamps to the video duration', async () => {
  const ui = setup(); await ui.api.select(ui.job);
  const video = ui.elements.get('result-video'); video.readyState = 0;
  ui.button(0).onclick(); assert.equal(video.currentTime, 0);
  video.readyState = 1; video.duration = 4; video.events.loadedmetadata(); assert.equal(video.currentTime, 4);
});

test('switching videos cancels a pending seek; polling preserves controls and playback', async () => {
  const ui = setup(); await ui.api.select(ui.job);
  const video = ui.elements.get('result-video'); video.readyState = 0; ui.button(0).onclick();
  await ui.api.select({...ui.job, id:'b'});
  video.readyState = 1; video.events.loadedmetadata(); assert.equal(video.currentTime, 0);
  const button = ui.button(0); video.currentTime = 7;
  await ui.api.select({...ui.job, id:'b'});
  assert.equal(ui.button(0), button); assert.equal(video.currentTime, 7);
  ui.api.clear(); assert.equal(ui.elements.get('analysis-panel').hidden, true);
});

test('separate analysis page loads the matching video above the skills', async () => {
  const ui = setup(false);
  await new Promise(resolve => setImmediate(resolve));
  await ui.elements.get('job-list').children[0].onclick();
  const video = ui.elements.get('result-video');
  assert.equal(video.getAttribute('src'), '/api/jobs/a/results/overlay.mp4');
  assert(ui.html.indexOf('id="result-video"') < ui.html.indexOf('id="skill-list"'));
  ui.button(0).onclick(); assert.equal(video.currentTime, 4.25);
});

test('custom video names appear in the list and heading while polling preserves a draft', async () => {
  const ui = setup(false);
  ui.job.label = 'Sunday practice';
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.elements.get('job-list').children[0].children[0].textContent, 'Sunday practice');
  await ui.elements.get('job-list').children[0].onclick();
  assert.equal(ui.elements.get('video-name').textContent, 'Sunday practice');
  assert.match(ui.elements.get('video-filename').textContent, /Original file: Routine/);
  const input = ui.elements.get('video-label');
  input.value = 'Draft name';
  await ui.elements.get('start-analysis').onclick();
  assert.equal(input.value, 'Draft name');
});

test('video begins loading before a slow analysis request finishes', async () => {
  const ui=setup(false);
  await new Promise(resolve=>setImmediate(resolve));
  let release;
  ui.delayAnalysis(new Promise(resolve=>{release=resolve;}));
  const opening=ui.elements.get('job-list').children[0].onclick();
  assert.equal(ui.elements.get('result-video').getAttribute('src'),'/api/jobs/a/results/overlay.mp4');
  assert.equal(ui.elements.get('analysis-panel').hidden,false);
  release();await opening;
});

test('best guesses distinguish shape, start position, rotations, and twists', async () => {
  const ui = setup();
  const base = {skill_index:1, takeoff_position:'feet', landing_position:'feet', twist:0, rotation:{somersault_quarters:4, direction:'backward'}, execution:{execution_position:'tuck_like'}};
  const cases = [
    [base, 'Back somersault (tuck)'],
    [{...base, twist:1}, 'Back full (tuck)'],
    [{...base, twist:.5, rotation:{somersault_quarters:4, direction:'forward'}}, 'Barani (tuck)'],
    [{...base, takeoff_position:'back', twist:1}, 'Back somersault · full twist from back (tuck)'],
    [{...base, takeoff_position:'front', rotation:{somersault_quarters:1, direction:'backward'}}, 'Return to feet from front (tuck)'],
    [{...base, landing_position:'front', rotation:{somersault_quarters:1, direction:'forward'}}, 'Front drop (tuck)'],
    [{...base, rotation:{somersault_quarters:0}}, 'Tuck jump'],
    [{...base, twist:.5, rotation:{somersault_quarters:0}}, 'Half twist · tuck jump'],
    [{...base, twist:1, rotation:{somersault_quarters:0}}, 'Full twist · tuck jump'],
    [{...base, rotation:{somersault_quarters:5}}, '1¼ somersault (tuck)'],
    [{...base, twist:1.5}, 'Back somersault · 1½ twists (tuck)'],
    [{...base, twist:2}, 'Double full (tuck)'],
    [{...base, twist:3}, 'Triple full (tuck)'],
    [{...base, twist:1.5, rotation:{somersault_quarters:4,direction:'forward'}}, 'Rudy (tuck)'],
    [{...base, twist:2.5, rotation:{somersault_quarters:4,direction:'forward'}}, 'Randy (tuck)'],
    [{...base, twist:3, rotation:{somersault_quarters:0}}, 'Triple twist · tuck jump'],
    [{...base, twist:2.5, rotation:{somersault_quarters:8,direction:'forward'}}, 'Double front somersault · 2½ twists (tuck)'],
    [{...base, twist:3, rotation:{somersault_quarters:12,direction:'backward'}}, 'Triple back somersault · triple twist (tuck)'],
    [{...base, twist:3.5}, 'Outside naming range'],
    [{...base, start_clipped:true}, 'Unknown — partial skill'],
    [{...base, rotation:{somersault_quarters:null, candidate_somersault_quarters:4}}, 'Unknown'],
  ];
  for (const [skill, expected] of cases) {
    ui.setData({analysis:{state:'done'}, skills:[skill], reference:{}, shape_images:{}});
    await ui.api.select(ui.job);
    const heading = ui.elements.get('skill-list').children[0].children[0].children[0].children[0];
    assert.equal(heading.textContent, `Best guess: ${expected}`);
  }
});

test('missing twist and start remain unconfirmed; supplied labels do not become guesses', async () => {
  const ui = setup();
  ui.setData({analysis:{state:'done'}, skills:[{skill_index:1, takeoff_position:'unknown', twist:'deferred', rotation:{somersault_quarters:4, direction:'forward'}, execution:{execution_position:'pike_like'}}], reference:{skills:[{skill_index:1, skill_identity:'Barani', twist_count:.5}]}, shape_images:{}});
  await ui.api.select(ui.job);
  const titleBlock = ui.elements.get('skill-list').children[0].children[0].children[0];
  assert.equal(titleBlock.children[0].textContent, 'Best guess: Front somersault (pike)');
  assert.match(titleBlock.children[2].textContent, /starting position, landing position, twist/);
});

test('tentative twist, legacy seat names, and confirmed references cannot name a detected twist', async () => {
  const ui = setup();
  ui.setData({analysis:{state:'done'}, skills:[{
    skill_index:1, twist:{count:.5,candidate_count:.5,status:'tentative',reasons:['competing_windings']},
    rotation:{somersault_quarters:0},
    seat_transition:{name:'Half twist from seat to feet',twist_count:.5,takeoff_position:'seat',landing_position:'feet'},
  }], reference:{skills:[{skill_index:1,skill_identity:'Half twist',user_confirmed:true,twist_count:.5}]}, shape_images:{}});
  await ui.api.select(ui.job);
  const card=ui.elements.get('skill-list').children[0];
  const titleBlock=card.children[0].children[0];
  assert.equal(titleBlock.children[0].textContent,'Best guess: Return to feet');
  assert.match(titleBlock.children[2].textContent,/Unconfirmed: twist/);
  const text=element=>typeof element==='string'?element:[element.textContent||'',...element.children.map(text)].join(' ');
  assert.match(text(card),/Twists Unknown/);
  assert.match(text(card),/Tentative twist — needs review 0.5 turns/);
  assert.match(text(card),/Your confirmed reference: Half twist/);
});

for (const embedded of [true, false]) test(`single player seek bar shows skill boundaries (${embedded ? 'inbox' : 'analysis'})`, async () => {
  const ui = setup(embedded), el = id => ui.elements.get(id);
  if (!embedded) await new Promise(resolve => setImmediate(resolve));
  ui.setData({analysis:{state:'done'}, skills:[{skill_index:1,start_seconds:3,end_seconds:6}],reference:{},shape_images:{}});
  if (embedded) await ui.api.select(ui.job);
  else await el('job-list').children[0].onclick();
  assert.equal(el('skill-timeline'), undefined);
  assert.equal(el('result-video').controls, false);
  assert.equal(el('video-controls').hidden, false);
  ui.button(0).onclick();
  assert.equal(el('skill-markers').children.length, 2);
  assert.match(el('skill-markers').children[0].style.left, /^calc\(10%/);
  assert.match(el('skill-markers').children[1].style.left, /^calc\(20%/);
  el('skill-seek').oninput({target:{value:'5'}});
  assert.equal(el('result-video').currentTime,5);
  el('result-video').currentTime=8;el('result-video').events.timeupdate();
  assert.equal(el('skill-seek').value,8);
  if(embedded) {ui.api.clear();assert.equal(el('skill-markers').children.length,0);}
});

test('player buttons preserve play, pause, and mute controls', async () => {
  const ui = setup(), video = ui.elements.get('result-video');
  video.paused=true; video.play=async()=>{video.paused=false;video.events.play();};
  video.pause=()=>{video.paused=true;video.events.pause();};
  await ui.elements.get('video-play').onclick();assert.equal(video.paused,false);
  assert.equal(ui.elements.get('video-play').attrs['aria-label'],'Pause video');
  await ui.elements.get('video-play').onclick();assert.equal(video.paused,true);
  ui.elements.get('video-mute').onclick();assert.equal(video.muted,true);
  assert.equal(ui.elements.get('video-mute').textContent,'Unmute');
});

test('frame buttons and arrow keys step exact saved timestamps while paused', async () => {
  const ui=setup(), video=ui.elements.get('result-video');
  await ui.api.select(ui.job);
  video.currentTime=0;video.paused=false;
  await ui.elements.get('video-next-frame').onclick();
  assert.equal(video.currentTime,.04);assert.equal(video.paused,true);
  assert.equal(ui.elements.get('video-frame-status').textContent,'Frame 2 / 4');
  await ui.elements.get('video-prev-frame').onclick();assert.equal(video.currentTime,0);
  let prevented=false;
  await ui.keydown({key:'ArrowRight',target:{tagName:'BODY'},preventDefault(){prevented=true;}});
  await new Promise(resolve=>setImmediate(resolve));
  assert(prevented);assert.equal(video.currentTime,.04);
  ui.keydown({key:'ArrowRight',target:{tagName:'INPUT',id:'box-x1'},preventDefault(){throw new Error('should not prevent text input');}});
  assert.equal(video.currentTime,.04);
});

test('slow-motion selector sets playback rate and keeps the default for reloads', () => {
  const ui=setup(), video=ui.elements.get('result-video'), speed=ui.elements.get('video-speed');
  for(const rate of ['0.75','0.5','0.25','0.1','1']) {
    speed.onchange({target:{value:rate}});
    assert.equal(video.playbackRate,Number(rate));
    assert.equal(video.defaultPlaybackRate,Number(rate));
    video.events.ratechange();assert.equal(speed.value,rate);
  }
  speed.onchange({target:{value:'0'}});assert.equal(video.playbackRate,1);
});

test('tightest-point button seeks shape time while keeping skill boundary markers', async () => {
  const ui=setup(), el=id=>ui.elements.get(id);
  ui.setData({analysis:{state:'done'},skills:[{skill_index:1,start_seconds:3,end_seconds:8,execution:{shape_timestamp_seconds:5.25}}],reference:{},shape_images:{}});
  await ui.api.select(ui.job);
  const button=el('skill-list').children[0].children[0].children[2];
  assert.equal(button.textContent,'Jump to tightest point');
  assert.equal(button.disabled,false);button.onclick();
  assert.equal(el('result-video').currentTime,5.25);
  assert.match(el('skill-markers').children[0].style.left,/^calc\(10%/);
  assert.match(el('skill-markers').children[1].style.left,/^calc\(26/);
  el('result-video').readyState=0;button.onclick();
  el('result-video').currentTime=0;el('result-video').readyState=1;el('result-video').events.loadedmetadata();
  assert.equal(el('result-video').currentTime,5.25);
});

test('tightest-point button uses review candidate when present and disables missing timing', async () => {
  const ui=setup();
  ui.setData({analysis:{state:'done'},skills:[
    {skill_index:1,start_seconds:0,end_seconds:5,execution:{shape_timestamp_seconds:2,review_shape_timestamp_seconds:3}},
    {skill_index:2,start_seconds:5,end_seconds:8,execution:{}},
    {skill_index:3,start_seconds:0,end_seconds:1,execution:{shape_timestamp_seconds:0}},
  ],reference:{},shape_images:{}});
  await ui.api.select(ui.job);
  const cards=ui.elements.get('skill-list').children;
  const button=cards[0].children[0].children[2];button.onclick();
  assert.equal(ui.elements.get('result-video').currentTime,3);
  assert.match(button.title,/candidate needs review/);
  assert.equal(cards[1].children[0].children[2].disabled,true);
  cards[2].children[0].children[2].onclick();assert.equal(ui.elements.get('result-video').currentTime,0);
});

for (const embedded of [true,false]) test(`all boundaries persist and below-video button follows seeker (${embedded ? 'inbox' : 'analysis'})`, async () => {
  const ui=setup(embedded), el=id=>ui.elements.get(id);
  if(!embedded) await new Promise(resolve=>setImmediate(resolve));
  ui.setData({analysis:{state:'done'},skills:[
    {skill_index:1,start_seconds:2,end_seconds:5,execution:{shape_timestamp_seconds:3}},
    {skill_index:2,start_seconds:5,end_seconds:8,execution:{shape_timestamp_seconds:6.5}},
    {skill_index:3,start_seconds:9,end_seconds:12,execution:{}},
  ],reference:{},shape_images:{}});
  if(embedded) await ui.api.select(ui.job); else await el('job-list').children[0].onclick();
  const markers=el('skill-markers').children;
  assert.equal(markers.length,5); // shared end/start contact is one point
  assert.match(markers[1].title,/Flight 1 end \/ Flight 2 start/);
  assert.equal(el('jump-current-tightest').disabled,true);
  el('skill-seek').oninput({target:{value:'4'}});
  assert.equal(el('current-skill-label').textContent,'Flight 1');
  el('jump-current-tightest').onclick();assert.equal(el('result-video').currentTime,3);
  // An exact contact belongs to the following skill, irrespective of last clicked card.
  el('skill-seek').oninput({target:{value:'5'}});
  assert.equal(el('current-skill-label').textContent,'Flight 2');
  el('jump-current-tightest').onclick();assert.equal(el('result-video').currentTime,6.5);
  el('result-video').currentTime=7;el('result-video').events.timeupdate();
  assert.equal(el('skill-markers').children,markers);
  el('skill-seek').oninput({target:{value:'8.5'}});assert.equal(el('jump-current-tightest').disabled,true);
  el('skill-seek').oninput({target:{value:'10'}});assert.equal(el('jump-current-tightest').disabled,true);
  assert.equal(el('current-skill-label').textContent,'Flight 3');
  if(embedded) {ui.api.clear();assert.equal(el('skill-markers').children.length,0);assert.equal(el('jump-current-tightest').disabled,true);}
});
