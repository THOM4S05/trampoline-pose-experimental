const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.join(__dirname,'../src/trampoline_pose/web');

function setup(fetcher) {
  class Element {
    constructor(){this.style={};this.events={};this.attrs={};this.hidden=false;}
    addEventListener(name,fn){(this.events[name] ||= []).push(fn);}
    emit(name){for(const fn of this.events[name] || [])fn();}
    setAttribute(k,v){this.attrs[k]=v;}
    getAttribute(k){return this.attrs[k] ?? null;}
    removeAttribute(k){delete this.attrs[k];}
  }
  const elements=new Map();
  for(const match of fs.readFileSync(path.join(web,'index.html'),'utf8').matchAll(/id="([^"]+)"/g)) elements.set(match[1],new Element());
  const video=elements.get('result-video');video.currentTime=0;video.paused=true;
  video.setAttribute('src','/api/jobs/a/results/overlay.mp4');
  const callbacks=new Map();let next=1;
  video.requestVideoFrameCallback=fn=>{const id=next++;callbacks.set(id,fn);return id;};
  video.cancelVideoFrameCallback=id=>callbacks.delete(id);
  const calls=[];
  const context={document:{getElementById:id=>elements.get(id)},window:{},fetch:async url=>{
    calls.push(url);return {ok:true,json:async()=>fetcher ? fetcher(url) : {samples:[
      [0,0,0,.1,.1,'tracked'],[1,.04,90,.8,.9,'tracked'],[2,.17,180,.2,.2,'tracked'],[3,.25,null,null,null,'uncertain']]}};
  }};
  vm.runInNewContext(fs.readFileSync(path.join(web,'orientation-dial.js'),'utf8'),context);
  return {elements,video,calls,api:context.window.orientationDial,callbacks,context};
}

test('dial follows irregular source frame intervals when seeking',async()=>{
  const ui=setup();await ui.api.select('a');
  ui.video.currentTime=.14;ui.video.emit('seeked');
  assert.equal(ui.elements.get('orientation-needle').getAttribute('transform'),'rotate(90 50 50)');
  assert.match(ui.elements.get('orientation-dial').getAttribute('aria-label'),/Frame 2 · 0.040 s/);
  ui.video.currentTime=.17;ui.video.emit('seeked');
  assert.equal(ui.elements.get('orientation-needle').getAttribute('transform'),'rotate(180 50 50)');
  assert.match(ui.elements.get('orientation-dial').getAttribute('aria-label'),/Inverted/);
});

test('playing dial uses displayed frame mediaTime and stops on pause',async()=>{
  const ui=setup();await ui.api.select('a');
  ui.video.paused=false;ui.video.emit('play');
  const [id,fn]=[...ui.callbacks][0];ui.callbacks.delete(id);fn(0,{mediaTime:.17});
  assert.equal(ui.elements.get('orientation-needle').getAttribute('transform'),'rotate(180 50 50)');
  ui.video.currentTime=.17;ui.video.paused=true;ui.video.emit('pause');
  assert.equal(ui.callbacks.size,0);
});

test('unreliable frame hides both hands',async()=>{
  const ui=setup();await ui.api.select('a');
  ui.video.currentTime=.25;ui.video.emit('timeupdate');
  assert.equal(ui.elements.get('orientation-needle').style.visibility,'hidden');
  assert.equal(ui.elements.get('orientation-dial').getAttribute('aria-label'),'Tracking uncertain');
});

test('switching clips ignores an older in-flight response',async()=>{
  let release;const pending=new Promise(resolve=>release=resolve);
  const ui=setup(url=>url.includes('/a/') ? pending : {samples:[[0,0,270,.4,.4,'tracked']]});
  const first=ui.api.select('a');await ui.api.select('b');
  release({samples:[[0,0,90,1,1,'tracked']]});await first;
  assert.equal(ui.elements.get('orientation-needle').getAttribute('transform'),'rotate(270 50 50)');
});

test('same clip polling preserves data and source-load emptied event does not erase it',async()=>{
  const ui=setup();await ui.api.select('a');await ui.api.select('a');
  assert.equal(ui.calls.length,1);
  ui.video.emit('emptied');
  assert.equal(ui.elements.get('orientation-panel').hidden,false);
  assert.equal(ui.elements.get('orientation-needle').getAttribute('transform'),'rotate(0 50 50)');
  ui.api.clear();assert.equal(ui.elements.get('orientation-panel').hidden,true);
});

for(const page of ['index.html','skills.html']) test(`dial sits directly below the player on ${page}`,()=>{
  const html=fs.readFileSync(path.join(web,page),'utf8');
  assert(html.indexOf('id="orientation-panel"')>html.indexOf('id="video-controls"'));
  assert(html.indexOf('id="orientation-panel"')<html.indexOf('class="video-skill-actions"'));
  assert(html.includes('/assets/orientation-dial.js'));
  assert(html.includes('orientation-hand-long'));
  assert(html.includes('orientation-hand-short'));
  assert(!html.includes('orientation-widths'));
  assert(!html.includes('orientation-readout'));
});

test('shared review player loads and clears the matching orientation trace',async()=>{
  const ui=setup();
  Object.defineProperty(ui.video,'src',{get(){return this.getAttribute('src');},set(v){this.setAttribute('src',v);}});
  ui.video.load=()=>ui.video.emit('emptied');
  vm.runInNewContext(fs.readFileSync(path.join(web,'video-player.js'),'utf8'),ui.context);
  ui.context.window.reviewVideo.setSource('/api/jobs/b/results/overlay.mp4');
  await new Promise(setImmediate);
  assert.equal(ui.calls[0],'/api/jobs/b/orientation');
  assert.equal(ui.elements.get('orientation-panel').hidden,false);
  ui.context.window.reviewVideo.clear();
  assert.equal(ui.elements.get('orientation-panel').hidden,true);
});
