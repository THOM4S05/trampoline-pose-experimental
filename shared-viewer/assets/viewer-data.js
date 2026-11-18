/* Static files only. There is no processing API or write endpoint. */
(() => {
  'use strict';
  const root = new URL('./data/', document.baseURI);
  const cache = new Map();
  function asset(id, filename) {
    if (!/^[a-f0-9]{32}$/.test(id) ||
        !/^(overlay\.mp4|analysis\.json|frames\.json|orientation\.json|skills\.(json|csv)|skill-images\/\d+\.jpg)$/.test(filename)) {
      throw new Error('Unknown saved result');
    }
    return new URL(`${id}/${filename}`, root).href;
  }
  async function json(url) {
    if (!cache.has(url)) {
      const request = fetch(url, {credentials: 'omit'}).then(async response => {
        if (!response.ok) throw new Error('A saved result could not be loaded. Please reload the page.');
        return response.json();
      }).catch(error => { cache.delete(url); throw error; });
      cache.set(url, request);
    }
    return cache.get(url);
  }
  function read(path) {
    if (path === '/jobs') return json(new URL('videos.json', root).href);
    const match = path.match(/^\/jobs\/([a-f0-9]{32})(\/analysis)?$/);
    if (!match) return Promise.reject(new Error('This viewer only opens saved results.'));
    return json(asset(match[1], match[2] ? 'analysis.json' : 'frames.json'));
  }
  window.viewerData = Object.freeze({asset, read});
})();
