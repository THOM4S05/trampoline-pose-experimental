const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
function setup() {
  let downloads=0;
  const video = {attrs:{}, currentTime:0, playbackRate:1, paused:true,
    getAttribute(name){return this.attrs[name];}, removeAttribute(name){delete this.attrs[name];},
    set src(value){this.attrs.src=value;this.sourceChanges=(this.sourceChanges||0)+1;this.currentTime=0;this.paused=true;},
    load(){this.loads=(this.loads||0)+1;this.currentTime=0;},
  };
  const context={document:{getElementById:id=>id==='result-video' ? video : null}, window:{},
    fetch:()=>{downloads++;throw new Error('A second video download must not be started');},
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/trampoline_pose/web/video-player.js'),'utf8'),context);
  return {api:context.window.reviewVideo, video, downloads:()=>downloads};
}
test('browser streams directly without a second full-file download', ()=>{
  const ui=setup();ui.api.setSource('/a.mp4');
  assert.equal(ui.video.getAttribute('src'),'/a.mp4');
  assert.equal(ui.video.preload,'auto');assert.equal(ui.downloads(),0);
});
test('polling and reopening a clip preserve playback position and speed', ()=>{
  const ui=setup();ui.api.setSource('/a.mp4');
  ui.video.currentTime=12;ui.video.playbackRate=.5;ui.video.paused=false;
  ui.api.setSource('/a.mp4');ui.api.setSource('/a.mp4');
  assert.equal(ui.video.sourceChanges,1);assert.equal(ui.video.currentTime,12);
  assert.equal(ui.video.playbackRate,.5);assert.equal(ui.video.paused,false);
});
test('switching clips replaces the source and clearing unloads it', ()=>{
  const ui=setup();ui.api.setSource('/a.mp4');ui.video.currentTime=12;
  ui.api.setSource('/b.mp4');
  assert.equal(ui.video.getAttribute('src'),'/b.mp4');assert.equal(ui.video.currentTime,0);
  ui.api.clear();assert.equal(ui.video.getAttribute('src'),undefined);assert.equal(ui.video.loads,1);
});
