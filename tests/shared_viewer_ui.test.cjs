const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '../shared-viewer');

function setup() {
  const elements = new Map();
  class Element {
    constructor(tag) {
      this.tagName = tag; this.children = []; this.events = {}; this.attrs = {};
      this.style = {setProperty(key, value) { this[key] = value; }};
      this.classList = {add(){}};
      this.readyState = 1; this.duration = 30; this.currentTime = 0; this.paused = true;
    }
    set id(value) { this._id = value; elements.set(value, this); }
    get id() { return this._id; }
    append(...items) { this.children.push(...items); }
    replaceChildren(...items) { this.children = items; }
    before() {}
    setAttribute(key, value) { this.attrs[key] = value; }
    getAttribute(key) { return this.attrs[key] ?? null; }
    removeAttribute(key) { delete this.attrs[key]; }
    set src(value) { this.attrs.src = value; }
    addEventListener(name, callback) { (this.events[name] ||= []).push(callback); }
    emit(name) { for (const callback of this.events[name] || []) callback(); }
    scrollIntoView() { this.scrolled = true; }
    focus() { this.focused = true; }
    load() { this.currentTime = 0; this.emit('emptied'); }
    pause() { this.paused = true; this.emit('pause'); }
    async play() { this.paused = false; this.emit('play'); }
  }
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  for (const match of html.matchAll(/id="([^"]+)"/g)) {
    assert(!elements.has(match[1]), 'unique HTML IDs');
    const el = new Element('div'); el.id = match[1];
  }
  const jobs = ['a', 'b'].map(letter => ({id:letter.repeat(32), label:`Clip ${letter}`, state:'done', analysis:{state:'done'}}));
  const data = {analysis:{state:'done', message:'Saved'}, skills:[{
    skill_index:1, start_seconds:1, end_seconds:2, visible_start_seconds:1, visible_end_seconds:2,
    takeoff_position:'feet', landing_position:'feet',
    rotation:{somersault_quarters:4, direction:'backward'},
    execution:{execution_position:'tuck_like', shape_timestamp_seconds:1.5},
    twist:{method:'shoulder_hip_width_passages_v1', candidate_count:.5, events:[{broad_seconds:1.25}]},
    landing_contact:{timestamp_seconds:2.05, frame_index:50}, difficulty:{value:.6}
  }], shape_images:{'1':{available:true, frame_index:30, timestamp_seconds:1.5}}, reference:{routine_start_seconds:1}};
  const calls = [], keys = {};
  const context = {
    URL, Map, Object, Error, Promise,
    document:{baseURI:'https://example.github.io/demo/', getElementById:id => elements.get(id) || null,
      createElement:tag => new Element(tag), createTextNode:text => text,
      addEventListener(name, callback) {keys[name] = callback;}},
    window:{orientationDial:{clear(){}, select(id){ context.dialId = id; }}},
    setTimeout(){}, clearTimeout(){},
    fetch:async (url, options) => {
      calls.push({url, options});
      return {ok:true, json:async () => url.endsWith('/videos.json') ? {jobs} :
        url.endsWith('/frames.json') ? {timestamps:[0, .04, 1, 1.5, 2, 2.05]} : data};
    }
  };
  for (const name of ['viewer-data.js', 'video-player.js', 'skills.js']) {
    vm.runInNewContext(fs.readFileSync(path.join(root, 'assets', name), 'utf8'), context);
  }
  return {elements, context, calls, jobs, data, keys};
}
const settle = () => new Promise(resolve => setImmediate(resolve));

test('preloaded viewer opens a clip, renders evidence and supports review controls', async () => {
  const ui = setup(); await settle();
  const get = id => ui.elements.get(id), video = get('result-video');
  assert.equal(get('video-name').textContent, 'Clip a');
  assert.equal(ui.context.dialId, ui.jobs[0].id);
  assert.equal(get('analysis-results').hidden, false);
  assert.equal(get('skill-list').children.length, 1);
  const heading = get('skill-list').children[0].children[0];
  const click = label => heading.children.find(child => child.textContent === label).onclick();
  click('Jump to tightest point'); assert.equal(video.currentTime, 1.5);
  click('Review twist passage 1'); assert.equal(video.currentTime, 1.25);
  click('Jump to landing'); assert.equal(video.currentTime, 2.05); assert.equal(video.paused, true);
  await get('video-prev-frame').onclick(); assert.equal(video.currentTime, 2);
  await get('video-next-frame').onclick(); assert.equal(video.currentTime, 2.05);
  get('video-speed').onchange({target:{value:'.25'}}); assert.equal(video.playbackRate, .25);
  await get('video-play').onclick(); assert.equal(video.paused, false);
  assert.ok(get('download-skills-json').href.startsWith('https://example.github.io/demo/data/'));
  assert.ok(ui.calls.every(call => !call.options?.method && !call.url.includes('/api/')));
});

test('switching clips stops playback and shows only the new saved results', async () => {
  const ui = setup(); await settle();
  const video = ui.elements.get('result-video');
  video.paused = false; video.currentTime = 2;
  await ui.elements.get('job-list').children[1].onclick();
  assert.equal(video.paused, true); assert.equal(video.currentTime, 0);
  assert.equal(ui.elements.get('video-name').textContent, 'Clip b');
  assert.ok(video.getAttribute('src').includes(ui.jobs[1].id));
  assert.equal(ui.elements.get('job-list').children[1].attrs['aria-pressed'], 'true');
});
