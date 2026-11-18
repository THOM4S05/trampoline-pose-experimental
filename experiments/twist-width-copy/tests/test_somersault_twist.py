import numpy as np
import pytest

from trampoline_pose.somersault_twist import candidate
from trampoline_pose.twist_width import WidthSettings,decode


def recording(half_turns=1,head_only=False):
    frames,rows=[],[]
    for i,t in enumerate(np.linspace(0,2,241)):
        flip=2*np.pi*t
        twist=half_turns*np.pi*t/2
        axis=np.array([np.sin(flip),-np.cos(flip)])
        right=np.array([-axis[1],axis[0]])
        hip=np.array([200.,200.]);shoulder=hip+60*axis
        ear=shoulder+25*axis
        nose=ear+15*np.cos(twist)*right
        width=.1 if head_only else .1+.9*abs(np.sin(twist))
        positions=dict(left_hip=hip-10*width*right,right_hip=hip+10*width*right,
            left_shoulder=shoulder-20*width*right,right_shoulder=shoulder+20*width*right,
            left_ear=ear-right,right_ear=ear+right,nose=nose)
        frames.append(dict(frame_index=i,timestamp_seconds=t,track_state='tracked',
            joints={n:dict(status='observed',flags=[],final=dict(x=p[0],y=p[1])) for n,p in positions.items()}))
        rows.append(dict(frame_index=i,timestamp_seconds=t,track_state='tracked',
                         shoulder_fraction=width,hip_fraction=width))
    return dict(frames=frames),rows


@pytest.mark.parametrize('half_turns',[1,2,3,5])
def test_body_relative_direction_counts_twists_during_somersaults(half_turns):
    data,rows=recording(half_turns)
    skill=dict(rotation=dict(somersault_count=2),start_clipped=False,end_clipped=False)
    previous=dict(start_seconds=0,end_seconds=2,candidate_count=None,reasons=['side_on_finish_not_established'])
    result=candidate(data,rows,skill,previous,WidthSettings())
    assert result['candidate_count']==half_turns*.5
    assert len(result['events'])==half_turns
    assert 'body_relative_facing_candidate_needs_review' in result['review_reasons']


@pytest.mark.parametrize('failure',['head_only','no_twist','long_gap','lost','partial','small_reference'])
def test_facing_changes_need_paired_width_evidence_and_complete_tracking(failure):
    data,rows=recording(0 if failure=='no_twist' else 1,head_only=failure=='head_only')
    skill=dict(rotation=dict(somersault_count=2),start_clipped=failure=='partial')
    previous=dict(start_seconds=0,end_seconds=2,candidate_count=None,reasons=[])
    if failure=='long_gap':
        for row in rows[100:120]:row['shoulder_fraction']=None
    if failure=='lost':rows[100]['track_state']='lost'
    if failure=='small_reference':previous['reasons']=['hip_reference_too_small']
    assert candidate(data,rows,skill,previous,WidthSettings()) is None


def test_twist_window_excludes_previous_flights_landing_broadening():
    _,rows=recording(1)
    for i,row in enumerate(rows):row['timestamp_seconds']+=.3
    previous=[dict(frame_index=-10+i,timestamp_seconds=i*.02,shoulder_fraction=w,hip_fraction=w)
              for i,w in enumerate([.1,.1,1.,1.,.1,.1])]
    skill=dict(visible_start_seconds=0,visible_end_seconds=2.3,
        rotation=dict(somersault_count=2,window_start_seconds=.3,window_end_seconds=2.3))
    result=decode(previous+rows,dict(shoulder=40,hip=20),skill)
    assert result['candidate_count']==.5
    assert result['start_seconds']==.3
    assert all(e['start_frame']>=0 for e in result['events'])
