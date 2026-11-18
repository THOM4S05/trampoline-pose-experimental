"""Contact parity must detect contradictions without inventing rotation evidence."""
import copy

import pytest

from trampoline_pose.skill_identification import rotation_contact_check, analyze
from test_skill_identification import bouncing_export


@pytest.mark.parametrize('takeoff,landing,allowed', [
    ('feet', 'feet', {0}), ('feet', 'front', {1, 3}),
    ('back', 'feet', {1, 3}), ('body', 'feet', {1, 3}),
    ('front', 'back', {0, 2}), ('back', 'back', {0, 2}),
    ('seat', 'feet', {0}), ('feet', 'seat', {0}), ('seat', 'seat', {0}),
    ('seat', 'front', {1, 3}), ('back', 'seat', {1, 3}),
])
def test_fractional_turn_constraint_across_multiple_full_turns(takeoff, landing, allowed):
    for quarters in range(17):
        rotation = dict(somersault_count=None, candidate_somersault_count=quarters / 4,
                        reasons=['torso_gaps_or_jumps'])
        before = copy.deepcopy(rotation)
        check = rotation_contact_check(rotation, takeoff, landing)
        assert check['status'] == ('consistent' if quarters % 4 in allowed else 'conflict')
        assert check['count_source'] == 'tentative'
        assert rotation == before


@pytest.mark.parametrize('takeoff,landing,clipped', [
    ('unknown', 'feet', False), ('feet', 'unknown', False),
    ('seat', 'unknown', False), ('unknown', 'seat', False), ('feet', 'feet', True),
])
def test_unknown_and_partial_contacts_abstain(takeoff, landing, clipped):
    check = rotation_contact_check({'somersault_count': 1.75}, takeoff, landing, clipped)
    assert check['status'] == 'unavailable'
    assert check['allowed_quarter_remainders'] is None


def test_supported_count_is_checked_before_tentative_count():
    check = rotation_contact_check({'somersault_count': 2, 'candidate_somersault_count': 1.75}, 'feet', 'feet')
    assert check['status'] == 'consistent'
    assert check['count_checked'] == 2
    assert check['count_source'] == 'supported'


def test_missing_count_cannot_be_inferred_from_feet_contacts():
    assert rotation_contact_check({}, 'feet', 'feet')['status'] == 'unavailable'


def test_analysis_attaches_check_and_does_not_force_partial_counts():
    result = analyze(bouncing_export(60))
    assert result['skills'][0]['rotation']['contact_consistency']['status'] == 'unavailable'
    assert result['skills'][0]['rotation']['somersault_count'] is None
    for skill in result['skills'][1:-1]:
        assert skill['rotation']['contact_consistency']['status'] == 'consistent'
        assert skill['rotation']['somersault_count'] == 0
