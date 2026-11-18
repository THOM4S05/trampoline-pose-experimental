"""FIG 2025–2028 TRA element difficulty; all arithmetic uses integer tenths.

Source: TRA CoP §17.1.1–17.1.6 (July 2025 publication).
This is an element value, before routine eligibility, repetition or age caps.
"""
from __future__ import annotations

import math

SOURCE = 'https://www.gymnastics.sport/publicdir/rules/files/en_1.1%20-%20TRA%20Code%20of%20Points%202025-2028.pdf'
RULESET = 'FIG-TRA-2025-2028'


def _integer(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value == int(value))


def element_difficulty(quarters, half_twists, shape='unknown', direction='unknown',
                       takeoff='unknown', landing='unknown'):
    """Calculate from resolved descriptors, never round raw angular estimates.

    Missing inputs block a value only when they can change its calculation.
    A straight zero-rotation bounce has value zero (no counting element).
    """
    result = dict(ruleset=RULESET, source=SOURCE, value=None, status='unknown',
                  components={}, reasons=[])
    reasons = result['reasons']
    if not _integer(quarters) or not 0 <= quarters <= 16:
        reasons.append('somersault_quarters_missing_or_outside_0_to_16')
    if not _integer(half_twists) or half_twists < 0:
        reasons.append('half_twists_missing_or_invalid')
    if reasons:
        return result
    q, h = int(quarters), int(half_twists)
    full, remainder = divmod(q, 4)
    parts = dict(somersault=(0, 5, 10, 16, 22)[full] + remainder,
                 twist=h, position=0, backward_bonus=0, twist_bonus=0,
                 non_rotating_element=0)
    if q == 0 and h == 0:
        if landing == 'seat' or (takeoff == landing == 'feet' and shape in ('tuck', 'pike', 'straddle')):
            parts['non_rotating_element'] = 1
        elif takeoff == landing == 'feet' and shape == 'straight':
            pass
        else:
            reasons.append('non_rotating_element_identity_unresolved')
    if (4 <= q <= 7 and h == 0) or q >= 8:
        if shape not in ('tuck', 'pike', 'straight'):
            reasons.append('body_position_unresolved')
        elif shape in ('pike', 'straight'):
            parts['position'] = 1 if q < 8 else full
    if q >= 8:
        if direction not in ('forward', 'backward'):
            reasons.append('somersault_direction_unresolved')
        elif direction == 'backward':
            parts['backward_bonus'] = full - 1
    if full == 2:
        parts['twist_bonus'] = max(0, h - 4)
    elif full == 3:
        parts['twist_bonus'] = 2 * max(0, h - 2)
    elif full == 4:
        parts['twist_bonus'] = 2 * h
    result['components'] = {key: value / 10 for key, value in parts.items()}
    if not reasons:
        result.update(value=sum(parts.values()) / 10, status='calculated')
    return result


def flight_difficulty(skill):
    """Adapt saved flight evidence; detector values are always provisional."""
    rotation = skill.get('rotation') or {}
    twist = skill.get('twist')
    twist = twist if isinstance(twist, dict) else {}
    q = rotation.get('somersault_quarters')
    rotation_source = 'somersault_quarters'
    if q is None:
        count = rotation.get('somersault_count')
        q = count * 4 if isinstance(count, (int, float)) else None
        rotation_source = 'somersault_count'
    if q is None:
        q = rotation.get('candidate_somersault_quarters')
        if q is None:
            count = rotation.get('candidate_somersault_count')
            q = count * 4 if isinstance(count, (int, float)) else None
        rotation_source = 'candidate_rotation'
    count = twist.get('count')
    twist_source = 'count'
    # A candidate may be used for an explicitly provisional calculation only.
    if count is None:
        count = twist.get('candidate_count') if twist.get('status') == 'tentative' else None
        twist_source = 'candidate_count'
    half = count * 2 if isinstance(count, (int, float)) and not isinstance(count, bool) else None
    direction = rotation.get('direction')
    if direction not in ('forward', 'backward'):
        direction = rotation.get('candidate_direction', 'unknown')
    shape = (skill.get('execution') or {}).get('body_position', 'unknown')
    result = element_difficulty(q, half, shape, direction,
                                skill.get('takeoff_position'), skill.get('landing_position'))
    result['inputs'] = dict(somersault_quarters=q, half_twists=half, shape=shape,
                           direction=direction, rotation_source=rotation_source,
                           twist_source=twist_source)
    if skill.get('start_clipped') or skill.get('end_clipped'):
        result.update(value=None, status='unknown')
        result['reasons'].append('partial_flight')
    elif (rotation.get('contact_consistency') or {}).get('status') == 'conflict':
        result.update(value=None, status='unknown')
        result['reasons'].append('rotation_conflicts_with_contacts')
    elif result['value'] is not None:
        result['status'] = 'provisional'
        result['reasons'].append('detected_descriptors_require_video_review')
    return result


def attach_difficulty(analysis):
    """Refresh after rotation/twist analysis; safe to call repeatedly."""
    for skill in analysis.get('skills', []):
        skill['difficulty'] = flight_difficulty(skill)
    return analysis
