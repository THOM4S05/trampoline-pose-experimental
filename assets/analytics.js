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

  let visitor;
  try {
    const key = `flightroom-visitor:${window.location.pathname.replace(/\/index\.html$/, '/')}`;
    const id = window.localStorage.getItem(key) || window.crypto.randomUUID();
    window.localStorage.setItem(key, id);
    visitor = id;
  } catch {
    // Count activity without treating an unidentified browser as a new visitor.
  }

  function send(event) {
    fetch(url.href, {
      method: 'POST',
      credentials: 'omit',
      keepalive: true,
      body: JSON.stringify({session, visitor, ...event}),
    }).catch(() => {});
  }

  const viewed = new Set();
  window.flightroomAnalytics = {
    videoView(id) {
      if (viewed.has(id)) return;
      viewed.add(id);
      send({page, video: id});
    },
  };
  send({});
})();
