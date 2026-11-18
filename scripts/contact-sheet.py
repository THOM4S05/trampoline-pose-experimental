"""Extract native video frames for reviewing bed-contact timing."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
from trampoline_pose.video import decode

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('job', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--times', type=float, nargs='+', required=True)
p.add_argument('--crop', type=int, nargs=4)
a = p.parse_args()
d = json.loads((a.job / 'joints.json').read_text())
job = json.loads((a.job / 'job.json').read_text())
stamps = np.array([f['timestamp_seconds'] for f in d['frames']])
selected = {int(np.argmin(abs(stamps - t))) for t in a.times}
panels = []
for timing, frame in decode(a.job / ('source' + job['extension']), d['source']):
    i = timing['frame_index']
    if i not in selected:
        continue
    if a.crop:
        x1,y1,x2,y2 = a.crop
        frame = frame[y1:y2,x1:x2]
    scale = min(440/frame.shape[1], 450/frame.shape[0])
    small = cv2.resize(frame, None, fx=scale, fy=scale)
    panel = np.full((490, 450, 3), 245, np.uint8)
    panel[:small.shape[0],:small.shape[1]] = small
    cv2.putText(panel, f'Frame {i} / {timing["timestamp_seconds"]:.6f} s', (5,475), cv2.FONT_HERSHEY_SIMPLEX,.55,(0,0,0),1)
    panels.append(panel)
    selected.remove(i)
    if not selected:
        break
while len(panels) % 4:
    panels.append(np.full_like(panels[0],245))
sheet = np.concatenate([np.concatenate(panels[i:i+4],axis=1) for i in range(0,len(panels),4)],axis=0)
a.output.parent.mkdir(parents=True,exist_ok=True)
cv2.imwrite(str(a.output),sheet)
print(a.output.resolve())
