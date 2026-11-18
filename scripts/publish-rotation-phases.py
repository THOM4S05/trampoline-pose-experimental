"""Publish the validated Liam rotation repair and restart the idle experiment."""
import copy
from datetime import datetime, timezone
import http.cookiejar
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

import psutil

ROOT = Path(__file__).resolve().parents[1]
COPY = ROOT / 'experiments/twist-width-copy'
sys.path.insert(0, str(COPY / 'src'))
from trampoline_pose.output import sha256
from trampoline_pose.skill_identification import write_csv

portal = COPY / '.portal'
directory = portal / 'jobs/f96c0c42f29845f3b2af56191095760f'
stage = directory / 'rotation-phase-retry'
before = json.loads((directory / 'skills.json').read_text())
after = json.loads((stage / 'skills.json').read_text())
expected = {3: 1.75, 5: 1, 6: 2, 7: 2, 8: 2, 12: 2}
assert len(before['skills']) == len(after['skills']) == 13
for old, new in zip(before['skills'], after['skills']):
    assert new['rotation']['candidate_somersault_count'] == expected.get(
        new['skill_index'], old['rotation']['candidate_somersault_count'])
    old_other, new_other = copy.deepcopy(old), copy.deepcopy(new)
    old_other.pop('rotation'); new_other.pop('rotation')
    assert old_other == new_other, 'Non-rotation analysis changed'
    assert old['rotation']['somersault_count'] == new['rotation']['somersault_count']
    assert old['rotation']['projected_turns'] == new['rotation']['projected_turns']

rows = [{k: s[k] for k in ('skill_index', 'start_frame', 'end_frame', 'start_seconds',
                          'end_seconds', 'start_clipped', 'end_clipped',
                          'supplied_skill_identity', 'predicted_skill_identity', 'review_status',
                          'time_of_flight_seconds', 'time_of_flight', 'landing_contact')}
        | {'rotation_' + k if k == 'reasons' else k: v for k, v in s['rotation'].items()}
        | {'shape_' + k if k == 'reasons' else k: v for k, v in s['execution'].items()}
        | {'candidate_twists': s['twist']['candidate_count'],
           'candidate_half_twists': None if s['twist']['candidate_count'] is None else s['twist']['candidate_count'] * 2,
           'twist_status': s['twist']['status'], 'twist_reasons': ';'.join(s['twist']['reasons'])}
        for s in after['skills']]
write_csv(stage / 'skills.csv', rows)
unchanged = {name: sha256(directory / name) for name in
             ('source.mov', 'joints.json', 'joints.csv', 'overlay.mp4', 'skill-reference.json', 'skill-images.json')}

opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
request = urllib.request.Request('http://localhost:8766/api/login',
    data=json.dumps({'key': (portal / 'access-key.txt').read_text().strip()}).encode(),
    headers={'Content-Type': 'application/json', 'Origin': 'http://localhost:8766', 'X-Portal-Request': '1'})
opener.open(request, timeout=10).close()
with opener.open('http://localhost:8766/api/jobs', timeout=10) as response:
    jobs = json.load(response)['jobs']
assert not [j for j in jobs if j['state'] in ('preparing', 'queued', 'processing')
            or (j.get('analysis') or {}).get('state') in ('queued', 'running')], 'Portal busy'
server = (COPY / 'scripts/serve_twist.py').resolve()
processes = []
for process in psutil.process_iter(['cmdline']):
    args = process.info['cmdline'] or []
    if '8766' in args and any(str(a).endswith('serve_twist.py') and Path(a).resolve() == server for a in args):
        processes.append(process)
assert processes, 'Experimental server not found'
for process in processes:
    process.terminate()
_, alive = psutil.wait_procs(processes, timeout=5)
assert not alive, 'Experimental server did not stop'

try:
    backup = directory / 'before-rotation-phase-repair'
    backup.mkdir(exist_ok=True)
    for name in ('skills.json', 'skills.csv', 'job.json'):
        if not (backup / name).exists():
            shutil.copy2(directory / name, backup / name)
    for name in ('skills.json', 'skills.csv'):
        pending = directory / (name + '.pending-phase-repair')
        shutil.copy2(stage / name, pending)
        pending.replace(directory / name)
    job = json.loads((directory / 'job.json').read_text())
    job['analysis']['analysis_version'] = 16
    job['updated_at'] = datetime.now(timezone.utc).isoformat()
    pending = directory / 'job.pending-phase-repair.json'
    pending.write_text(json.dumps(job, allow_nan=False))
    pending.replace(directory / 'job.json')
    assert unchanged == {name: sha256(directory / name) for name in unchanged}
    report = dict(expected_counts=expected, non_rotation_analysis_unchanged=True,
                  unchanged_files_sha256=unchanged, backup=str(backup))
    (stage / 'publication-verification.json').write_text(json.dumps(report, indent=2))
    print('Published six recovered counts. Tracking, boundaries, shapes, twist, video and references unchanged.', flush=True)
finally:
    with (portal / 'rotation-phase-server.stdout.log').open('w') as out, (portal / 'rotation-phase-server.stderr.log').open('w') as err:
        child = subprocess.Popen([str(ROOT / '.venv/Scripts/python.exe'), '-u', str(server),
            '--port', '8766', '--public-url', 'https://desktop-qfvrcme.tail48ad3d.ts.net:8443'],
            cwd=str(ROOT), stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
    print('Restarting experimental server', child.pid, flush=True)
