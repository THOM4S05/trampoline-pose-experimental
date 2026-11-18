"""Experimental native-frame opening evidence for TRA §20.2.1.3."""
import math
from bisect import bisect_left, bisect_right
from itertools import groupby
from statistics import median

import numpy as np

from .orientation import torso_degrees
from .skill_identification import centre, joint_angle, usable


SIDES = ('left', 'right')
PARTS = ('shoulder', 'hip', 'knee', 'ankle')
OPEN = 171
FOLDED = 135
SMOOTH_SECONDS = .020
HOLD_SECONDS = .030
EPS = 1e-8


def stamp(row):
    return row['timestamp_seconds']


def number(value):
    return float(value) if math.isfinite(value) else None


def observations(data):
    """Retain native timing, unfiltered angles, and landmark quality."""
    frames = data['frames']
    if not frames:
        return []
    rows = [{key: frame[key] for key in ('frame_index', 'timestamp_seconds', 'source_pts', 'source_time_base')}
            | {'torso_degrees': torso_degrees(frame), 'track_state': frame['track_state'],
               'horizontal_face': horizontal_face(frame),
               'possible_frontal_projection': possible_frontal_projection(frame)} for frame in frames]
    times = np.asarray([stamp(row) for row in rows])
    for side in SIDES:
        names = [f'{side}_{part}' for part in PARTS]
        points = np.full((len(frames), len(names), 2), np.nan)
        raw_points = points.copy()
        for i, (frame, row) in enumerate(zip(frames, rows)):
            joints = {}
            for j, (part, name) in enumerate(zip(PARTS, names)):
                joint = frame.get('joints', {}).get(name, {})
                raw = joint.get('raw', {})
                xy = usable(frame, name)
                if xy is not None:
                    points[i, j] = xy
                if all(isinstance(raw.get(axis), (int, float)) for axis in ('x', 'y')):
                    raw_points[i, j] = [raw['x'], raw['y']]
                elif xy is not None:
                    raw_points[i, j] = xy
                joints[part] = dict(score=raw.get('model_score'), usable=xy is not None,
                                    status=joint.get('status'), visibility=joint.get('visibility'))
            row[side] = dict(landmarks=joints)

        lengths = np.linalg.norm(np.diff(points, axis=1), axis=2)
        minimum = []
        for column in lengths.T:
            good = column[np.isfinite(column)]
            minimum.append(max(5, .38 * median(good)) if len(good) else 5)
        collapsed = lengths < minimum
        for part, j in (('hip', 0), ('knee', 1)):
            apparent = joint_angle(*raw_points[:, j:j+3].transpose(1, 0, 2))
            angles = joint_angle(*points[:, j:j+3].transpose(1, 0, 2))
            short = collapsed[:, j:j+2].any(axis=1)
            quality = ['foreshortened_segment' if short[i] else
                       'unreliable_landmarks' if not math.isfinite(angle) else 'usable'
                       for i, angle in enumerate(angles)]
            angles[short] = np.nan
            # Flag a sharp reversal through an isolated observation. Sustained
            # motion is checked separately, without a fixed frames-per-second assumption.
            for i in range(1, len(angles) - 1):
                if stamp(rows[i+1]) - stamp(rows[i-1]) <= .085:
                    a, b, c = angles[i-1:i+2]
                    if abs(a-c) < 20 and min(abs(b-a), abs(b-c)) > 45:
                        angles[i] = np.nan
                        quality[i] = 'isolated_angle_jump'
            for i, row in enumerate(rows):
                row[side][part] = dict(raw_degrees=number(apparent[i]), observed_degrees=number(angles[i]),
                                       filtered_degrees=None, quality=quality[i])
            valid = np.flatnonzero(np.isfinite(angles))
            blocks = np.split(valid, np.flatnonzero(
                (np.diff(valid) != 1) | (np.diff(times[valid]) > 2 * SMOOTH_SECONDS + EPS)) + 1)
            for block in blocks:
                if len(block):
                    for i in block:
                        start = max(block[0], bisect_left(times, times[i] - SMOOTH_SECONDS - EPS))
                        stop = min(block[-1] + 1, bisect_right(times, times[i] + SMOOTH_SECONDS + EPS))
                        rows[i][side][part]['filtered_degrees'] = float(np.median(angles[start:stop]))
    return rows


def horizontal_face(frame):
    """Anatomical front/back evidence near a horizontal bed contact."""
    nose = usable(frame, 'nose')
    if nose is None:
        return None
    axis = centre(frame, 'shoulder') - centre(frame, 'hip')
    length = np.linalg.norm(axis)
    if not np.isfinite(length) or length < 10 or abs(axis[1]) > .45 * length:
        return None
    offset = (nose - centre(frame, 'ear')) / length
    if not np.isfinite(offset).all() or abs(offset[1]) < .12 or abs(offset[0]) > abs(offset[1]):
        return None
    return 'front' if offset[1] > 0 else 'back'


def possible_frontal_projection(frame):
    """A broad view can hide sagittal flexion even with visible landmarks."""
    pairs = [[usable(frame, f'{side}_{part}') for side in SIDES] for part in ('shoulder', 'hip')]
    if any(point is None for pair in pairs for point in pair):
        return False
    (left_shoulder, right_shoulder), (left_hip, right_hip) = pairs
    torso = np.linalg.norm((left_shoulder + right_shoulder - left_hip - right_hip) / 2)
    return bool(torso > 10 and np.linalg.norm(left_shoulder - right_shoulder) > .75 * torso
                and np.linalg.norm(left_hip - right_hip) > .50 * torso)


def bilateral(row, part='hip', kind='observed_degrees'):
    if row.get('possible_frontal_projection'):
        return None
    values = [row[side][part][kind] for side in SIDES]
    if None in values or abs(values[0] - values[1]) > 35:
        return None
    return values


def shape(row):
    hips = bilateral(row, kind='filtered_degrees')
    knees = bilateral(row, 'knee', 'filtered_degrees')
    if hips is None or knees is None or max(hips) > FOLDED:
        return None
    if max(knees) <= FOLDED:
        return 'tuck'
    if min(knees) > FOLDED:
        return 'pike'
    return None


def is_open(row, kind):
    hips = bilateral(row, kind=kind)
    return hips is not None and min(hips) >= OPEN - EPS


def pike_flexion(row):
    hips = bilateral(row, kind='filtered_degrees')
    knees = bilateral(row, 'knee', 'filtered_degrees')
    return (hips is not None and knees is not None
            and max(hips) < OPEN - EPS and min(knees) > FOLDED)


def flight_bounds(skill):
    timing = skill.get('time_of_flight', {})
    start = timing.get('takeoff_seconds')
    end = timing.get('landing_seconds')
    return (max(skill['visible_start_seconds'], start) if start is not None else skill['visible_start_seconds'],
            min(skill['visible_end_seconds'], end) if end is not None else skill['visible_end_seconds'])


def progression(skill, rows, gap):
    """Map the existing torso clock to continuous rotation, anchored at landing."""
    rotation = skill['rotation']
    turns = rotation.get('projected_turns')
    if not turns or abs(turns) < .12 or skill.get('end_clipped'):
        return {}, None, None
    sign = math.copysign(1, turns)
    end = flight_bounds(skill)[1]
    # A short torso outage can still leave an unambiguous direction of
    # travel. A selected frame needs its own observed angle in all cases.
    clock_gap = max(gap, min(.060, max(.040, 2 * gap)))
    suffix = []
    for row in reversed(rows):
        if row['torso_degrees'] is None:
            continue
        if suffix and stamp(suffix[-1]) - stamp(row) > clock_gap:
            break
        suffix.append(row)
    if len(suffix) < 3 or end - stamp(suffix[0]) > clock_gap:
        return {}, None, None
    suffix.reverse()
    degrees = np.unwrap([row['torso_degrees'] for row in suffix], period=360) * sign
    deltas = np.diff(degrees)
    # A cumulative sum of negative steps counts every small pose jitter as a
    # reversal, especially in high-FPS footage. Check actual reverse travel.
    backward_excursion = np.max(np.maximum.accumulate(degrees) - degrees)
    if np.max(np.abs(deltas)) > 95 or backward_excursion > 45:
        return {}, None, None
    phase = {row['frame_index']: float(angle) for row, angle in zip(suffix, degrees)}
    landing = skill.get('landing_position')
    count = rotation.get('somersault_count')
    if (count == 0 or rotation.get('contact_consistency', {}).get('status') == 'conflict'
            or (count is None and (abs(turns) < .5 or degrees[-1] - degrees[0] < 90))):
        return phase, None, None
    if landing in (None, 'unknown', 'body') and skill.get('landing_contact'):
        # Require consistent observations close to measured bed arrival.
        votes = [row['horizontal_face'] for row in suffix if end - stamp(row) <= .085
                 and row.get('horizontal_face') is not None]
        if len(votes) >= 2 and len(set(votes)) == 1:
            landing = votes[0]
    if landing == 'feet':
        landing_axis = round(degrees[-1] / 360) * 360
        offset = 180
    elif landing in ('front', 'back'):
        base = 270 if landing == 'front' else 90
        landing_axis = base + round((degrees[-1] - base) / 360) * 360
        offset = 90
    else:
        return phase, None, None
    if abs(degrees[-1] - landing_axis) > 45 or degrees[-1] - degrees[0] < 30:
        return phase, None, None
    return phase, landing_axis - offset, landing


def judging(skill, status, selected, phase, anchor, landing):
    result = dict(phase_degrees=None, opening_deduction=None, landing_context=landing, status='unavailable')
    if status == 'not_applicable' or skill['rotation'].get('somersault_count') == 0:
        result['status'] = 'not_applicable'
    elif anchor is not None and status == 'incomplete':
        result.update(opening_deduction=.3, status='estimated')
    elif anchor is not None and status in ('confirmed', 'coach_confirmed'):
        degrees = phase.get(selected['frame_index'])
        if degrees is not None:
            elapsed = round(degrees - anchor, 2)
            result.update(phase_degrees=elapsed, status='estimated',
                          opening_deduction=.0 if elapsed <= 30 else .1 if elapsed <= 60 else .2 if elapsed <= 90 else .3)
    return result


def candidate(row):
    return ({key: row[key] for key in ('frame_index', 'timestamp_seconds', 'source_pts', 'source_time_base',
                                      'torso_degrees', *SIDES)}
            | {'possible_frontal_projection': row.get('possible_frontal_projection', False)})


def opening_analysis(skill, rows):
    start, end = flight_bounds(skill)
    flight = [row for row in rows if start + EPS < stamp(row) < end - EPS]
    periods = [stamp(b) - stamp(a) for a, b in zip(flight, flight[1:])]
    gap = min(.12, max(.025, 1.6 * median(periods))) if periods else .08
    phase, anchor, landing = progression(skill, flight, gap)
    result = dict(status='not_applicable', selected=None, episodes=[], post_opening_flexion=[],
                  reasons=[], flight_bounds_seconds=[start, end], continuity_seconds=gap)
    if skill['execution'].get('body_position') == 'straight':
        result['fig'] = judging(skill, result['status'], None, phase, anchor, landing)
        return result

    # Split on both state transitions and timing outages. Missing observations
    # are never bridged to manufacture a shape, threshold crossing or hold.
    states = [('open' if is_open(row, 'observed_degrees') else
               shape(row) or ('flexed' if pike_flexion(row) else None)) for row in flight]
    blocks = np.cumsum([0, *(period > gap for period in periods)]) if flight else []
    fold = None
    for (state, _), indices in groupby(range(len(flight)), key=lambda i: (states[i], blocks[i])):
        indices = list(indices)
        first, last = indices[0], indices[-1]
        a, b = flight[first], flight[last]
        duration = stamp(b) - stamp(a)
        if state in ('tuck', 'pike', 'flexed') and duration >= HOLD_SECONDS - EPS:
            if not result['episodes']:
                if (fold is None and state != 'flexed' and stamp(a) < start + .8 * (end - start)
                        and stamp(b) > start + .12 * (end - start)):
                    fold = (state, first)
                continue
            # A prolonged refold with rotation still to complete can begin a
            # new pike phase. Terminal pike-down and re-extension stay attached
            # to the previous kickout. A held retuck has distinct knee evidence.
            at_end = phase.get(flight[-1]['frame_index'])
            at_fold = phase.get(a['frame_index'])
            remaining = None if at_end is None or at_fold is None else at_end - at_fold
            before_landing_phase = (remaining is not None
                                    and (remaining >= 190 if anchor is None else at_fold < anchor))
            pike_phase = (state == 'pike' and duration >= .070 - EPS
                          and before_landing_phase and remaining >= 90)
            upright_pike_phase = (state == 'pike' and skill['rotation'].get('somersault_count') == 0
                                  and duration >= .10 - EPS and stamp(a) < start + .65 * (end - start)
                                  and stamp(b) < start + .80 * (end - start))
            retuck = state == 'tuck' and end - stamp(a) >= .12
            if (retuck or pike_phase or upright_pike_phase) and fold is None:
                fold = (state, first)
            elif fold is None and state != 'tuck':
                result['post_opening_flexion'].append(
                    dict(start=candidate(a), end=candidate(b), kind='pike_down',
                         before_fig_three=None if anchor is None or at_fold is None else at_fold < anchor + 90))
        elif state == 'open' and fold and duration >= HOLD_SECONDS - EPS:
            supported = sum(is_open(flight[i], 'filtered_degrees') for i in indices)
            if supported >= 2:
                previous = flight[first-1] if first else None
                crossing_known = (previous is not None and stamp(a) - stamp(previous) <= gap
                                  and bilateral(previous) is not None
                                  and not is_open(previous, 'observed_degrees'))
                prior = next((row for row in reversed(flight[fold[1]:first])
                              if bilateral(row) is not None and not is_open(row, 'observed_degrees')), None)
                result['episodes'].append(dict(frame=candidate(a), end_frame_index=b['frame_index'],
                                              confirmation_seconds=duration, preceding_shape=fold[0],
                                              preceding_shape_start_seconds=stamp(flight[fold[1]]),
                                              crossing_observed=bool(crossing_known),
                                              crossing_interval_seconds=[stamp(prior), stamp(a)] if prior else None))
                fold = None

    best = None
    if result['episodes']:
        episode = result['episodes'][-1]
        best = episode['frame']
        if not episode['crossing_observed']:
            result['reasons'].append('opening_crossing_may_be_hidden')
        if (skill.get('time_of_flight', {}).get('landing_seconds') is None
                and end - stamp(best) < .09):
            result['reasons'].append('opening_near_unverified_landing')
        late_visible = [stamp(row) for row in flight if row['frame_index'] >= episode['end_frame_index']
                        and stamp(row) < end - .12 and bilateral(row) is not None]
        if late_visible and any(b - a >= .12 for a, b in zip(late_visible, [*late_visible[1:], end - .12])):
            result['reasons'].append('later_opening_coverage_gap')
    if not best or fold:
        selected = flight[fold[1]:] if fold else flight
        if selected and best is None:
            def rank(row):
                hips = bilateral(row)
                one_side = [row[side]['hip']['observed_degrees'] for side in SIDES]
                return (hips is not None, min(hips) if hips else max((v for v in one_side if v is not None), default=-1))
            best = candidate(max(selected, key=rank))
        if not fold:
            result['reasons'].append('no_supported_prior_tuck_or_pike')
        elif (len(selected) < 3 or (selected and end - stamp(selected[-1]) > gap)
              or any(bilateral(row) is None for row in selected)
              or any(stamp(y) - stamp(x) > gap for x, y in zip(selected, selected[1:]))):
            result['reasons'].append('insufficient_bilateral_opening_coverage')
        elif any(is_open(row, 'observed_degrees') for row in selected):
            result['reasons'].append('opening_not_sustained')
        if result['episodes']:
            result['reasons'].append('later_refold_without_confirmed_opening')
    if (skill.get('start_clipped') or skill.get('end_clipped')) and (not result['episodes'] or fold or skill.get('end_clipped')):
        result['reasons'].append('partial_flight')
    status = 'needs_review' if result['reasons'] else 'confirmed' if result['episodes'] else 'incomplete'
    result.update(status=status, selected=best, fig=judging(skill, status, best, phase, anchor, landing))
    return result


def coach_selection(skill, rows, frame_index):
    start, end = flight_bounds(skill)
    flight = [row for row in rows if start + EPS < stamp(row) < end - EPS]
    selected = next((candidate(row) for row in flight if row['frame_index'] == frame_index), None)
    if selected is None:
        raise ValueError('Choose a native frame inside this skill’s flight')
    phase, anchor, landing = progression(skill, flight, skill['kickout']['continuity_seconds'])
    return dict(status='coach_confirmed', selected=selected,
                fig=judging(skill, 'coach_confirmed', selected, phase, anchor, landing))
