import math

import numpy as np
import pytest

from trampoline_pose.twist_width import WidthSettings, attach, decode, measure


def test_ewan_observed_widths_resolve_five_half_turns_with_review_gaps():
    import json
    from pathlib import Path
    fixture=json.loads((Path(__file__).parent/'fixtures/ewan_width_gaps.json').read_text())
    result=decode(fixture['rows'],fixture['refs'],fixture['skill'])
    assert result['candidate_count']==2.5
    assert result['completed_passages']==5
    assert result['count'] is None
    assert result['status']=='tentative'
    assert result['review_reasons']==['short_bounded_torso_gaps']


def brief_narrow_rows():
    return [dict(frame_index=i, timestamp_seconds=t, shoulder_fraction=w, hip_fraction=w)
            for i, (t, w) in enumerate([(0, .1), (.04, .1), (.10, .9), (.14, .9),
                 (.20, .1), (.208, .1), (.216, .1), (.224, .1),
                 (.25, .9), (.29, .9), (.36, .1), (.40, .1)])]


def residual_finish_rows():
    return [dict(frame_index=i, timestamp_seconds=t, shoulder_fraction=s, hip_fraction=h)
            for i, (t, s, h) in enumerate([(0, .1, .1), (.04, .1, .1),
                (.10, 1., 1.), (.14, 1., 1.), (.20, .6, .6),
                (.25, .42, .46), (.28, .3, .39)])]


def test_paired_narrowing_at_bed_touch_completes_residual_width_finish():
    span = dict(visible_start_seconds=0, visible_end_seconds=.3,
                landing_contact=dict(timestamp_seconds=.28))
    result = decode(residual_finish_rows(), dict(shoulder=50, hip=35), span)
    assert result['candidate_count'] == .5
    assert result['count'] is None
    assert result['finish_evidence']['method'] == 'paired_narrowing_at_bed_touch'
    assert result['events'][0]['completion_method'] == 'paired_narrowing_at_bed_touch'


@pytest.mark.parametrize('failure', ['no_touch', 'single_frame', 'hips_stay_broad', 'small_drop', 'missing'])
def test_residual_finish_requires_paired_sustained_large_drop_and_touch(failure):
    rows = residual_finish_rows()
    span = dict(visible_start_seconds=0, visible_end_seconds=.28,
                landing_contact=dict(timestamp_seconds=.28))
    if failure == 'no_touch':
        span.pop('landing_contact')
    elif failure == 'single_frame':
        rows[-2]['shoulder_fraction'] = .7
    elif failure == 'hips_stay_broad':
        for r in rows[-2:]:
            r['hip_fraction'] = .7
    elif failure == 'small_drop':
        for r in rows[2:4]:
            r['shoulder_fraction'] = r['hip_fraction'] = .7
    else:
        rows[-2]['hip_fraction'] = None
    result = decode(rows, dict(shoulder=50, hip=35), span)
    assert result['candidate_count'] is None
    assert result['finish_evidence'] is None


def test_sustained_paired_internal_dip_splits_without_using_finish_rule():
    rows = residual_finish_rows()
    rows.extend([dict(frame_index=7, timestamp_seconds=.34, shoulder_fraction=1., hip_fraction=1.),
                 dict(frame_index=8, timestamp_seconds=.38, shoulder_fraction=1., hip_fraction=1.),
                 dict(frame_index=9, timestamp_seconds=.44, shoulder_fraction=.1, hip_fraction=.1),
                 dict(frame_index=10, timestamp_seconds=.48, shoulder_fraction=.1, hip_fraction=.1)])
    result = decode(rows, dict(shoulder=50, hip=35), dict(visible_start_seconds=0,visible_end_seconds=.48,
                    landing_contact=dict(timestamp_seconds=.48)))
    assert result['candidate_count'] == 1.0
    assert result['finish_evidence'] is None
    assert all(e['completion_method']=='sustained_paired_relative_narrowing' for e in result['events'])


def test_brief_missing_observation_does_not_merge_observed_half_turns():
    rows = residual_finish_rows()
    rows.insert(3, dict(frame_index=100, timestamp_seconds=.12,
                       shoulder_fraction=None, hip_fraction=None))
    for i, row in enumerate(rows):
        row['frame_index'] = i
    rows.extend([dict(frame_index=8, timestamp_seconds=.34, shoulder_fraction=1., hip_fraction=1.),
                 dict(frame_index=9, timestamp_seconds=.38, shoulder_fraction=1., hip_fraction=1.),
                 dict(frame_index=10, timestamp_seconds=.44, shoulder_fraction=.1, hip_fraction=.1),
                 dict(frame_index=11, timestamp_seconds=.48, shoulder_fraction=.1, hip_fraction=.1)])
    result = decode(rows, dict(shoulder=50, hip=35),
                    dict(visible_start_seconds=0, visible_end_seconds=.48))
    assert result['candidate_count'] == 1.
    assert result['status'] == 'tentative'
    assert result['count'] is None
    assert result['review_reasons'] == ['short_bounded_torso_gaps']
    assert result['raw_evidence'][3]['shoulder_fraction'] is None
    # An outage hiding the narrowing must still invalidate a total.
    for row in rows:
        if .14 <= row['timestamp_seconds'] <= .34:
            row['shoulder_fraction'] = row['hip_fraction'] = None
    result = decode(rows, dict(shoulder=50, hip=35),
                    dict(visible_start_seconds=0, visible_end_seconds=.48))
    assert result['candidate_count'] is None
    assert 'unsupported_torso_gap' in result['reasons']


def test_24ms_middle_narrow_phase_separates_two_passages():
    span = dict(visible_start_seconds=0, visible_end_seconds=.4)
    refs = dict(shoulder=50, hip=35)
    assert decode(brief_narrow_rows(), refs, span, WidthSettings(stable_seconds=.03))['candidate_count'] == .5
    assert decode(brief_narrow_rows(), refs, span)['candidate_count'] == 1


def test_bed_touch_excludes_later_rotation():
    span = dict(visible_start_seconds=0, visible_end_seconds=.4,
                landing_contact=dict(timestamp_seconds=.224, status='video_estimate_needs_review'))
    result = decode(brief_narrow_rows(), dict(shoulder=50, hip=35), span)
    assert result['candidate_count'] == .5
    assert result['end_seconds'] == .224
    assert result['end_boundary_method'] == 'estimated_bed_touch'
    assert all(r['timestamp_seconds'] <= .224 for r in result['raw_evidence'])


def test_one_frame_narrow_spike_cannot_split_passages():
    rows = [r for r in brief_narrow_rows() if not .20 < r['timestamp_seconds'] <= .224]
    result = decode(rows, dict(shoulder=50, hip=35), dict(visible_start_seconds=0, visible_end_seconds=.4))
    assert result['candidate_count'] == .5


def sequence(turns=.5, rate=120, image_rotation=False, hip_turns=None):
    frames = []
    for i, t in enumerate(np.linspace(0, 2, 2 * rate + 1)):
        angle = math.pi * t if image_rotation else 0
        transform = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
        joints = {}
        for part, factor, centre in [('shoulder', 50, np.array([0, -100])), ('hip', 35, np.array([0, 0]))]:
            rotation = hip_turns if part == 'hip' and hip_turns is not None else turns
            width = 3 + factor * abs(math.sin(2 * math.pi * rotation * t / 2))
            for side, sign in [('left', -1), ('right', 1)]:
                point = transform @ (centre + [sign * width / 2, 0]) + 200
                joints[side + '_' + part] = dict(final=dict(x=float(point[0]), y=float(point[1])),
                    status='observed', visibility='unknown', flags=[])
        frames.append(dict(frame_index=i, timestamp_seconds=float(t), track_state='tracked', joints=joints))
    return dict(frames=frames)


def flight(**changes):
    return dict(visible_start_seconds=0, visible_end_seconds=2, start_clipped=False, end_clipped=False, **changes)


@pytest.mark.parametrize('turns', [.5, 1, 1.5, 2.5])
@pytest.mark.parametrize('rate', [30, 60, 120])
def test_known_passages_at_different_rates(turns, rate):
    rows, refs = measure(sequence(turns, rate))
    result = decode(rows, refs, flight())
    assert result['candidate_count'] == turns
    assert result['count'] is None
    assert result['status'] == 'tentative'


def test_no_twist_during_image_plane_somersault():
    data = sequence(0, image_rotation=True)
    reference = sequence(.5)['frames']
    for f in reference:
        f['timestamp_seconds'] += 3
        f['frame_index'] += 400
    data['frames'].extend(reference)
    rows, refs = measure(data)
    result = decode(rows, refs, flight())
    assert result['candidate_count'] == 0
    assert max(abs(r['shoulder_width_px'] - 3) for r in rows if r['timestamp_seconds'] <= 2) < 1e-10


def test_shoulder_motion_without_matching_hips_abstains():
    rows, refs = measure(sequence(1, hip_turns=0))
    result = decode(rows, dict(shoulder=refs['shoulder'], hip=38), flight())
    assert result['candidate_count'] is None
    assert 'shoulder_hip_disagreement' in result['reasons']


def test_tracking_loss_and_missing_joints_abstain():
    data = sequence()
    data['frames'][100]['track_state'] = 'lost'
    rows, refs = measure(data)
    assert decode(rows, refs, flight())['candidate_count'] is None
    data = sequence()
    data['frames'] = data['frames'][:95] + data['frames'][125:]
    rows, refs = measure(data)
    result = decode(rows, refs, flight())
    assert 'unsupported_torso_gap' in result['reasons']
    assert result['candidate_count'] is None


def test_clipped_and_unfinished_flights_abstain():
    rows, refs = measure(sequence())
    span = flight()
    span['start_clipped'] = True
    assert decode(rows, refs, span)['candidate_count'] is None
    span = flight()
    span['visible_end_seconds'] = 1.1
    result = decode(rows, refs, span)
    assert result['candidate_count'] is None
    assert 'incomplete_passage' in result['reasons']


def test_side_swaps_do_not_change_width():
    data = sequence(1)
    original, _ = measure(data)
    for f in data['frames'][60:90]:
        for part in ('shoulder', 'hip'):
            js = f['joints']
            a, b = 'left_' + part, 'right_' + part
            js[a], js[b] = js[b], js[a]
    swapped, _ = measure(data)
    assert original == swapped


def test_unknown_when_recording_has_no_usable_breadth_reference():
    rows, refs = measure(sequence(0))
    assert decode(rows, refs, flight())['candidate_count'] is None


def test_reversal_is_explicitly_not_resolved():
    # Width from a half turn and a quarter turn followed by reversal can match.
    rows, refs = measure(sequence(.5))
    result = decode(rows, refs, flight())
    assert result['candidate_count'] == .5
    assert result['count'] is None
    assert 'continued_twisting_without_reversal' in result['assumptions']


@pytest.mark.parametrize('failure',[None,'one_frame','shoulder_only','hip_only','small_drop'])
def test_relative_valley_requires_sustained_bilateral_excursion(failure):
    widths=[(.1,.1)]*3+[(1.,1.)]*3+[(.5,.5)]*3+[(1.,1.)]*3+[(.1,.1)]*3
    if failure=='one_frame':
        widths[6]=widths[8]=(1.,1.)
    elif failure=='shoulder_only':
        widths[6:9]=[(.5,1.)]*3
    elif failure=='hip_only':
        widths[6:9]=[(1.,.5)]*3
    elif failure=='small_drop':
        widths[6:9]=[(.85,.85)]*3
    rows=[dict(frame_index=i,timestamp_seconds=i*.02,shoulder_fraction=s,hip_fraction=h)
          for i,(s,h) in enumerate(widths)]
    result=decode(rows,dict(shoulder=50,hip=35),dict(visible_start_seconds=0,visible_end_seconds=.28))
    assert result['candidate_count']==(1.0 if failure is None else .5)


def test_img3386_recovered_width_signal_has_five_supported_passages():
    import json
    from pathlib import Path
    fixture=json.loads((Path(__file__).parent/'fixtures/img3386-widths.json').read_text())
    result=decode(fixture['rows'],fixture['references_px'],fixture['flight'])
    assert result['candidate_count']==2.5
    assert result['completed_passages']==5
    assert result['count'] is None
    assert result['status']=='tentative'
    assert result['reasons']==[]


def test_rare_twist_in_long_side_on_routine_keeps_broad_reference():
    import copy
    data=sequence(.5,rate=30)
    for i in range(1200):
        row=copy.deepcopy(data['frames'][0])
        row.update(frame_index=len(data['frames']),timestamp_seconds=2+(i+1)/30)
        data['frames'].append(row)
    rows,refs=measure(data)
    assert refs['shoulder']>40
    assert refs['hip']>25
    assert decode(rows,refs,flight())['candidate_count']==.5


def test_isolated_width_outlier_cannot_establish_broad_reference():
    data=sequence(0,rate=120)
    for part in ('shoulder','hip'):
        data['frames'][120]['joints']['left_'+part]['final']['x']-=100
        data['frames'][120]['joints']['right_'+part]['final']['x']+=100
    rows,refs=measure(data)
    assert refs['shoulder']==pytest.approx(3)
    assert refs['hip']==pytest.approx(3)
    assert decode(rows,refs,flight())['candidate_count'] is None


def test_img2926_flight5_is_detected_from_widths_without_reference_label():
    import json
    from pathlib import Path
    fixture=json.loads((Path(__file__).parent/'fixtures/img2926-widths.json').read_text())
    data=dict(frames=[])
    for i,(t,s,h) in enumerate(fixture['width_samples']):
        joints={}
        for part,width in [('shoulder',s),('hip',h)]:
            for side,sign in [('left',-1),('right',1)]:
                joints[side+'_'+part]=dict(status='missing' if width is None else 'observed',
                    final=dict(x=None if width is None else 200+sign*width/2,y=200),flags=[])
        data['frames'].append(dict(frame_index=i,timestamp_seconds=t,track_state='tracked',joints=joints))
    rows,refs=measure(data)
    result=decode(rows,refs,fixture['flight'])
    assert result['candidate_count']==.5
    assert result['completed_passages']==1
    assert result['status']=='tentative'
    assert result['reasons']==[]


@pytest.mark.parametrize('turns,label',[(.5,'Half twist jump'),(1.,'Full twist jump')])
def test_jump_candidate_is_explicit_without_promoting_supported_identity(turns,label):
    skill=flight()
    skill.update(rotation=dict(somersault_count=0),takeoff_position='feet',landing_position='feet',
                 predicted_skill_identity='unknown',supplied_skill_identity='Unrelated reference')
    result=attach(sequence(turns),dict(skills=[skill]))['skills'][0]
    assert result['twist']['candidate_skill_identity']==label
    assert result['twist']['count'] is None
    assert result['predicted_skill_identity']=='unknown'


@pytest.mark.parametrize('failure',[None,'short_gap','long_gap','low_coverage','broad_spike','partial','short_flight'])
def test_zero_twist_requires_positive_sustained_evidence(failure):
    data=sequence(0)
    reference=sequence(.5)['frames']
    for f in reference:
        f['timestamp_seconds']+=3
        f['frame_index']+=400
    data['frames'].extend(reference)
    if failure in ('short_gap','long_gap','low_coverage'):
        length={'short_gap':3,'long_gap':10,'low_coverage':40}[failure]
        for row in data['frames'][100:100+length]:
            row['track_state']='lost'
    if failure=='broad_spike':
        for row in data['frames'][100:109]:
            row['joints']['left_shoulder']['final']['x']-=30
    rows,refs=measure(data)
    span=flight()
    if failure=='partial':span['start_clipped']=True
    if failure=='short_flight':span['visible_end_seconds']=.2
    result=decode(rows,refs,span)
    if failure in (None,'short_gap'):
        assert result['count']==0
        assert result['status']=='supported_conditional'
        assert result['zero_twist_evidence']['supported']
        assert result['reasons']==[]
    else:
        assert result['count'] is None
        assert not result['zero_twist_evidence']['supported']
