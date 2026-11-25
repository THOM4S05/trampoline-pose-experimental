(() => {
  'use strict';
  const endpoint = document.querySelector('meta[name="flightroom-analytics"]')?.content.trim();
  if (!endpoint || !window.crypto?.randomUUID) return;
  let url;
  try { url = new URL(endpoint); } catch { return; }
  if (url.protocol !== 'https:' || url.pathname !== '/count') return;

  const page = window.crypto.randomUUID();
  let session = page;
  try {
    const key = 'flightroom-visit';
    session = window.sessionStorage.getItem(key) || page;
    window.sessionStorage.setItem(key, session);
  } catch {
    // A browser with storage disabled can still count this page load.
  }

  function send(event) {
    fetch(url.href, {
      method: 'POST',
      credentials: 'omit',
      keepalive: true,
      body: JSON.stringify(event),
    }).catch(() => {});
  }

  const viewed = new Set();
  window.flightroomAnalytics = {
    videoView(id) {
      if (viewed.has(id)) return;
      viewed.add(id);
      send({session, page, video: id});
    },
  };
  send({session});
})();
