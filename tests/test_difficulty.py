import pytest

from trampoline_pose.difficulty import element_difficulty, flight_difficulty, attach_difficulty


@pytest.mark.parametrize('q,h,shape,direction,expected', [
    (1, 0, 'unknown', 'unknown', .1),
    (3, 1, 'tuck', 'forward', .4),
    (4, 0, 'tuck', 'backward', .5),
    (4, 0, 'pike', 'backward', .6),
    (4, 1, 'straight', 'forward', .6),
    (4, 2, 'straight', 'backward', .7),
    (5, 0, 'pike', 'backward', .7),
    (7, 0, 'pike', 'forward', .9),
    (8, 0, 'tuck', 'backward', 1.1),
    (8, 0, 'pike', 'backward', 1.3),
    (8, 1, 'tuck', 'forward', 1.1),
    (8, 4, 'straight', 'backward', 1.7),
    (8, 5, 'tuck', 'forward', 1.6),
    (8, 8, 'straight', 'backward', 2.5),
    (11, 0, 'tuck', 'backward', 1.4),
    (12, 0, 'tuck', 'backward', 1.8),
    (12, 3, 'pike', 'forward', 2.4),
    (12, 6, 'straight', 'backward', 3.5),
    (15, 0, 'tuck', 'backward', 2.1),
    (16, 2, 'straight', 'backward', 3.5),
])
def test_cop_examples_and_bonus_boundaries(q, h, shape, direction, expected):
    result = element_difficulty(q, h, shape, direction)
    assert result['value'] == expected
    assert round(sum(result['components'].values()), 1) == expected


@pytest.mark.parametrize('q,h', [(None, 0), (4, None), (4.1, 0), (-1, 0),
                                     (17, 0), (4, -.5), (4, float('nan')), (True, 0)])
def test_invalid_descriptors_never_get_rounded_into_skills(q, h):
    assert element_difficulty(q, h)['value'] is None


def test_unknown_shape_and_direction_only_block_when_relevant():
    assert element_difficulty(4, 1)['value'] == .6
    assert element_difficulty(4, 0)['value'] is None
    assert element_difficulty(8, 0, 'tuck')['value'] is None


def test_non_rotating_elements():
    for shape in ('tuck', 'pike', 'straddle'):
        assert element_difficulty(0, 0, shape, takeoff='feet', landing='feet')['value'] == .1
    assert element_difficulty(0, 0, landing='seat')['value'] == .1
    assert element_difficulty(0, 0, 'straight', takeoff='feet', landing='feet')['value'] == 0
    assert element_difficulty(0, 0)['value'] is None


def flight():
    return dict(rotation=dict(candidate_somersault_count=2, candidate_direction='backward'),
                execution=dict(body_position='pike'),
                twist=dict(status='tentative', count=None, candidate_count=1))


def test_candidates_are_explicit_and_partial_flights_are_blocked():
    skill = flight()
    result = flight_difficulty(skill)
    assert result['value'] == 1.5
    assert result['status'] == 'provisional'
    assert result['inputs']['twist_source'] == 'candidate_count'
    skill['start_clipped'] = True
    assert flight_difficulty(skill)['value'] is None


def test_missing_twist_never_defaults_to_zero_or_uses_reference():
    skill = flight()
    skill['twist'] = 'deferred'
    skill['supplied_skill_identity'] = 'double back'
    assert flight_difficulty(skill)['value'] is None
    skill['twist'] = dict(status='unknown', candidate_count=0)
    assert flight_difficulty(skill)['value'] is None


def test_attachment_refreshes_after_twist_analysis():
    analysis = dict(skills=[flight()])
    attach_difficulty(analysis)
    analysis['skills'][0]['twist']['candidate_count'] = 0
    attach_difficulty(analysis)
    assert analysis['skills'][0]['difficulty']['value'] == 1.3


def test_conflicting_rotation_is_not_scored():
    skill = flight()
    skill['rotation']['contact_consistency'] = dict(status='conflict')
    assert flight_difficulty(skill)['value'] is None
