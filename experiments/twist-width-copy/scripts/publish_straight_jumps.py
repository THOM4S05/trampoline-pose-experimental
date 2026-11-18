"""Publish the three reviewed straight-jump pose/analysis retries."""
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trampoline_pose.output import sha256,validate
from trampoline_pose.portal import JobStore
from trampoline_pose.types import TrackerConfig
from trampoline_pose.twist_width import attach

labels=json.loads((ROOT/'results/straight-jump-twists/user-labels.json').read_text())
for label in labels:
    directory=ROOT/'.portal/jobs'/label['job_id']
    staging=directory/'torso-preserved'
    data=json.loads((staging/'joints.json').read_text())
    validate(data)
    assert data['source']['sha256']==sha256(directory/'source.mp4')==label['source_sha256']
    analysis=attach(data,json.loads((staging/'skills.json').read_text()))
    assert analysis['skills'][1]['twist']['candidate_count']==label['expected_twists']
    backup=ROOT/'results/straight-jump-twists/before-v7'/label['job_id']
    backup.mkdir(parents=True,exist_ok=True)
    for name in ('joints.json','joints.csv','overlay.mp4','detections.json','skills.json','skills.csv',
                 'bed-motion.json','skill-images.json','job.json'):
        if (directory/name).exists() and not (backup/name).exists():
            shutil.copy2(directory/name,backup/name)
    if (directory/'skill-images').exists() and not (backup/'skill-images').exists():
        shutil.copytree(directory/'skill-images',backup/'skill-images')
    for name in ('joints.json','joints.csv','overlay.mp4','detections.json','bed-motion.json'):
        pending=directory/(name+'.pending-retry')
        shutil.copy2(staging/name,pending)
        pending.replace(directory/name)
store=JobStore(ROOT/'.portal/jobs',TrackerConfig())
try:
    for label in labels:
        job=store.jobs[label['job_id']]
        store.analyze_skills(job)
        assert job['analysis']['state']=='done'
        result=json.loads((store.directory(job)/'skills.json').read_text())
        skill=result['skills'][1]
        assert skill['twist']['candidate_count']==label['expected_twists']
        print(job['name'],skill['twist']['candidate_skill_identity'],skill['twist']['candidate_count'],flush=True)
finally:
    store.worker.shutdown(wait=True)
