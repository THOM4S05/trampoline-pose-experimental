/* Let the browser stream and buffer the selected clip without a second download. */
(() => {
'use strict';
const video = document.getElementById('result-video');
function clear() {
  video.removeAttribute('src');
  video.load();
}
function setSource(url) {
  // Polling and selecting this same clip must preserve playback and its buffer.
  if (video.getAttribute('src') === url) return;
  // Use the browser's media buffer immediately; this is the same stream used
  // for playback, so it does not create a second full-file download.
  video.preload = 'auto';
  video.src = url;
}
window.reviewVideo = {setSource, clear};
})();
