"""Reprocess the reviewed Liam clip using an explicit spectator-free flight region."""
import json
from pathlib import Path
import sys
from dataclasses import replace
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
COPY = ROOT / 'experiments/twist-width-copy'
sys.path.insert(0, str(COPY / 'src'))
from trampoline_pose.api import PoseTracker
from trampoline_pose.backend import OpenMMLabBackend
from trampoline_pose.types import TrackerConfig, AthleteSelection
from trampoline_pose.skeleton import NAMES

job_dir = COPY / '.portal/jobs/f96c0c42f29845f3b2af56191095760f'
stage = job_dir / 'flight-region-retry'
stage.mkdir(exist_ok=True)
old = json.loads((job_dir / 'joints.json').read_text())
config = TrackerConfig(**old['effective_config'])
selection = replace(AthleteSelection(**old['selection']),
                    flight_region_xyxy=(600, 0, 1300, 930))


class ReuseUnchangedPose(OpenMMLabBackend):
    frame_index = 0

    def estimate(self, image, box):
        frame = old['frames'][self.frame_index]
        if frame['bbox_xyxy'] is None or not np.allclose(box, frame['bbox_xyxy'], atol=.01):
            return super().estimate(image, box)
        points = np.array([[frame['joints'][name]['raw'][axis]
                            if frame['joints'][name]['raw'][axis] is not None else np.nan
                            for axis in ('x', 'y')] for name in NAMES])
        scores = np.array([frame['joints'][name]['raw']['model_score']
                           if frame['joints'][name]['raw']['model_score'] is not None else np.nan
                           for name in NAMES])
        return points, scores, frame['crop_transform']


backend = ReuseUnchangedPose(config)


def progress(kind, count, total):
    if kind == 'pose':
        backend.frame_index = count
    if count == 1 or count % 200 == 0:
        print(kind, count, total, flush=True)


result = PoseTracker(config, backend).process_video(
    job_dir / 'source.mov', selection, cache_path=job_dir / 'detections.json', progress=progress)
result.data['local_tracking_repair'] = {
    'reason': 'Reviewed flight region excludes spectator centres at the bottom of the image',
    'flight_region_xyxy': list(selection.flight_region_xyxy),
    'reuse_policy': 'Reuse cached detector evidence and unchanged pose crops; estimate all changed crops',
}
result.save_json(stage / 'joints.json')
result.save_csv(stage / 'joints.csv')
print('Rendering overlay', result.data['diagnostics']['track_states'], flush=True)
result.save_video(stage / 'overlay.mp4')
print('REPAIR_READY', flush=True)
