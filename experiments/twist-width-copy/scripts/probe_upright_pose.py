from pathlib import Path
import sys,json,numpy as np
root=Path('experiments/twist-width-copy').resolve();sys.path.insert(0,str(root/'src'))
from trampoline_pose.backend import OpenMMLabBackend
from trampoline_pose.types import TrackerConfig
from trampoline_pose.video import decode
p=root/'.portal/jobs/3ee0e567e5134cb88aba47e906763de3';d=json.loads((p/'joints.json').read_text())
b=OpenMMLabBackend(TrackerConfig.from_yaml(root.parent.parent/'configs/default.yaml'))
for timing,image in decode(p/'source.mp4',d['source']):
 i=timing['frame_index']
 if not 244<=i<=257:continue
 f=d['frames'][i];pts,scores,crop=b._estimate_single(image,f['bbox_xyxy']);print(i,round(timing['timestamp_seconds'],3),'original rot',f['crop_transform'].get('pose_rotation_degrees',0),'upright widths',[round(float(np.linalg.norm(pts[a]-pts[z])),1) for a,z in [(5,6),(11,12)]],'scores',[round(float(scores[k]),2) for k in [5,6,11,12]],flush=True)
 if i==257:break
