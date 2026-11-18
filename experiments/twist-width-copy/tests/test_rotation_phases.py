"""Rotation recovery across endpoints, sampling rates, gaps and pose corruption."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from trampoline_pose.rotation_phases import phase_rotation_evidence, recover_rotation


def motion(turns, initial=0, rate=120, duration=2):
    t = np.linspace(0, duration, round(duration * rate) + 1)
    theta = initial + turns * 2 * np.pi * t / duration
    hip = np.zeros((len(t), 2))
    shoulder = np.column_stack([100 * np.sin(theta), -100 * np.cos(theta)])
    return t, shoulder, hip


@pytest.mark.parametrize('rate', [24, 30, 60, 120, 240])
@pytest.mark.parametrize('turns,initial', [
    (0, 0), (1, 0), (2, 0), (3, 0), (-2, 0),
    (.25, 0), (.75, 0), (1.25, 0), (1.75, 0), (2.25, 0),
    (.25, -np.pi / 2), (.75, np.pi / 2), (1.25, -np.pi / 2), (2.25, -np.pi / 2),
    (.5, np.pi / 2), (-.5, np.pi / 2), (1, np.pi / 2), (1.5, np.pi / 2),
])
def test_counts_across_upright_and_horizontal_endpoints(rate, turns, initial):
    t, shoulder, hip = motion(turns, initial, rate)
    evidence = phase_rotation_evidence(t, shoulder, hip, 0, 2, 0, 2)
    assert evidence['candidate_somersault_count'] == abs(turns), evidence


def test_boundary_pose_flip_without_horizontal_transition_is_not_an_extra_flip():
    t, shoulder, hip = motion(2)
    shoulder[(t >= .04) & (t <= .1)] *= -1
    evidence = phase_rotation_evidence(t, shoulder, hip, 0, 2, 0, 2)
    assert evidence['candidate_somersault_count'] == 2
    assert evidence['observed_inversion_count'] == 2
    assert evidence['rejected_phase_runs']


def test_short_occlusion_during_one_inversion_does_not_split_it():
    t, shoulder, hip = motion(2)
    shoulder[(t > .22) & (t < .29)] = np.nan
    evidence = phase_rotation_evidence(t, shoulder, hip, 0, 2, 0, 2)
    assert evidence['observed_inversion_count'] == 2
    assert evidence['candidate_somersault_count'] == 2


def test_long_gap_cannot_silently_hide_an_additional_rotation():
    t, shoulder, hip = motion(2)
    shoulder[(t > .2) & (t < .5)] = np.nan
    evidence = phase_rotation_evidence(t, shoulder, hip, 0, 2, 0, 2)
    assert evidence['status'] == 'unavailable'
    assert 'gap_could_hide_additional_rotation' in evidence['reasons']


def test_reversal_is_not_counted_as_a_complete_somersault():
    t, shoulder, hip = motion(1)
    theta = np.where(t <= 1, t * np.pi, (2 - t) * np.pi)
    shoulder[:] = np.column_stack([100 * np.sin(theta), -100 * np.cos(theta)])
    evidence = phase_rotation_evidence(t, shoulder, hip, 0, 2, 0, 2)
    assert evidence['status'] == 'unavailable'
    assert 'phase_direction_reversal_or_projection_ambiguity' in evidence['reasons']


def test_partial_flight_and_missing_endpoints_abstain():
    t, shoulder, hip = motion(2)
    assert phase_rotation_evidence(t, shoulder, hip, 0, 2, 0, 2, clipped=True)['status'] == 'unavailable'
    shoulder[t > 1.5] = np.nan
    assert phase_rotation_evidence(t, shoulder, hip, 0, 2, 0, 2)['status'] == 'unavailable'


def test_recovery_preserves_supported_counts_and_raw_measurement():
    t, shoulder, hip = motion(2)
    evidence = phase_rotation_evidence(t, shoulder, hip, 0, 2, 0, 2)
    supported = dict(somersault_count=1, somersault_quarters=4, candidate_somersault_count=1,
                     projected_turns=1.02, reasons=[])
    before = copy.deepcopy(supported)
    recover_rotation(supported, evidence)
    supported.pop('phase_evidence')
    assert supported == before
    tentative = dict(somersault_count=None, candidate_somersault_count=1.75,
                     candidate_somersault_quarters=7, projected_turns=1.86, reasons=['torso_gaps_or_jumps'])
    recover_rotation(tentative, evidence)
    assert tentative['candidate_somersault_count'] == 2
    assert tentative['angle_candidate_somersault_count'] == 1.75
    assert tentative['projected_turns'] == 1.86
    assert tentative['somersault_count'] is None


def test_large_disagreement_is_not_overridden():
    t, shoulder, hip = motion(3)
    evidence = phase_rotation_evidence(t, shoulder, hip, 0, 2, 0, 2)
    rotation = dict(somersault_count=None, candidate_somersault_count=1)
    recover_rotation(rotation, evidence)
    assert rotation['candidate_somersault_count'] == 1
    assert rotation['phase_evidence']['status'] == 'conflict'


def test_phase_proxy_cannot_override_an_observed_seat_or_feet_contact():
    t, shoulder, hip = motion(1.75)
    evidence = phase_rotation_evidence(t, shoulder, hip, 0, 2, 0, 2)
    rotation = dict(somersault_count=None, candidate_somersault_count=1.5)
    recover_rotation(rotation, evidence, ('feet', 'seat'))
    assert rotation['candidate_somersault_count'] == 1.5
    assert evidence['status'] == 'conflict'
    assert 'observed_contact_and_phase_disagree' in evidence['reasons']


def test_reviewed_liam_counts_from_pose_evidence_without_reference_input():
    fixture = json.loads((Path(__file__).parent / 'fixtures/liam_rotation_phases.json').read_text())
    samples = np.asarray(fixture['samples'], dtype=float)
    for flight in fixture['flights']:
        a, b, start, end = [flight[k] for k in ('contact_start', 'contact_end', 'start', 'end')]
        context = (samples[:, 0] >= min(a, start) - .35) & (samples[:, 0] <= max(b, end) + .35)
        rows = samples[context]
        evidence = phase_rotation_evidence(rows[:, 0], rows[:, 1:], np.zeros((len(rows), 2)),
                                           start, end, a, b, flight['clipped'])
        rotation = dict(somersault_count=flight['supported'],
                        candidate_somersault_count=flight['angle_candidate'],
                        candidate_somersault_quarters=round(flight['angle_candidate'] * 4), reasons=[])
        recover_rotation(rotation, evidence)
        assert rotation['candidate_somersault_count'] == flight['expected'], flight['index']
        assert rotation['somersault_count'] == flight['supported']


def test_somersault_recovery_does_not_change_existing_twist_decoder_output():
    from trampoline_pose.twist_width import attach
    fixtures = json.loads((Path(__file__).parent / 'fixtures/varsities.json').read_text())
    for fixture in fixtures:
        before = dict(skills=[copy.deepcopy(fixture['skill'])])
        after = copy.deepcopy(before)
        rotation = after['skills'][0]['rotation']
        original = rotation['candidate_somersault_count']
        rotation['angle_candidate_somersault_count'] = original
        rotation['angle_candidate_somersault_quarters'] = rotation['candidate_somersault_quarters']
        rotation['candidate_somersault_count'] = original + .25
        rotation['candidate_somersault_quarters'] += 1
        attach(fixture['data'], before)
        attach(fixture['data'], after)
        assert before['skills'][0]['twist'] == after['skills'][0]['twist']
