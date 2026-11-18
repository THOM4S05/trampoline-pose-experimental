"""Stage rotated detections and a local, explicitly reseeded tail repair."""
import json
from pathlib import Path
import sys
import numpy as np
from dataclasses import replace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import trampoline_pose.api as api
from trampoline_pose.types import TrackerConfig,AthleteSelection
from trampoline_pose.tracking import associate
from trampoline_pose.geometry import iou
from trampoline_pose.skill_identification import analyze
from trampoline_pose.bed_contact import add_bed_contact_times
from trampoline_pose.twist_width import attach
from trampoline_pose.skill_identification import usable,centre
from trampoline_pose.skeleton import NAMES
from trampoline_pose.backend import OpenMMLabBackend

p=ROOT/'.portal/jobs/aba69910e6b24073afeb7bc24aa95d5b'
stage=p/'rotation-retry';stage.mkdir(exist_ok=True)
job=json.loads((p/'job.json').read_text())
config=TrackerConfig(model_directory=str(ROOT.parent.parent/'models'),detector_rotations=(0,90,180,270))
old=json.loads((p/'joints.json').read_text())
cached=json.loads((p/'detections.json').read_text())
retry={f['frame_index'] for f in old['frames'] if any(usable(f,n) is None
    for n in ('left_shoulder','right_shoulder','left_hip','right_hip'))}
retry.update(range(2325,2370))
axes=np.array([centre(f,'shoulder')-centre(f,'hip') for f in old['frames']])
theta=np.arctan2(axes[:,0],-axes[:,1])
dt=np.diff([f['timestamp_seconds'] for f in old['frames']])
speed=np.abs((np.diff(theta)+np.pi)%(2*np.pi)-np.pi)/dt
for i in np.flatnonzero((speed>40) & (np.arange(len(speed))>=948) & (np.arange(len(speed))<=1170)):
    retry.update(range(max(0,int(i)-2),min(len(axes),int(i)+4)))
print('Targeted detection/pose retries:',len(retry),flush=True)

class TargetedBackend(OpenMMLabBackend):
    def __init__(self):
        super().__init__(config)
        self.detect_index=0
        self.pose_index=0
        self.provenance['runtime']['targeted_retry_frames']=sorted(retry)
        self.provenance['runtime']['reuse_policy']='Original detector/pose evidence outside retry frames when association box unchanged'
    def detect(self,image):
        i=self.detect_index;self.detect_index+=1
        if i in retry:return super().detect(image)
        record=cached['records'][i]
        return np.array(record['boxes']).reshape(-1,4),np.array(record['scores'])
    def estimate(self,image,box):
        i=self.pose_index;self.pose_index+=1
        f=old['frames'][i]
        if i in retry or f['bbox_xyxy'] is None or not np.allclose(box,f['bbox_xyxy'],atol=.01):
            return super().estimate(image,box)
        return (np.array([[f['joints'][n]['raw'][k] if f['joints'][n]['raw'][k] is not None else np.nan
                           for k in ('x','y')] for n in NAMES]),
                np.array([f['joints'][n]['raw']['model_score'] if f['joints'][n]['raw']['model_score'] is not None else np.nan for n in NAMES]),
                f['crop_transform'])

def repaired_association(records,selection,settings,seed_appearance):
    tracks=[dict(bbox_xyxy=f['bbox_xyxy'],track_state=f['track_state'],diagnostics=dict(f['diagnostics']))
            for f in old['frames']]
    # Keep established athlete identity. Only refine a crop where the rotated
    # detector agrees spatially with the existing athlete track.
    for i in sorted(retry):
        if i>=2315:continue
        box=tracks[i]['bbox_xyxy']
        if box is None:continue
        overlap,k=max(((iou(box,b),k) for k,b in enumerate(records[i]['boxes'])),default=(0,-1))
        if overlap<.65:continue
        tracks[i]=dict(bbox_xyxy=records[i]['boxes'][k],track_state='tracked',
            diagnostics={**tracks[i]['diagnostics'],'reason':'rotated_detection_agrees_with_existing_athlete',
                         'prior_box_iou':overlap})
    # Explicitly reviewed native frame 2423: gymnast in the air after the last
    # double, not the spectator standing against the wall. This clip repair
    # leaves the general association algorithm and all earlier flights alone.
    index=2423
    expected=np.array([585.,229.,835.,955.])
    overlap,k=max((iou(expected,b),k) for k,b in enumerate(records[index]['boxes']))
    assert overlap>.8
    anchor=records[index]['boxes'][k]
    tail=associate(records,AthleteSelection(index,tuple(anchor)),replace(settings,minimum_seed_scale=.6),
                   records[index]['appearances'][k])
    start=2315
    assert iou(tail[start]['bbox_xyxy'],old['frames'][start]['bbox_xyxy'])>.8
    for i in range(start,len(tracks)):
        tracks[i]=tail[i]
        tracks[i]['diagnostics']['local_reselection_frame']=index
    return tracks

api.associate=repaired_association
tracker=api.PoseTracker(config,backend=TargetedBackend())
def progress(kind,n,total):
    if kind=='pose':tracker.backend.pose_index=n
    if n==1 or n%200==0:print(kind,n,total,flush=True)
result=tracker.process_video(p/'source.mov',AthleteSelection(**job['selection']),
    cache_path=stage/'detections.json',progress=progress)
result.data['local_tracking_reselection']=dict(frame_index=2423,bbox_xyxy=[585,229,835,955],
    applied_from_frame=2315,minimum_seed_scale=.6,
    reason='Reviewed gymnast after background-person identity switch')
result.save_json(stage/'joints.json');result.save_csv(stage/'joints.csv');result.save_video(stage/'overlay.mp4')
analysis=analyze(result.data)
add_bed_contact_times(result.data,analysis,p/'source.mov',stage/'bed-motion.json')
attach(result.data,analysis)
(stage/'skills.json').write_text(json.dumps(analysis,indent=2,allow_nan=False))
for s in analysis['skills']:
    print('SKILL',s['skill_index'],round(s['visible_start_seconds'],3),round(s['visible_end_seconds'],3),
        s['rotation']['candidate_somersault_count'],s['rotation']['reasons'],
        {k:s['twist'].get(k) for k in ('candidate_count','count','completed_passages','reasons','review_reasons')},flush=True)
