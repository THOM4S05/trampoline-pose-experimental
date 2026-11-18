"""Stage Ewan's rotated detector/pose retry with standard contact handling."""
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

p=ROOT/'.portal/jobs/d9aaa82b04d7421a8a2f42607db7e1bb'
stage=p/'rotation-retry';stage.mkdir(exist_ok=True)
job=json.loads((p/'job.json').read_text())
config=TrackerConfig(model_directory=str(ROOT.parent.parent/'models'),detector_rotations=(0,90,180,270))
tracker=PoseTracker(config)
def progress(kind,n,total):
    if n==1 or n%100==0:print(kind,n,total,flush=True)
result=tracker.process_video(p/'source.mp4',AthleteSelection(**job['selection']),
    cache_path=stage/'detections.json',progress=progress)
result.save_json(stage/'joints.json');result.save_csv(stage/'joints.csv');result.save_video(stage/'overlay.mp4')
analysis=analyze(result.data)
add_bed_contact_times(result.data,analysis,p/'source.mp4',stage/'bed-motion.json')
attach(result.data,analysis)
(stage/'skills.json').write_text(json.dumps(analysis,indent=2,allow_nan=False))
for s in analysis['skills']:
    print('SKILL',s['skill_index'],s['rotation'],{k:v for k,v in s['twist'].items() if k not in ['raw_evidence','zero_twist_evidence']},flush=True)
