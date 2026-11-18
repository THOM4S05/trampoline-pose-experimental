import copy
import hashlib
import cv2
import numpy as np
import pytest

from trampoline_pose.bed_contact import deformation_onset, add_bed_contact_times, measure_bed,bed_region,discover_contacts


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
    add_bed_contact_times(data,result,source,tmp_path/'bed.json',profile='video_recovery')
    assert result['skills'][0]['landing_contact']['frame_index'] == 240
    assert result['skills'][0]['time_of_flight_seconds'] is None
    assert result['skills'][1]['time_of_flight_seconds'] == 1.1
    assert result['skills'][1]['time_of_flight']['interval_seconds'] == [1.08,1.12]
    # Cache remains usable without decoding again, but mismatched sources fail.
    monkeypatch.setattr('trampoline_pose.bed_contact.measure_bed', lambda *args:pytest.fail('cache not used'))
    add_bed_contact_times(data,result,source,tmp_path/'bed.json',profile='video_recovery')
    source.write_bytes(b'changed')
    with pytest.raises(ValueError,match='does not match'):
        add_bed_contact_times(data,result,source,tmp_path/'bed.json',profile='video_recovery')


def test_fast_descending_ankles_do_not_place_bed_band_above_mesh():
    frames=[]
    for i,t in enumerate(np.arange(0,2,.025)):
        ankle_y=110 if .89<=t<=1.01 else 200
        joints={}
        for side,x in [('left',195),('right',205)]:
            for part,y in [('ankle',ankle_y),('hip',150),('shoulder',100)]:
                joints[side+'_'+part]=dict(final=dict(x=x,y=y),status='observed',flags=[])
        frames.append(dict(frame_index=i,timestamp_seconds=float(t),track_state='tracked',joints=joints))
    region=bed_region(dict(frames=frames,source=dict(display_width=400,display_height=300)),[dict(timestamp_seconds=1.)])
    assert region['method']=='lower_ankle_envelope_checked_by_video'
    assert region['roi'][1]<=200<=region['roi'][3]
    assert region['roi'][1]>150


@pytest.mark.parametrize('failure',[None,'one_side_only','camera_drift'])
def test_video_scan_discovers_contacts_without_pose_proposals(failure):
    t=np.arange(0,4,1/60)
    signal=np.full_like(t,5.)
    for start in (1.,3.):
        selected=(t>start)&(t<start+.4)
        signal[selected]+=45*np.sin(np.pi*(t[selected]-start)/.4)**2
    left,right=signal.copy(),signal.copy()
    if failure=='one_side_only':right[:]=5
    if failure=='camera_drift':left=right=5+2*t
    rows=[[float(stamp),float(a),float(b)] for stamp,a,b in zip(t,left,right)]
    frames=[]
    for i,stamp in enumerate(t):
        joints={side+'_'+part:dict(final=dict(x=x,y=y),status='observed',flags=[])
                for side,x in [('left',195),('right',205)] for part,y in [('shoulder',100),('hip',150)]}
        frames.append(dict(frame_index=i,timestamp_seconds=float(stamp),track_state='tracked',joints=joints))
    result=discover_contacts(rows,dict(frames=frames),dict(roi=[0,175,400,250],torso=50))
    landings=[e['landing'] for e in result if e['landing']]
    if failure:assert not landings
    else:
        assert len(landings)==2
        assert [e['timestamp_seconds'] for e in landings]==pytest.approx([1,3],abs=.035)
        assert all(e['supported_sides']==2 for e in landings)


def test_video_discovered_contact_rebuilds_spans_and_preserves_facing_override(tmp_path,monkeypatch):
    source=tmp_path/'source.mp4';source.write_bytes(b'fixture')
    data=dict(source=dict(sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    landing=dict(timestamp_seconds=2.5,frame_index=150,interval_seconds=[2.47,2.53])
    release=dict(timestamp_seconds=2.8,frame_index=168,interval_seconds=[2.77,2.83])
    measurement=dict(status='measured',events=[dict(proxy_seconds=1.,landing=None,release=None),dict(proxy_seconds=4.,landing=None,release=None)],
        discovered_contacts=[dict(proxy_seconds=2.5,landing=landing,release=release)])
    monkeypatch.setattr('trampoline_pose.bed_contact.measure_bed',lambda *args:copy.deepcopy(measurement))
    def rebuild(d,settings,facing_override,additional_contacts):
        assert d is data and facing_override=='right'
        assert additional_contacts[0]['timestamp_seconds']==2.5
        return dict(contacts=[dict(timestamp_seconds=1.),*additional_contacts,dict(timestamp_seconds=4.)],
            skills=[dict(start_seconds=1.,end_seconds=2.5),dict(start_seconds=2.5,end_seconds=4.)])
    monkeypatch.setattr('trampoline_pose.skill_identification.analyze',rebuild)
    result=dict(settings={},facing=dict(method='user_override',screen_direction='right'),
        contacts=[dict(timestamp_seconds=1.),dict(timestamp_seconds=4.)],skills=[dict(start_seconds=1.,end_seconds=4.)])
    add_bed_contact_times(data,result,source,profile='video_recovery')
    assert len(result['skills'])==2
    assert result['skills'][0]['landing_contact']==landing
    assert result['bed_timing']['additional_video_contacts']==1


def test_stopping_contact_retains_wide_uncertainty_without_relaxing_camera_drift_check():
    import json
    from pathlib import Path
    fixture=json.loads((Path(__file__).parent/'fixtures/stopping-bed-signal.json').read_text())
    values=np.array(fixture['samples']);proxy=fixture['proxy_seconds']
    options=[]
    for column in (1,2):
        found=[deformation_onset(values[:,0],values[:,column],proxy+offset,max_uncertainty_seconds=.20)
               for offset in (0.,-.1,-.15)]
        options.append([r for r in found if r])
    pairs=[(a,b) for a in options[0] for b in options[1] if abs(a['timestamp_seconds']-b['timestamp_seconds'])<=.035]
    assert pairs
    assert any(max(r['interval_seconds'][1] for r in pair)-min(r['interval_seconds'][0] for r in pair)>.10 for pair in pairs)
    t=np.arange(0,2,1/30)
    assert deformation_onset(t,5+10*t,1.05,max_uncertainty_seconds=.20) is None


def test_recovery_bounce_fix_is_opt_in_not_the_default(monkeypatch):
    def standard(data,result,source,cache):
        result['bed_timing']={'version':3}
    monkeypatch.setattr('trampoline_pose.bed_contact_standard.add_bed_contact_times',standard)
    monkeypatch.setattr('trampoline_pose.bed_contact._add_recovery_bed_contact_times',
                        lambda *args:pytest.fail('Instagram recovery ran without an opt-in'))
    result={}
    add_bed_contact_times({},result,'unused')
    assert result['bed_timing']=={'version':3,'profile':'standard'}
