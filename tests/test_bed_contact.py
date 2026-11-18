import copy
import hashlib
import cv2
import numpy as np
import pytest

from trampoline_pose.bed_contact import deformation_onset, add_bed_contact_times, measure_bed


@pytest.mark.parametrize('rate', [30, 60, 240])
def test_detects_first_deformation_not_peak_compression(rate):
    t = np.arange(0, 2, 1/rate)
    t[1:-1] += np.sin(np.arange(1, len(t)-1)) * .08/rate
    signal = 4 + .5*t + 900*np.maximum(0, t-1)**2
    result = deformation_onset(t, signal, 1.05)
    assert result is not None
    assert result['timestamp_seconds'] == pytest.approx(1, abs=1/rate)
    assert result['interval_seconds'][0] <= 1 <= result['interval_seconds'][1]


def test_no_detection_for_static_bed_camera_drift_or_missing_impact_frames():
    t = np.arange(0, 2, .005)
    assert deformation_onset(t, np.full_like(t, 5), 1.05) is None
    assert deformation_onset(t, 5+10*t, 1.05) is None
    signal = 4+900*np.maximum(0,t-1)**2
    signal[(t>.94)&(t<1.09)] = np.nan
    assert deformation_onset(t, signal, 1.05) is None


def test_video_detector_registers_camera_motion_and_measures_the_bed(monkeypatch):
    rng = np.random.default_rng(6)
    background = rng.integers(30, 140, size=(300,400), dtype=np.uint8)
    background = cv2.GaussianBlur(background, (3,3), 0)
    times = np.arange(0, 2.1, 1/60)
    frames, images = [], []
    for i, stamp in enumerate(times):
        joints = {}
        for side, x in (('left',195), ('right',205)):
            for part, y in (('ankle',200), ('knee',175), ('hip',150), ('shoulder',100)):
                joints[side+'_'+part] = dict(final=dict(x=x,y=y),status='observed',visibility='unknown',flags=[])
        frames.append(dict(frame_index=i,timestamp_seconds=float(stamp),track_state='tracked',joints=joints))
        image = background.copy()
        if 1 < stamp < 1.4:
            deformation = round(45*np.sin(np.pi*(stamp-1)/.4)**2)
            image[175:225] += deformation
        # A moving person in the excluded middle cannot trigger the bed strips.
        image[140:230,175:225] = 100 + round(40*np.sin(stamp*15))
        image = cv2.warpAffine(image,np.float32([[1,0,.8*np.sin(stamp*4)],[0,1,.8*np.cos(stamp*3)]]),(400,300))
        images.append(cv2.cvtColor(image,cv2.COLOR_GRAY2BGR))
    data = dict(frames=frames,source=dict(display_width=400,display_height=300))
    def decode(*args):
        for frame, image in zip(frames,images):
            yield frame, image
    monkeypatch.setattr('trampoline_pose.bed_contact.decode',decode)
    measured = measure_bed(data,{'contacts':[{'timestamp_seconds':1.05}]},'synthetic')
    landing = measured['events'][0]['landing']
    assert landing is not None
    assert landing['timestamp_seconds'] == pytest.approx(1,abs=.035)
    assert landing['supported_sides'] == 2


def test_video_evidence_replaces_wrong_pose_timing_and_preserves_landing_on_partial_skill(tmp_path, monkeypatch):
    source = tmp_path/'source.mp4'
    source.write_bytes(b'video fixture')
    data = {'source':{'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}}
    contact = {'timestamp_seconds':1.0, 'frame_index':240, 'interval_seconds':[.99,1.01]}
    release = {'timestamp_seconds':1.4, 'frame_index':336, 'interval_seconds':[1.39,1.41]}
    later = {'timestamp_seconds':2.5, 'frame_index':600, 'interval_seconds':[2.49,2.51]}
    measurement = {'status':'measured','events':[
        {'proxy_seconds':1.06,'landing':contact,'release':release},
        {'proxy_seconds':2.57,'landing':later,'release':None}]}
    monkeypatch.setattr('trampoline_pose.bed_contact.measure_bed', lambda *args:copy.deepcopy(measurement))
    result = {'contacts':[{'timestamp_seconds':1.06},{'timestamp_seconds':2.57}], 'skills':[
        {'start_seconds':None,'end_seconds':1.06,'start_clipped':True,'time_of_flight_seconds':99},
        {'start_seconds':1.06,'end_seconds':2.57,'time_of_flight_seconds':99}]}
    add_bed_contact_times(data,result,source,tmp_path/'bed.json')
    assert result['skills'][0]['landing_contact']['frame_index'] == 240
    assert result['skills'][0]['time_of_flight_seconds'] is None
    assert result['skills'][1]['time_of_flight_seconds'] == 1.1
    assert result['skills'][1]['time_of_flight']['interval_seconds'] == [1.08,1.12]
    # Cache remains usable without decoding again, but mismatched sources fail.
    monkeypatch.setattr('trampoline_pose.bed_contact.measure_bed', lambda *args:pytest.fail('cache not used'))
    add_bed_contact_times(data,result,source,tmp_path/'bed.json')
    source.write_bytes(b'changed')
    with pytest.raises(ValueError,match='does not match'):
        add_bed_contact_times(data,result,source,tmp_path/'bed.json')
