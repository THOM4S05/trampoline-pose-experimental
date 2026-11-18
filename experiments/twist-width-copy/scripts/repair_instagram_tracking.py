"""Stage a tracking retry for the compressed Instagram development clip."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trampoline_pose.api import PoseTracker
from trampoline_pose.types import TrackerConfig,AthleteSelection

directory=ROOT/'.portal/jobs/82ca1f7b2df443ffb10eeb3fad06f6cc'
job=json.loads((directory/'job.json').read_text())
staging=directory/'tracking-retry'
staging.mkdir(exist_ok=True)
config=TrackerConfig.from_yaml(ROOT/'configs/instagram.yaml')
tracker=PoseTracker(config)
last=None
def progress(stage,n,total):
    global last
    if n%100==0 or stage!=last:
        print(stage,n,total,flush=True)
        last=stage
result=tracker.process_video(directory/'source.mp4',AthleteSelection(**job['selection']),
    progress=progress,cache_path=staging/'detections.json')
result.save_json(staging/'joints.json')
result.save_csv(staging/'joints.csv')
result.save_video(staging/'overlay.mp4')
print('Coverage',result.data['diagnostics']['track_states'],flush=True)
