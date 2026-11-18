import numpy as np
import pytest

from trampoline_pose.backend import OpenMMLabBackend,rotation_to_source
from trampoline_pose.geometry import crop_geometry,apply_affine
from trampoline_pose.types import TrackerConfig


@pytest.mark.parametrize('rotation',[90,180,270])
def test_rotation_maps_pixel_centres_to_original(rotation):
    original=np.arange(7*11).reshape(7,11)
    rotated=np.rot90(original,rotation//90)
    y,x=np.indices(rotated.shape)
    mapped=apply_affine(np.column_stack([x.ravel(),y.ravel()]),rotation_to_source(rotation,11,7)).astype(int)
    np.testing.assert_array_equal(original[mapped[:,1],mapped[:,0]],rotated.ravel())


def test_retry_recovers_coherent_pose_and_composes_crop_transform():
    backend=object.__new__(OpenMMLabBackend)
    backend.config=TrackerConfig()
    image=np.zeros((100,160,3),np.uint8)
    box=[40,20,80,90]
    calls=[]
    def estimate(im,b):
        calls.append(im.shape)
        points=np.tile([55.,45.],(17,1))
        scores=np.full(17,.8)
        if len(calls)==1:
            scores[11]=.1
        elif len(calls)==2:
            points[:]=[104.,54.]
            scores[:]=.9
        else:
            scores[:]=.1
        return points,scores,crop_geometry(b)
    backend._estimate_single=estimate
    points,scores,crop=backend.estimate(image,box)
    np.testing.assert_allclose(points,np.tile([55,45],(17,1)))
    assert crop['pose_rotation_degrees']==180
    assert np.all(scores==.9)
    identity=np.vstack([crop['source_to_input_affine'],[0,0,1]]) @ np.vstack([crop['input_to_source_affine'],[0,0,1]])
    np.testing.assert_allclose(identity,np.eye(3),atol=1e-12)


def test_complete_pose_needs_no_rotation_retry():
    backend=object.__new__(OpenMMLabBackend)
    backend.config=TrackerConfig()
    calls=[]
    def estimate(im,box):
        calls.append(1)
        return np.full((17,2),50.),np.ones(17),crop_geometry(box)
    backend._estimate_single=estimate
    backend.estimate(np.zeros((100,160,3),np.uint8),[30,20,90,90])
    assert len(calls)==1


def test_high_score_crop_edge_points_still_trigger_retry():
    backend=object.__new__(OpenMMLabBackend)
    backend.config=TrackerConfig()
    calls=[]
    def estimate(im,box):
        calls.append(1)
        crop=crop_geometry(box)
        if len(calls)==1:
            crop['padded_bbox_xyxy']=[50,0,100,100]
        return np.full((17,2),50.),np.ones(17),crop
    backend._estimate_single=estimate
    backend.estimate(np.zeros((100,160,3),np.uint8),[30,20,90,90])
    assert len(calls)==4


def test_missing_limb_cannot_replace_strong_torso_with_false_width_dip():
    backend=object.__new__(OpenMMLabBackend)
    backend.config=TrackerConfig()
    calls=[]
    points=np.full((17,2),50.)
    points[5]=[40,35];points[6]=[70,35]
    points[11]=[43,65];points[12]=[67,65]
    scores=np.full(17,.85);scores[9]=.1
    def estimate(im,box):
        calls.append(1)
        if len(calls)>1:
            collapsed=points.copy()
            # A rotated alternative looks confident but collapses both widths.
            collapsed[[5,6,11,12]]=[109,49]
            return collapsed,np.ones(17),crop_geometry(box)
        return points,scores,crop_geometry(box)
    backend._estimate_single=estimate
    result=backend.estimate(np.zeros((100,160,3),np.uint8),[30,20,90,90])
    assert np.linalg.norm(result[0][5]-result[0][6])==30
