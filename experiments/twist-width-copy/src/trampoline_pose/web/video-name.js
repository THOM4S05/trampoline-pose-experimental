(() => {
  'use strict';
  let selectedId = null, savedLabel = null, saving = false;
  const form = document.createElement('form');
  form.className = 'video-name-form';
  const label = document.createElement('label');
  label.htmlFor = 'video-label'; label.textContent = 'Video name';
  const row = document.createElement('div'); row.className = 'video-name-row';
  const input = document.createElement('input');
  input.id = 'video-label'; input.type = 'text'; input.maxLength = 240;
  input.placeholder = 'Give this video a name';
  input.setAttribute('aria-describedby', 'video-filename');
  const button = document.createElement('button');
  button.type = 'submit'; button.className = 'secondary'; button.textContent = 'Save name';
  const filename = document.createElement('p'); filename.id = 'video-filename'; filename.className = 'small';
  const status = document.createElement('p'); status.className = 'small'; status.setAttribute('role', 'status');
  row.append(input, button); form.append(label, row, filename, status);
  document.getElementById('video-name').closest('.editor-heading').after(form);
  window.videoNameEditor = {
    setJob(job) {
      if (selectedId !== job.id || savedLabel !== (job.label || '')) {
        selectedId = job.id; savedLabel = job.label || ''; input.value = savedLabel; status.textContent = '';
      }
      filename.textContent = `Original file: ${job.name} · Leave the name blank to use the filename.`;
      document.getElementById('video-name').textContent = job.label || job.name;
    }
  };
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!selectedId || saving) return;
    const id = selectedId;
    saving = true; button.disabled = true; status.textContent = 'Saving…';
    try {
      const response = await fetch(`/api/jobs/${id}`, {
        method: 'PATCH', headers: {'X-Portal-Request': '1', 'Content-Type': 'application/json'},
        body: JSON.stringify({label: input.value.trim()})
      });
      const job = await response.json();
      if (!response.ok) throw new Error(job.error || 'Could not save the video name');
      if (selectedId === id) {
        window.videoNameEditor.setJob(job);
        status.textContent = job.label ? 'Name saved.' : 'Using the original filename.';
      }
      document.dispatchEvent(new CustomEvent('video-name-saved', {detail: job}));
    } catch (error) { if (selectedId === id) status.textContent = error.message; }
    finally { saving = false; button.disabled = false; }
  });
})();
