const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');

function viewer(fetch) {
  const context = {window:{}, document:{baseURI:'https://example.github.io/flightroom-demo/'}, URL, Map, Object, Error, Promise, fetch};
  vm.runInNewContext(readFileSync('shared-viewer/assets/viewer-data.js', 'utf8'), context);
  return context.window.viewerData;
}

test('all URLs remain under the GitHub project path; reads reuse static responses', async () => {
  const calls = [];
  const data = viewer(async (url, options) => {
    calls.push({url, options});
    return {ok:true, json:async () => ({jobs:[]})};
  });
  const id = 'a'.repeat(32);
  assert.equal(data.asset(id, 'overlay.mp4'), `https://example.github.io/flightroom-demo/data/${id}/overlay.mp4`);
  await Promise.all([data.read('/jobs'), data.read('/jobs')]);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'https://example.github.io/flightroom-demo/data/videos.json');
  assert.equal(calls[0].options.credentials, 'omit');
  await data.read(`/jobs/${id}/analysis`);
  await data.read(`/jobs/${id}`);
  assert.ok(calls[1].url.endsWith('/analysis.json'));
  assert.ok(calls[2].url.endsWith('/frames.json'));
  assert.throws(() => data.asset('../private', 'overlay.mp4'));
  assert.throws(() => data.asset(id, '../access-key.txt'));
  await assert.rejects(data.read('/login'));
});

test('failed reads can be retried without caching an error forever', async () => {
  let attempts = 0;
  const data = viewer(async () => ({ok:++attempts > 1, json:async () => ({jobs:[]})}));
  await assert.rejects(data.read('/jobs'));
  await data.read('/jobs');
  assert.equal(attempts, 2);
});
