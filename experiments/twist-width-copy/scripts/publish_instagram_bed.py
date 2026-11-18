"""Publish reviewed bed-contact analysis in the existing experimental job."""
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trampoline_pose.output import sha256
from trampoline_pose.portal import JobStore
from trampoline_pose.types import TrackerConfig

job_id='82ca1f7b2df443ffb10eeb3fad06f6cc'
directory=ROOT/'.portal/jobs'/job_id
data=json.loads((directory/'joints.json').read_text())
assert data['source']['sha256']==sha256(directory/'source.mp4')
staging=directory/'bed-retry'
reviewed=json.loads((staging/'skills.json').read_text())
assert sum(c.get('bed_contact') is not None for c in reviewed['contacts'])==14
backup=ROOT/'results/instagram-tracking/before-bed-v4'
backup.mkdir(parents=True,exist_ok=True)
for name in ('skills.json','skills.csv','bed-motion.json','skill-images.json','job.json'):
    if (directory/name).exists() and not (backup/name).exists():
        shutil.copy2(directory/name,backup/name)
if (directory/'skill-images').exists() and not (backup/'skill-images').exists():
    shutil.copytree(directory/'skill-images',backup/'skill-images')
pending=directory/'bed-motion.pending-retry.json'
shutil.copy2(staging/'bed-motion.json',pending)
pending.replace(directory/'bed-motion.json')
store=JobStore(ROOT/'.portal/jobs',TrackerConfig())
try:
    job=store.jobs[job_id]
    store.update(job,bed_contact_profile='video_recovery')
    store.analyze_skills(job)
    assert job['analysis']['state']=='done'
    analysis=json.loads((directory/'skills.json').read_text())
    assert sum(c.get('bed_contact') is not None for c in analysis['contacts'])==14
    print('Published 14 bed contacts,',len(analysis['skills']),'flight spans; analysis version',job['analysis']['analysis_version'])
finally:
    store.worker.shutdown(wait=True)
