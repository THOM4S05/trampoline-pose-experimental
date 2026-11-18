"""Experimental side-on torso-width passages; no model inference or 3D claims."""
from dataclasses import asdict, dataclass
import math

import numpy as np
from scipy.signal import find_peaks

from .skill_identification import usable
from .upright_twist import jump_candidate
from .somersault_twist import candidate as somersault_candidate


@dataclass(frozen=True)
class WidthSettings:
    narrow_fraction: float = .35
    broad_fraction: float = .65
    stable_seconds: float = .015
    filter_radius_seconds: float = .025
    max_gap_seconds: float = .08
    minimum_shoulder_reference_px: float = 12
    minimum_hip_reference_px: float = 8
    finish_fraction: float = .50
    finish_minimum_drop: float = .45
    paired_valley_drop: float = .25
    reference_window_seconds: float = .15
    zero_minimum_coverage: float = .95
    zero_max_gap_seconds: float = .05
    zero_max_width_fraction: float = .60
    zero_minimum_narrow_fraction: float = .60


def zero_twist_evidence(selected,refs,skill,start,end,settings):
    """Positive narrow-torso evidence, including only short bounded outages."""
    good=[r for r in selected if r['shoulder_fraction'] is not None and r['hip_fraction'] is not None]
    coverage=len(good)/len(selected) if selected else 0.
    gaps=[b['timestamp_seconds']-a['timestamp_seconds'] for a,b in zip(good,good[1:])]
    max_gap=max([good[0]['timestamp_seconds']-start,end-good[-1]['timestamp_seconds']]+gaps) if good else end-start
    peak=max([max(r['shoulder_fraction'],r['hip_fraction']) for r in good],default=None)
    narrow=sum(max(r['shoulder_fraction'],r['hip_fraction'])<=settings.narrow_fraction for r in good)/len(good) if good else 0.
    failures=[]
    if skill.get('start_clipped') or skill.get('end_clipped'):
        failures.append('partial_flight')
    if end-start<.3 or len(good)<3:
        failures.append('insufficient_duration')
    if refs['shoulder'] is None or refs['shoulder']<settings.minimum_shoulder_reference_px or refs['hip'] is None or refs['hip']<settings.minimum_hip_reference_px:
        failures.append('insufficient_breadth_reference')
    if coverage<settings.zero_minimum_coverage:
        failures.append('insufficient_torso_coverage')
    if max_gap>settings.zero_max_gap_seconds+1e-9:
        failures.append('torso_gap_too_long')
    if peak is None or peak>settings.zero_max_width_fraction:
        failures.append('torso_broadening_present')
    if narrow<settings.zero_minimum_narrow_fraction:
        failures.append('narrow_torso_not_sustained')
    for edge,rows in [('start',[r for r in good if r['timestamp_seconds']<=start+.12]),
                      ('finish',[r for r in good if r['timestamp_seconds']>=end-.12])]:
        if (len(rows)<2 or rows[-1]['timestamp_seconds']-rows[0]['timestamp_seconds']<settings.stable_seconds
                or max(np.median([r[p+'_fraction'] for r in rows]) for p in ('shoulder','hip'))>settings.finish_fraction):
            failures.append('side_on_'+edge+'_not_supported')
    return dict(supported=not failures,method='sustained_narrow_torso_with_bounded_gaps',
                coverage=coverage,max_gap_seconds=max_gap,peak_width_fraction=peak,
                narrow_fraction=narrow,reasons=failures)


def split_paired_passages(selected, events, settings):
    """Resolve repeated broad phases inside an already bounded passage.

    Projection and occlusion can leave residual width at a side-on view.
    Require sustained bilateral narrowing AND re-expansion between peaks;
    an isolated spike or a dip in only one pair cannot split a passage.
    Absolute narrow start/finish checks remain the decoder's responsibility.
    """
    output=[]
    for event in events:
        rows=[r for r in selected if event['start_frame']<=r['frame_index']<=event['end_frame']]
        rows=[r for r in rows if all(r[p+'_fraction'] is not None for p in ('shoulder','hip'))]
        if (len(rows)<3 or any(b['timestamp_seconds']-a['timestamp_seconds']>settings.max_gap_seconds
                              for a,b in zip(rows,rows[1:]))):
            output.append(event)
            continue
        times=np.array([r['timestamp_seconds'] for r in rows])
        values=np.array([[r[p+'_fraction'] for p in ('shoulder','hip')] for r in rows])
        peaks=find_peaks(values.min(axis=1),prominence=settings.paired_valley_drop)[0]
        def sustained(mask):
            ids=np.flatnonzero(mask)
            breaks=(np.diff(ids)>1)|(np.diff(times[ids])>settings.max_gap_seconds)
            for group in np.split(ids,np.flatnonzero(breaks)+1):
                if len(group)>=2 and times[group[-1]]-times[group[0]]+1e-9>=settings.stable_seconds:
                    return group
            return None
        supported=[]
        for peak in peaks:
            broad=(values.min(axis=1)>=settings.broad_fraction)
            lo=hi=peak
            while lo>0 and broad[lo-1]:
                lo-=1
            while hi+1<len(rows) and broad[hi+1]:
                hi+=1
            if broad[peak] and hi>lo and times[hi]-times[lo]+1e-9>=settings.stable_seconds:
                supported.append(int(peak))
        if not supported:
            output.append(event)
            continue
        kept=[supported[0]]
        valleys=[]
        for peak in supported[1:]:
            previous=kept[-1]
            threshold=np.minimum(values[previous],values[peak])-settings.paired_valley_drop
            mask=(np.arange(len(rows))>previous)&(np.arange(len(rows))<peak)&(values<=threshold).all(axis=1)
            valley=sustained(mask)
            if valley is not None:
                valleys.append(int(valley[np.argmin(values[valley].max(axis=1))]))
                kept.append(peak)
            elif values[peak].min()>values[previous].min():
                kept[-1]=peak
        if len(kept)==1:
            output.append(event)
            continue
        boundaries=[event['start_frame']]+[rows[i]['frame_index'] for i in valleys]+[event['end_frame']]
        for i,peak in enumerate(kept):
            output.append(dict(start_frame=boundaries[i],end_frame=boundaries[i+1],
                broad_frame=rows[peak]['frame_index'],broad_seconds=times[peak].item(),
                candidate_half_turns=1,completion_method='sustained_paired_relative_narrowing',
                parent_passage=dict(start_frame=event['start_frame'],end_frame=event['end_frame']),
                paired_valley_drop=settings.paired_valley_drop))
    return output


def widths(frame):
    result = []
    for part in ('shoulder', 'hip'):
        a, b = [usable(frame, side + '_' + part) for side in ('left', 'right')]
        result.append(None if a is None or b is None else float(np.linalg.norm(a - b)))
    return result


def measure(data, settings=WidthSettings()):
    """One constant reference per segment for the recording, never torso length.

    q95 plus the broadest sustained median is an observed width reference,
    not calibrated anatomical breadth. A rare broad view in a long routine
    must not be discarded just because it occupies less than 5% of the clip.
    Euclidean pair distances are invariant to image-plane torso rotation and
    anatomical left/right swaps. Foreshortening and misassociation remain.
    """
    rows = [dict(frame_index=f['frame_index'], timestamp_seconds=float(f['timestamp_seconds']),
                 track_state=f.get('track_state'),
                 shoulder_width_px=widths(f)[0], hip_width_px=widths(f)[1])
            for f in data['frames']]
    if not rows or any(not math.isfinite(r['timestamp_seconds']) for r in rows):
        raise ValueError('Finite, nonempty tracking timestamps required')
    if any(b['timestamp_seconds'] <= a['timestamp_seconds'] for a, b in zip(rows, rows[1:])):
        raise ValueError('Tracking timestamps must be strictly increasing')
    refs = {}
    for part in ('shoulder', 'hip'):
        key = part + '_width_px'
        values = [r[key] for r in rows if r[key] is not None]
        refs[part] = float(np.quantile(values, .95)) if values else None
    # Filter only within contiguous blocks of observations valid for both pairs.
    blocks, block = [], []
    for i, row in enumerate(rows):
        good = row['shoulder_width_px'] is not None and row['hip_width_px'] is not None
        if not good or (block and row['timestamp_seconds'] - rows[block[-1]]['timestamp_seconds'] > settings.max_gap_seconds):
            if block:
                blocks.append(block)
            block = []
        if good:
            block.append(i)
    if block:
        blocks.append(block)
    # Keep a recording-wide constant, but retain brief supported broad views.
    # Contiguous paired observations and a median over >=120 ms reject isolated
    # spikes; never calibrate from a window spanning missing or uncertain poses.
    for block in blocks:
        times=np.array([rows[i]['timestamp_seconds'] for i in block])
        values=np.array([[rows[i][p+'_width_px'] for p in ('shoulder','hip')] for i in block])
        for j,t in enumerate(times):
            end=int(np.searchsorted(times,t+settings.reference_window_seconds+1e-9,side='right'))
            if end-j<3 or times[end-1]-t+1e-9<settings.reference_window_seconds*.8:
                continue
            medians=np.median(values[j:end],axis=0)
            for k,part in enumerate(('shoulder','hip')):
                refs[part]=max(refs[part],float(medians[k]))
    for row in rows:
        row.update(shoulder_filtered_px=None, hip_filtered_px=None,
                   shoulder_fraction=None, hip_fraction=None)
    for block in blocks:
        times = np.array([rows[i]['timestamp_seconds'] for i in block])
        for part in ('shoulder', 'hip'):
            values = np.array([rows[i][part + '_width_px'] for i in block])
            for j, i in enumerate(block):
                nearby = abs(times - times[j]) <= settings.filter_radius_seconds
                value = float(np.median(values[nearby]))
                rows[i][part + '_filtered_px'] = value
                rows[i][part + '_fraction'] = value / refs[part] if refs[part] and refs[part] > 0 else None
    return rows, refs


def decode(rows, refs, skill, settings=WidthSettings()):
    start, end = skill['visible_start_seconds'], skill['visible_end_seconds']
    boundary_method = 'pose_contact_proxy'
    rotation=skill.get('rotation',{})
    turns=rotation.get('somersault_count')
    if turns is None:turns=rotation.get('candidate_somersault_count')
    if turns is not None and turns>=.25:
        start=rotation.get('window_start_seconds',start)
        end=rotation.get('window_end_seconds',end)
        boundary_method='pose_rotation_contact_window'
    landing = skill.get('landing_contact') or {}
    touch = landing.get('timestamp_seconds')
    if isinstance(touch, (int, float)) and math.isfinite(touch) and start < touch <= end:
        end = touch
        boundary_method = 'estimated_bed_touch'
    selected = [dict(r) for r in rows if start <= r['timestamp_seconds'] <= end]
    reasons = []
    events, runs = [], []
    if any(r.get('track_state') == 'lost' for r in selected):
        reasons.append('athlete_tracking_lost')
    for part, minimum in (('shoulder', settings.minimum_shoulder_reference_px), ('hip', settings.minimum_hip_reference_px)):
        if refs[part] is None or refs[part] < minimum:
            reasons.append(part + '_reference_too_small')
    if skill.get('start_clipped') or skill.get('end_clipped'):
        reasons.append('partial_flight')
    if len(selected) < 3:
        reasons.append('insufficient_frames')
    valid_times = []
    current, run = None, []
    for row in selected:
        s, h = row['shoulder_fraction'], row['hip_fraction']
        if s is None or h is None:
            state = 'missing'
            reasons.append('missing_torso_observation')
        elif max(s, h) <= settings.narrow_fraction:
            state = 'narrow'
        elif min(s, h) >= settings.broad_fraction:
            state = 'broad'
        elif (s <= settings.narrow_fraction and h >= settings.broad_fraction) or (h <= settings.narrow_fraction and s >= settings.broad_fraction):
            state = 'disagreement'
        else:
            state = 'transition'
        row['width_state'] = state
        if state != 'missing':
            valid_times.append(row['timestamp_seconds'])
        if current != state:
            if run:
                runs.append((current, run))
            current, run = state, []
        run.append(row)
    if run:
        runs.append((current, run))
    if selected:
        if selected[0]['timestamp_seconds'] - start > settings.max_gap_seconds or end - selected[-1]['timestamp_seconds'] > settings.max_gap_seconds:
            reasons.append('unsupported_boundary')
    if any(b - a > settings.max_gap_seconds for a, b in zip(valid_times, valid_times[1:])):
        reasons.append('unsupported_torso_gap')
    stable = []
    for state, run in runs:
        duration = run[-1]['timestamp_seconds'] - run[0]['timestamp_seconds']
        if len(run) >= 2 and duration + 1e-9 >= settings.stable_seconds:
            if state == 'disagreement':
                reasons.append('shoulder_hip_disagreement')
            if state in ('narrow', 'broad'):
                stable.append((state, run))
    phase, anchor, broad = 'unarmed', None, None
    for state, run in stable:
        if state == 'narrow':
            if phase == 'broad':
                peak = max(broad, key=lambda r: min(r['shoulder_fraction'], r['hip_fraction']))
                events.append(dict(start_frame=anchor[-1]['frame_index'],
                                   broad_frame=peak['frame_index'],
                                   end_frame=run[0]['frame_index'],
                                   broad_seconds=peak['timestamp_seconds'], candidate_half_turns=1,
                                   completion_method='strict_narrow_state'))
            phase, anchor = 'narrow', run
        elif phase == 'narrow':
            phase, broad = 'broad', run
        elif phase == 'broad':
            # Brief threshold chatter must not discard the rest of a broad phase.
            broad = broad + run
    finish_evidence = None
    # At measured bed touch, projection can leave a residual hip/shoulder width.
    # Complete only the final pending passage, after both widths have fallen
    # substantially from a supported broad phase. Internal states remain strict.
    if phase == 'broad' and boundary_method == 'estimated_bed_touch' and not reasons:
        tail = []
        for row in reversed(selected):
            values = [row[p + '_fraction'] for p in ('shoulder', 'hip')]
            if (row['timestamp_seconds'] < broad[-1]['timestamp_seconds']
                    or any(v is None or v > settings.finish_fraction for v in values)
                    or (tail and tail[-1]['timestamp_seconds'] - row['timestamp_seconds'] > settings.max_gap_seconds)):
                break
            tail.append(row)
        tail.reverse()
        if len(tail) >= 2 and tail[-1]['timestamp_seconds'] - tail[0]['timestamp_seconds'] + 1e-9 >= settings.stable_seconds:
            drops = {p: max(r[p + '_fraction'] for r in broad)
                        - max(r[p + '_fraction'] for r in tail) for p in ('shoulder', 'hip')}
            falling = all(tail[-1][p + '_fraction'] <= tail[0][p + '_fraction'] for p in ('shoulder', 'hip'))
            if falling and min(drops.values()) >= settings.finish_minimum_drop:
                peak = max(broad, key=lambda r: min(r['shoulder_fraction'], r['hip_fraction']))
                finish_evidence = dict(method='paired_narrowing_at_bed_touch',
                    start_seconds=tail[0]['timestamp_seconds'], end_seconds=tail[-1]['timestamp_seconds'],
                    drop_from_broad=drops)
                events.append(dict(start_frame=anchor[-1]['frame_index'], broad_frame=peak['frame_index'],
                    end_frame=tail[0]['frame_index'], broad_seconds=peak['timestamp_seconds'],
                    candidate_half_turns=1, completion_method='paired_narrowing_at_bed_touch'))
                phase = 'narrow'
    # Both boundary regions must be narrow. Do not hide incomplete passages.
    edge = max(.12, settings.stable_seconds * 2)
    if not stable or stable[0][0] != 'narrow' or stable[0][1][0]['timestamp_seconds'] > start + edge:
        reasons.append('side_on_start_not_established')
    if finish_evidence is None and (not stable or stable[-1][0] != 'narrow' or stable[-1][1][-1]['timestamp_seconds'] < end - edge):
        reasons.append('side_on_finish_not_established')
    if phase == 'broad':
        reasons.append('incomplete_passage')
    events=split_paired_passages(selected,events,settings)
    zero=zero_twist_evidence(selected,refs,skill,start,end,settings) if not events else None
    supported_zero=zero is not None and zero['supported']
    if supported_zero:
        reasons=[]
    review_reasons=[]
    if ('missing_torso_observation' in reasons and valid_times
            and valid_times[0]-start<=settings.max_gap_seconds
            and end-valid_times[-1]<=settings.max_gap_seconds
            and 'unsupported_torso_gap' not in reasons):
        reasons=[r for r in reasons if r!='missing_torso_observation']
        review_reasons.append('short_bounded_torso_gaps')
    reasons = sorted(set(reasons))
    return dict(method='shoulder_hip_width_passages_v1', status='supported_conditional' if supported_zero else 'unknown' if reasons else 'tentative',
                decoder_version=9, start_seconds=start, end_seconds=end,
                zero_twist_evidence=zero,
                finish_evidence=finish_evidence,
                end_boundary_method=boundary_method,
                end_boundary_status=landing.get('status') if boundary_method == 'estimated_bed_touch' else 'needs_review',
                count=0. if supported_zero else None, candidate_count=None if reasons else len(events) * .5,
                completed_passages=len(events), events=events, reasons=reasons, review_reasons=review_reasons,
                assumptions=['fixed_side_on_camera', 'side_on_departure_and_landing',
                             'continued_twisting_without_reversal', 'sustained_observed_reference_approximates_broad_width',
                             'sustained_paired_width_minima_separate_half_turns'],
                endpoint_facing_check='not_implemented_requires_somersault_aware_review',
                references_px=refs, settings=asdict(settings), raw_evidence=selected)


def attach(data, analysis, settings=WidthSettings()):
    rows, refs = measure(data, settings)
    for skill in analysis['skills']:
        # Phase recovery refines the somersault display independently. Keep the
        # established twist decoder's angle input until that dependency is
        # separately validated, so a count repair cannot change twist passages.
        twist_skill = skill
        rotation = skill.get('rotation', {})
        if 'angle_candidate_somersault_count' in rotation:
            twist_rotation = {**rotation,
                'candidate_somersault_count': rotation['angle_candidate_somersault_count'],
                'candidate_somersault_quarters': rotation.get('angle_candidate_somersault_quarters')}
            twist_skill = {**skill, 'rotation': twist_rotation}
        skill['twist'] = decode(rows, refs, twist_skill, settings)
        twist=skill['twist']
        somersault=somersault_candidate(data,rows,twist_skill,twist,settings)
        if somersault is not None:
            twist.update(status='tentative',candidate_count=somersault['candidate_count'],
                events=somersault['events'],detected_phases=len(somersault['events']),reasons=[],
                review_reasons=somersault['review_reasons'],
                endpoint_facing_check=somersault['facing_check'],
                passage_method='paired_widths_with_body_relative_facing')
        candidate=jump_candidate(data,rows,refs,twist_skill,twist,settings)
        if candidate is not None:
            twist.update(status='tentative',candidate_count=candidate['candidate_count'],
                events=candidate['events'],detected_phases=len(candidate['events']),reasons=[],
                review_reasons=candidate['review_reasons'],
                endpoint_facing_check=candidate['facing_check'],
                passage_method='upright_paired_width_phases_with_facing',
                finish_evidence=dict(method='landing_facing_parity',note=candidate['finish_note']),
                finish_completion_status='needs_review')
        # Present an explicitly experimental identity alongside the candidate;
        # leave supported count and confirmed/predicted skill identity unchanged.
        jump=(skill.get('rotation',{}).get('somersault_count')==0
              and skill.get('takeoff_position')=='feet' and skill.get('landing_position')=='feet')
        twist['candidate_skill_identity']=({.5:'Half twist jump',1.:'Full twist jump',1.5:'1½ twist jump',
                                            2.:'Double twist jump',2.5:'2½ twist jump',3.:'Triple twist jump'}.get(twist['candidate_count'])
                                            if jump and twist['status']=='tentative' else None)
    analysis['twist_experiment'] = dict(method='shoulder_hip_width_passages_v1',
        decoder_version=9,
        validated=False, note='Zero twists supported conditionally by sustained narrow torso evidence; positive totals remain candidates. Twist distribution is unresolved.')
    from .difficulty import attach_difficulty
    return attach_difficulty(analysis)
