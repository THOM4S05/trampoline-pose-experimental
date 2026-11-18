"""Validate and publish the isolated Shoddy varsities retry."""
import http.cookiejar
import json
from pathlib import Path
import shutil
import sys
import urllib.request
import time
import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trampoline_pose.output import sha256,validate
from trampoline_pose.portal import JobStore
from trampoline_pose.types import TrackerConfig
from trampoline_pose.skill_identification import analyze
from trampoline_pose.bed_contact import add_bed_contact_times
from trampoline_pose.twist_width import attach

identifier='aba69910e6b24073afeb7bc24aa95d5b'
directory=ROOT/'.portal/jobs'/identifier
stage=directory/'rotation-retry'
data=json.loads((stage/'joints.json').read_text());validate(data)
assert data['source']['sha256']==sha256(directory/'source.mov')
report=json.loads((ROOT/'results/shoddy-varsities/verification.json').read_text())
assert report['source_frames']==report['overlay_frames']==2524
assert report['max_overlay_timestamp_error_seconds']<=1/90000

def check(result):
    assert len(result['skills'])==12
    for index,flips,twists in [(5,2,None),(6,2,.5),(8,1,.5),(10,1,.5),(11,2,1),(12,0,None)]:
        skill=result['skills'][index-1]
        assert skill['rotation']['candidate_somersault_count']==flips,(index,skill['rotation'])
        if twists is not None:assert skill['twist']['candidate_count']==twists,(index,skill['twist']['reasons'])
    assert result['skills'][11]['twist']['completed_passages']==0

result=analyze(data)
add_bed_contact_times(data,result,directory/'source.mov',stage/'bed-motion.json')
attach(data,result);check(result)
(stage/'skills.json').write_text(json.dumps(result,indent=2,allow_nan=False))

# Authenticate on localhost; stop only the existing idle experimental server.
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
request=urllib.request.Request('http://localhost:8766/api/login',
    data=json.dumps(dict(key=(ROOT/'.portal/access-key.txt').read_text().strip())).encode(),
    headers={'Content-Type':'application/json','Origin':'http://localhost:8766','X-Portal-Request':'1'})
opener.open(request).close()
jobs=json.load(opener.open('http://localhost:8766/api/jobs'))['jobs']
def active(job):
    if job['state']=='uploading':
        # Partial uploads persist across restarts. Ignore only long-idle ones;
        # preserve their job metadata and upload.part without alteration.
        folder=ROOT/'.portal/jobs'/job['id']
        latest=max(f.stat().st_mtime for f in folder.iterdir() if f.is_file())
        return time.time()-latest<300
    return (job['state'] in ('preparing','queued','processing')
            or (job.get('analysis') or {}).get('state') in ('queued','running'))
assert not [j for j in jobs if active(j)], 'Portal busy'
server=(ROOT/'scripts/serve_twist.py').resolve()
processes=[]
for process in psutil.process_iter(['cmdline']):
    args=process.info['cmdline'] or []
    if any(str(a).endswith('serve_twist.py') and Path(a).resolve()==server for a in args):processes.append(process)
assert processes
for process in processes:process.terminate()
_,alive=psutil.wait_procs(processes,timeout=5)
assert not alive

backup=ROOT/'results/shoddy-varsities/before-retry'
backup.mkdir(parents=True,exist_ok=True)
for name in ('joints.json','joints.csv','overlay.mp4','detections.json','bed-motion.json',
             'skills.json','skills.csv','skill-images.json','job.json'):
    if (directory/name).exists() and not (backup/name).exists():shutil.copy2(directory/name,backup/name)
if (directory/'skill-images').exists() and not (backup/'skill-images').exists():
    shutil.copytree(directory/'skill-images',backup/'skill-images')
for name in ('joints.json','joints.csv','overlay.mp4','detections.json','bed-motion.json'):
    pending=directory/(name+'.pending-retry');shutil.copy2(stage/name,pending);pending.replace(directory/name)

store=JobStore(ROOT/'.portal/jobs',TrackerConfig())
try:
    job=store.jobs[identifier]
    store.update(job,bed_contact_profile='standard',local_tracking_reselection=data['local_tracking_reselection'])
    store.analyze_skills(job)
    assert job['analysis']['state']=='done',job['analysis']
    check(json.loads((directory/'skills.json').read_text()))
    print('Published 12 flights; all six requested flight checks passed.',flush=True)
finally:store.worker.shutdown(wait=True)
