"""Recover tentative somersault counts from observed torso phase passages.

This module never reads reference annotations, changes joints, or moves contacts.
Feet and seat both have an upright torso; front/back have a horizontal torso.
"""
import numpy as np


def _phase_runs(t, axes):
    lengths = np.linalg.norm(axes, axis=1)
    valid = np.isfinite(axes).all(axis=1) & (lengths > 10)
    vertical = np.full(len(t), np.nan)
    vertical[valid] = -axes[valid, 1] / lengths[valid]
    runs = []
    for i in np.flatnonzero(valid):
        v = vertical[i]
        state = 'upright' if v >= .6 else 'inverted' if v <= -.6 else 'horizontal'
        if runs and runs[-1]['phase'] == state and t[i] - runs[-1]['end'] <= .16:
            runs[-1].update(end=float(t[i]), samples=runs[-1]['samples'] + 1)
        else:
            runs.append(dict(phase=state, start=float(t[i]), end=float(t[i]), samples=1))
    return [r for r in runs if r['samples'] >= 2 and r['end'] - r['start'] >=
            (.012 if r['phase'] == 'horizontal' else .03)], valid


def _distance(run, stamp):
    return max(run['start'] - stamp, stamp - run['end'], 0)


def phase_rotation_evidence(t, shoulder, hip, start, end, contact_start, contact_end, clipped=False):
    """Count supported alternating upright/inverted passages, including end quarters.

    Recovered values stay tentative: projected torso phases are not independent
    verification of the full 3D rotation or the anatomical landing surface.
    """
    result = dict(method='observed_torso_phase_passages', version=1, status='unavailable',
                  candidate_somersault_count=None, candidate_somersault_quarters=None,
                  takeoff_phase='unknown', landing_phase='unknown',
                  observed_inversion_count=None, phase_sequence=[], rejected_phase_runs=[], reasons=[])
    if clipped:
        result['reasons'].append('partial_flight')
        return result
    t = np.asarray(t, dtype=float)
    axes = np.asarray(shoulder, dtype=float) - np.asarray(hip, dtype=float)
    if len(t) < 3 or not np.isfinite(t).all() or np.any(np.diff(t) <= 0):
        result['reasons'].append('insufficient_phase_timing')
        return result
    runs, valid = _phase_runs(t, axes)

    def endpoint(stamp, contact):
        choices = [r for r in runs if r['phase'] != 'inverted' and _distance(r, stamp) <= .08]
        if choices:
            r = min(choices, key=lambda r: _distance(r, stamp))
            return dict(phase=r['phase'], method='near_rotation_endpoint',
                        evidence_start_seconds=r['start'], evidence_end_seconds=r['end'])
        # A contact occlusion can hide the horizontal endpoint. Nearby observed
        # post-contact motion supplies a proxy, explicitly retained as tentative.
        choices = [r for r in runs if r['phase'] != 'inverted' and _distance(r, contact) <= .25]
        if choices:
            r = min(choices, key=lambda r: _distance(r, contact))
            return dict(phase=r['phase'], method='near_contact_proxy_needs_review',
                        evidence_start_seconds=r['start'], evidence_end_seconds=r['end'])
        return dict(phase='unknown', method='unavailable')

    first, last = endpoint(start, contact_start), endpoint(end, contact_end)
    result.update(takeoff_phase=first['phase'], landing_phase=last['phase'],
                  takeoff_evidence=first, landing_evidence=last)
    if 'unknown' in (first['phase'], last['phase']):
        result['reasons'].append('contact_phase_unresolved')
        return result
    ids = np.flatnonzero(valid & (t >= start) & (t <= end))
    if len(ids) < 3 or (t[ids[-1]] - t[ids[0]]) < .3:
        result['reasons'].append('insufficient_phase_coverage')
        return result
    gaps = np.diff(t[ids])
    # Even at the existing raw-angle veto of 40 rad/s, this gap cannot hide a
    # complete extra revolution. Longer gaps must retain count ambiguity.
    result['max_observed_gap_seconds'] = float(gaps.max())
    if gaps.max() * 40 >= 2 * np.pi:
        result['reasons'].append('gap_could_hide_additional_rotation')
        return result
    theta = np.arctan2(axes[ids, 0], -axes[ids, 1])
    delta = (np.diff(theta) + np.pi) % (2 * np.pi) - np.pi
    stable = np.abs(delta) / gaps < 20
    forward = float(delta[stable & (delta > 0)].sum())
    backward = float(-delta[stable & (delta < 0)].sum())
    if min(forward, backward) > np.pi / 2 and min(forward, backward) > .25 * (forward + backward):
        result['reasons'].append('phase_direction_reversal_or_projection_ambiguity')
        return result
    core = [dict(r, start=max(r['start'], start), end=min(r['end'], end)) for r in runs
            if r['end'] >= start and r['start'] <= end]
    horizontal = [r for r in core if r['phase'] == 'horizontal']
    anchors = []
    if first['phase'] == 'upright':
        anchors.append(dict(phase='upright', start=start, end=start, samples=0))
    for r in core:
        if r['phase'] == 'horizontal':
            continue
        if anchors and r['phase'] == anchors[-1]['phase']:
            anchors[-1]['end'] = max(anchors[-1]['end'], r['end'])
            continue
        previous = anchors[-1]['end'] if anchors else start
        has_horizontal = any(h['start'] >= previous - 1e-6 and h['end'] <= r['start'] + 1e-6
                             for h in horizontal)
        if not has_horizontal:
            # Upright endpoint evidence may itself begin just inside the window.
            if not anchors and r['phase'] == first['phase']:
                anchors.append(r)
                continue
            result['rejected_phase_runs'].append(r)
            if r['end'] - r['start'] >= .12:
                result['reasons'].append('unsupported_sustained_phase_transition')
            continue
        anchors.append(r)
    if result['reasons']:
        return result
    if last['phase'] == 'upright' and anchors and anchors[-1]['phase'] != 'upright':
        if not any(h['start'] >= anchors[-1]['end'] - 1e-6 for h in horizontal):
            result['reasons'].append('missing_final_phase_transition')
            return result
        anchors.append(dict(phase='upright', start=end, end=end, samples=0))
    if not anchors:
        result['reasons'].append('no_supported_vertical_phase')
        return result
    quarters = 2 * (len(anchors) - 1)
    quarters += int(first['phase'] == 'horizontal') + int(last['phase'] == 'horizontal')
    result.update(status='tentative', candidate_somersault_quarters=quarters,
                  candidate_somersault_count=quarters / 4,
                  observed_inversion_count=sum(r['phase'] == 'inverted' for r in anchors),
                  phase_sequence=anchors)
    return result


def recover_rotation(rotation, evidence, contact_positions=None):
    """Refine tentative counts only; retain the original angle result verbatim."""
    rotation['phase_evidence'] = evidence
    if rotation.get('somersault_count') is not None or evidence['status'] != 'tentative':
        return
    if contact_positions is not None:
        for position, key in zip(contact_positions, ('takeoff_phase', 'landing_phase')):
            expected = ('upright' if position in ('feet', 'seat', 'upright') else
                        'horizontal' if position in ('front', 'back', 'body') else None)
            if expected is not None and evidence[key] != expected:
                evidence['status'] = 'conflict'
                evidence['reasons'].append('observed_contact_and_phase_disagree')
                return
    count = evidence['candidate_somersault_count']
    original = rotation.get('candidate_somersault_count')
    # A large disagreement indicates possible missed phases, rather than a
    # licence to replace the angle counter with an unrelated interpretation.
    if original is None or abs(count - original) > .75:
        evidence['status'] = 'conflict'
        evidence['reasons'].append('phase_and_angle_counts_disagree')
        return
    rotation['angle_candidate_somersault_count'] = original
    rotation['angle_candidate_somersault_quarters'] = rotation.get('candidate_somersault_quarters')
    rotation['candidate_somersault_count'] = count
    rotation['candidate_somersault_quarters'] = evidence['candidate_somersault_quarters']
    rotation['count_method'] = 'torso_phases_and_contact_orientation'
    rotation['reasons'] = list(dict.fromkeys([*rotation.get('reasons', []), 'phase_contact_count_needs_review']))
