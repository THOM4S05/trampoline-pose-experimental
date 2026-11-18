"""Publish verified rotated poses and restore standard bed handling for affected jobs."""
import http.cookiejar
import json
from pathlib import Path
import shutil
import sys
import urllib.request

import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trampoline_pose.output import sha256,validate
from trampoline_pose.portal import JobStore
from trampoline_pose.types import TrackerConfig
from trampoline_pose.twist_width import attach

ewan='d9aaa82b04d7421a8a2f42607db7e1bb'
directory=ROOT/'.portal/jobs'/ewan
stage=directory/'rotation-retry'
data=json.loads((stage/'joints.json').read_text())
validate(data)
assert data['source']['sha256']==sha256(directory/'source.mp4')
result=attach(data,json.loads((stage/'skills.json').read_text()))
assert result['skills'][1]['rotation']['candidate_somersault_quarters']==8
assert result['skills'][1]['twist']['candidate_count']==2.5
report=json.loads((ROOT/'results/ewan-full-rudi/verification.json').read_text())
assert report['source_frames']==report['overlay_frames']==653
assert report['max_overlay_timestamp_error_seconds']==0

# Stop only this idle experimental server. Keep its existing localhost binding.
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
request=urllib.request.Request('http://localhost:8766/api/login',
    data=json.dumps(dict(key=(ROOT/'.portal/access-key.txt').read_text().strip())).encode(),
    headers={'Content-Type':'application/json','Origin':'http://localhost:8766','X-Portal-Request':'1'})
opener.open(request).close()
jobs=json.load(opener.open('http://localhost:8766/api/jobs'))['jobs']
assert not [j for j in jobs if j['state'] in ('uploading','preparing','queued','processing')
            or j.get('analysis',{}).get('state') in ('queued','running')], 'Portal busy'
server=(ROOT/'scripts/serve_twist.py').resolve()
processes=[]
for process in psutil.process_iter(['cmdline']):
    args=process.info['cmdline'] or []
    if any(str(a).endswith('serve_twist.py') and Path(a).resolve()==server for a in args):
        processes.append(process)
assert processes, 'Expected experimental server missing'
for process in processes:
    process.terminate()
_,alive=psutil.wait_procs(processes,timeout=5)
assert not alive

affected=[ewan,'1f62c06cebda4bf58c092baa9ceb4791']
for identifier in affected:
    directory=ROOT/'.portal/jobs'/identifier
    if not directory.exists():
        continue
    backup=ROOT/'results/ewan-full-rudi/before-standard-scope'/identifier
    backup.mkdir(parents=True,exist_ok=True)
    for name in ('joints.json','joints.csv','overlay.mp4','detections.json','bed-motion.json',
                 'skills.json','skills.csv','skill-images.json','job.json'):
        if (directory/name).exists() and not (backup/name).exists():
            shutil.copy2(directory/name,backup/name)
    if (directory/'skill-images').exists() and not (backup/'skill-images').exists():
        shutil.copytree(directory/'skill-images',backup/'skill-images')
    if identifier==ewan:
        for name in ('joints.json','joints.csv','overlay.mp4','detections.json','bed-motion.json'):
            pending=directory/(name+'.pending-retry')
            shutil.copy2(stage/name,pending)
            pending.replace(directory/name)

store=JobStore(ROOT/'.portal/jobs',TrackerConfig())
try:
    for identifier in affected:
        if identifier not in store.jobs:
            continue
        job=store.jobs[identifier]
        store.update(job,bed_contact_profile='standard')
        store.analyze_skills(job)
        assert job['analysis']['state']=='done', job['analysis']
        if identifier==ewan:
            result=json.loads((store.directory(job)/'skills.json').read_text())
            skill=result['skills'][1]
            assert skill['rotation']['candidate_somersault_quarters']==8
            assert skill['twist']['candidate_count']==2.5
            print('Published Ewan skill 2: 8 quarters, 2.5 twists (estimates)',flush=True)
        else:
            print('Restored standard bed profile:',job['name'],flush=True)
finally:
    store.worker.shutdown(wait=True)
