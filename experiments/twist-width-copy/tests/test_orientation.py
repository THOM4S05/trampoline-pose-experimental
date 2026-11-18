import math

import pytest

from trampoline_pose.orientation import orientation_samples


def frame(angle,time=0,state='tracked'):
    r=math.radians(angle)
    shoulders=(100+50*math.sin(r),100-50*math.cos(r))
    joints={}
    for part,centre,width in [('shoulder',shoulders,30),('hip',(100,100),20)]:
        for side,sign in [('left',-1),('right',1)]:
            joints[side+'_'+part]=dict(final=dict(x=centre[0]+sign*width/2,y=centre[1]),
                status='observed',visibility='unknown',flags=[])
    return dict(frame_index=0,timestamp_seconds=time,track_state=state,joints=joints)


@pytest.mark.parametrize('angle',[0,45,90,180,270,359])
def test_image_plane_angle_matches_detector_torso_axis(angle):
    result=orientation_samples(dict(frames=[frame(angle)]))
    assert result['samples'][0][2]==pytest.approx(angle)
    assert result['samples'][0][3:5]==pytest.approx([1,1])


@pytest.mark.parametrize('failure',['missing','uncertain','crop_edge','collapsed'])
def test_unusable_orientation_does_not_invent_a_heading(failure):
    f=frame(45)
    if failure=='missing':
        f['joints']['left_hip'].update(status='missing',final=dict(x=None,y=None))
    elif failure=='uncertain':f['track_state']='uncertain'
    elif failure=='crop_edge':f['joints']['right_shoulder']['flags']=['near_crop_edge']
    else:
        for side in ('left','right'):
            f['joints'][side+'_shoulder']['final']=dict(f['joints'][side+'_hip']['final'])
    result=orientation_samples(dict(frames=[f]))
    assert result['samples'][0][2] is None


def test_orientation_preserves_irregular_source_timestamps():
    frames=[frame(a,t) for a,t in [(0,0),(90,.04),(180,.17)]]
    for i,f in enumerate(frames):f['frame_index']=i
    result=orientation_samples(dict(frames=frames))
    assert [r[:3] for r in result['samples']]==[[0,0,0],[1,.04,90],[2,.17,180]]
