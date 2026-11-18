"""Compact, frame-timed orientation evidence for the review player."""
import math

import numpy as np

from .skill_identification import centre
from .twist_width import measure


def torso_degrees(frame):
    axis = centre(frame, 'shoulder') - centre(frame, 'hip')
    if np.isfinite(axis).all() and np.linalg.norm(axis) > 10:
        return round(math.degrees(math.atan2(axis[0], -axis[1])) % 360, 2)
    return None


def orientation_samples(data):
    widths,refs=measure(data)
    samples=[]
    for frame,row in zip(data['frames'],widths):
        samples.append([frame['frame_index'],frame['timestamp_seconds'],torso_degrees(frame),
                        row['shoulder_fraction'],row['hip_fraction'],frame['track_state']])
    return dict(columns=['frame_index','timestamp_seconds','torso_degrees',
                         'shoulder_fraction','hip_fraction','track_state'],
                convention='Image-plane hip-to-shoulder angle: 0 upright, 90 leaning right, 180 inverted. Widths are twist evidence, not 3D heading.',
                references_px=refs,samples=samples)
