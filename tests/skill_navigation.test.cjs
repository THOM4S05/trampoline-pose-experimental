const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '../src/trampoline_pose/web');

test('flight difficulty shows a provisional value and component breakdown', async () => {
  const ui = setup();
  ui.setData({analysis:{state:'done'}, skills:[{skill_index:1,
    difficulty:{value:1.3, status:'provisional', components:{somersault:1, position:.2, backward_bonus:.1}},
  }, {skill_index:2, difficulty:{value:null, reasons:['partial_flight']}}], reference:{}, shape_images:{}});
  await ui.api.select(ui.job);
  const fields = index => ui.elements.get('skill-list').children[index].children.find(child => child.tagName === 'dl').children;
  const find = (index, name) => fields(index).find(field => field.children[0].textContent === name).children[1].textContent;
  assert.equal(find(0, 'Difficulty (FIG 2025–2028 estimate)'), '1.3 · provisional');
  assert.match(find(0, 'Difficulty breakdown'), /position 0.2/);
  assert.equal(find(1, 'Difficulty (FIG 2025–2028 estimate)'), 'Unavailable — partial flight');
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
    setAttribute(key, value) { this.attrs[key] = value; }
    getAttribute(key) { return this.attrs[key] ?? null; }
    removeAttribute(key) { delete this.attrs[key]; }
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
  let analysisGate = null, keydown = null;
  const context = {document:{getElementById:id => elements.get(id) || null, createElement:tag => new Element(tag), createTextNode:text => text, addEventListener(name,callback){if(name==='keydown')keydown=callback;}}, window:{}, setTimeout(){}, clearTimeout(){}, setInterval(){}, fetch:async url => {
    if (analysisGate && url.endsWith('/analysis')) await analysisGate;
    return {ok:true, json:async () => url === '/api/jobs' ? {jobs:[job]} : url === '/api/jobs/a' ? {...job,timestamps:[0,.04,.1,.15]} : data};
  }};
  context.window.reviewVideo = {
    setSource(src) { const video=elements.get('result-video'); if(video.getAttribute('src')!==src) video.src=src; },
    clear() { const video=elements.get('result-video'); video.removeAttribute('src'); video.load(); },
  };
  vm.runInNewContext(fs.readFileSync(path.join(root, 'skills.js'), 'utf8'), context);
  return {elements, job, api:context.window.skillAnalysis, html, keydown(event){return keydown(event);}, delayAnalysis(value){analysisGate=value;}, setData(value){data=value;}, button(index){return elements.get('skill-list').children[index].children[0].children[1];}};
}

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
  assert(cards[0].includes('Time of flight (video estimate) 1.235 s'));
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
    [{...base, rotation:{somersault_quarters:5}}, 'Outside naming range'],
    [{...base, twist:1.5}, 'Outside naming range'],
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
  assert.match(text(card),/Twist \(supported\) Unknown/);
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
