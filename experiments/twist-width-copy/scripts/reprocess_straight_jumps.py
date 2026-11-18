"""Stage the recent straight-jump poses with reliable-torso preservation."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trampoline_pose.api import PoseTracker
from trampoline_pose.types import TrackerConfig,AthleteSelection
from trampoline_pose.skill_identification import analyze
from trampoline_pose.bed_contact import add_bed_contact_times
from trampoline_pose.twist_width import attach

tracker=PoseTracker(TrackerConfig.from_yaml(ROOT.parent.parent/'configs/default.yaml'))
ids=['001d3ba6ea5a484c94f6c69de04f5d7a','1008b53c4baf4deba0a4f268e8954d76','3ee0e567e5134cb88aba47e906763de3']
for jid in ids:
    directory=ROOT/'.portal/jobs'/jid
    staging=directory/'torso-preserved';staging.mkdir(exist_ok=True)
    job=json.loads((directory/'job.json').read_text())
    cache=json.loads((directory/'detections.json').read_text())
    # Only pose retry policy changed. Detector assets/runtime and source must
    # match exactly before reusing detector evidence with updated provenance.
    old=json.loads(json.dumps(cache['key']['models']))
    old['runtime']['pose_rotation_fallback']=tracker.backend.provenance['runtime']['pose_rotation_fallback']
    assert old==tracker.backend.provenance
    cache['key']['models']=old
    (staging/'detections.json').write_text(json.dumps(cache,allow_nan=False))
    def progress(stage,n,total):
        if n==1 or n%100==0: print(job['name'],stage,n,total,flush=True)
    result=tracker.process_video(directory/'source.mp4',AthleteSelection(**job['selection']),
        cache_path=staging/'detections.json',progress=progress)
    result.save_json(staging/'joints.json');result.save_csv(staging/'joints.csv')
    result.save_video(staging/'overlay.mp4')
    analysis=analyze(result.data)
    add_bed_contact_times(result.data,analysis,directory/'source.mp4',staging/'bed-motion.json')
    attach(result.data,analysis)
    (staging/'skills.json').write_text(json.dumps(analysis,indent=2,allow_nan=False))
    print('RESULT',job['name'],[(s['skill_index'],s['twist']['candidate_count'],s['twist']['reasons']) for s in analysis['skills']],flush=True)
