/* One browser-managed video stream; changing clips stops the previous clip. */
(() => {
  'use strict';
  const video = document.getElementById('result-video');
  function clear() {
    window.orientationDial?.clear();
    video.pause();
    video.removeAttribute('src');
    video.load();
  }
  function setSource(url) {
    if (video.getAttribute('src') === url) return;
    video.preload = 'metadata';
    video.src = url;
  }
  window.reviewVideo = {setSource, clear};
})();
