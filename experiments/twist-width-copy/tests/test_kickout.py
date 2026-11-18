import math

import pytest

from trampoline_pose.kickout import observations, opening_analysis
from trampoline_pose.orientation import torso_degrees


def skill(turns=0, landing='feet', duration=1.2, position='tuck'):
    return dict(visible_start_seconds=0, visible_end_seconds=duration, landing_position=landing,
                rotation=dict(somersault_count=abs(turns), projected_turns=turns),
                execution=dict(body_position=position))


def native_rows(segments, turns=0, duration=1.2, step=.02, initial=0):
    rows = []
    for index in range(1, round(duration / step)):
        time = round(index * step, 6)
        lhip, rhip, knee = next(angles for end, angles in segments if time <= end)
        sides = {}
        for side, hip in [('left', lhip), ('right', rhip)]:
            sides[side] = {part: dict(raw_degrees=angle, observed_degrees=angle, filtered_degrees=angle)
                           for part, angle in [('hip', hip), ('knee', knee)]}
        rows.append(dict(frame_index=index, timestamp_seconds=time, source_pts=index*193,
                         source_time_base='1/90000',
                         torso_degrees=(initial + 360*turns*time/duration) % 360, **sides))
    return rows


TUCK = (92, 94, 82)
PIKE = (108, 110, 176)
OPEN = (175, 177, 179)


def episodes(result):
    return [episode['frame']['timestamp_seconds'] for episode in result['episodes']]


@pytest.mark.parametrize('turns', [2, -2])
def test_retain_both_openings_after_sustained_retuck(turns):
    rows = native_rows([(.30, TUCK), (.44, OPEN), (.79, TUCK), (1.2, OPEN)], turns)
    result = opening_analysis(skill(turns), rows)
    assert result['status'] == 'confirmed'
    assert episodes(result) == [.32, .80]
    assert result['selected']['frame_index'] == 40
    assert result['selected']['source_pts'] == 40 * 193


def test_landing_pike_down_and_reextension_do_not_replace_kickout():
    rows = native_rows([(.63, PIKE), (.91, OPEN), (1.09, PIKE), (1.2, OPEN)], 1)
    result = opening_analysis(skill(1, position='pike'), rows)
    assert result['status'] == 'confirmed'
    assert episodes(result) == [.64]
    assert result['post_opening_flexion'][0]['kind'] == 'pike_down'
    assert result['selected']['timestamp_seconds'] == .64


def test_pike_down_early_in_final_judging_arc_still_preserves_opening():
    rows = native_rows([(.43, PIKE), (.60, OPEN), (.78, PIKE), (1.2, OPEN)], 1)
    result = opening_analysis(skill(1, position='pike'), rows)
    assert episodes(result) == [.44]
    assert result['post_opening_flexion'][0]['before_fig_three'] is True


def test_distinct_pike_retained_when_substantial_rotation_remains():
    rows = native_rows([(.28, PIKE), (.41, OPEN), (.71, PIKE), (1.2, OPEN)], 2)
    assert episodes(opening_analysis(skill(2, position='pike'), rows)) == [.30, .72]


def test_early_fractional_kickout_is_eligible():
    rows = native_rows([(.35, TUCK), (1.2, OPEN)], 1.75)
    result = opening_analysis(skill(1.75, 'front'), rows)
    assert result['status'] == 'confirmed'
    assert episodes(result) == [.36]
    assert result['fig']['opening_deduction'] == 0


def test_opening_after_detected_bed_contact_is_excluded():
    rows = native_rows([(.50, TUCK), (.90, (151, 153, 178)), (1.2, OPEN)])
    flight = skill()
    flight['time_of_flight'] = dict(takeoff_seconds=.10, landing_seconds=.90)
    result = opening_analysis(flight, rows)
    assert result['status'] == 'incomplete'
    assert not result['episodes']
    assert result['selected']['timestamp_seconds'] < .90


@pytest.mark.parametrize('landing, turns, initial, first, expected', [
    ('feet', 1, 0, .60, .0), ('feet', 1, 0, .72, .1),
    ('feet', -1, 0, .82, .2), ('feet', 1, 0, .92, .3),
    ('front', 1.75, 0, 1.10, .1), ('back', 1.25, 0, 1.06, .1),
])
def test_fig_clock_uses_rotation_direction_and_landing(landing, turns, initial, first, expected):
    rows = native_rows([(round(first - .01, 2), TUCK), (1.2, OPEN)], turns, initial=initial)
    result = opening_analysis(skill(turns, landing), rows)
    assert result['selected']['timestamp_seconds'] == first
    assert result['fig']['opening_deduction'] == expected


@pytest.mark.parametrize('position, folded', [('tuck', TUCK), ('pike', PIKE)])
def test_upright_jumps_receive_opening_without_deduction(position, folded):
    result = opening_analysis(skill(position=position), native_rows([(.50, folded), (1.2, OPEN)], step=.04))
    assert result['status'] == 'confirmed'
    assert result['selected']['timestamp_seconds'] == .52
    assert result['fig']['status'] == 'not_applicable'


def test_straight_skill_is_not_applicable():
    assert opening_analysis(skill(position='straight'), native_rows([(1.2, OPEN)]))['status'] == 'not_applicable'


def test_reliable_asymmetric_extension_is_incomplete_and_keeps_maximum():
    rows = native_rows([(.4, TUCK), (.75, (178, 162, 172)), (.96, (176, 158, 174)), (1.2, TUCK)], 1)
    result = opening_analysis(skill(1), rows)
    assert result['status'] == 'incomplete'
    assert result['selected']['timestamp_seconds'] == .42
    assert result['fig']['opening_deduction'] == .3


def test_occlusion_and_isolated_threshold_crossing_are_not_incomplete():
    missing = native_rows([(.4, TUCK), (.96, (177, None, 179)), (1.2, (176, 169, 179))])
    assert opening_analysis(skill(), missing)['status'] == 'needs_review'
    fleeting = native_rows([(.4, TUCK), (.42, OPEN), (1.2, (167, 166, 179))])
    assert opening_analysis(skill(), fleeting)['reasons'] == ['opening_not_sustained']


def test_hidden_crossing_retains_supported_episode_and_uncertainty_interval():
    rows = native_rows([(.4, TUCK), (.48, (None, None, None)), (1.2, OPEN)])
    result = opening_analysis(skill(), rows)
    assert result['status'] == 'needs_review'
    assert episodes(result) == [.50]
    assert result['episodes'][0]['crossing_interval_seconds'] == [.4, .50]


def test_projection_limited_extension_is_reviewable_even_with_large_apparent_angles():
    rows = native_rows([(.4, TUCK), (1.2, OPEN)])
    for row in rows:
        if row['timestamp_seconds'] > .4:
            row['possible_frontal_projection'] = True
    result = opening_analysis(skill(), rows)
    assert result['status'] == 'needs_review'
    assert not result['episodes']


def test_earliest_native_sample_retained_when_filter_boundary_lags():
    rows = native_rows([(.44, TUCK), (1.2, OPEN)], step=.01)
    for side in ('left', 'right'):
        rows[44][side]['hip']['filtered_degrees'] = 169
    result = opening_analysis(skill(), rows)
    assert result['status'] == 'confirmed'
    assert result['selected']['timestamp_seconds'] == .45


def test_measurement_retains_raw_angles_and_pts_and_rejects_collapsed_side():
    def joint(x, y):
        return dict(status='observed', visibility='unknown', final=dict(x=x, y=y),
                    raw=dict(x=x, y=y, model_score=.9), flags=[])

    frames = []
    for i in range(6):
        joints = {}
        for side, x in [('left', 20), ('right', 40)]:
            for part, y in [('shoulder', 10), ('hip', 30), ('knee', 31 if side == 'right' and i == 2 else 50), ('ankle', 70)]:
                joints[f'{side}_{part}'] = joint(x, y)
        frames.append(dict(joints=joints, track_state='tracked', frame_index=i, timestamp_seconds=i*.016,
                           source_pts=100+i*16, source_time_base='1/1000'))
    data = observations(dict(frames=frames))
    assert data[2]['source_pts'] == 132
    assert data[2]['torso_degrees'] == torso_degrees(frames[2]) == 0
    assert math.isclose(data[2]['left']['hip']['observed_degrees'], 180)
    assert data[2]['right']['hip']['observed_degrees'] is None
    assert data[2]['right']['hip']['filtered_degrees'] is None
    assert data[2]['right']['landmarks']['knee']['score'] == .9
