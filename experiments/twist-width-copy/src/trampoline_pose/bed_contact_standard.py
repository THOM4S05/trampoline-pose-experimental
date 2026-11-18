"""Native-frame bed deformation evidence for contact and release timing.

Pose contacts only locate search windows and the trampoline area. Timing comes
from the video: an unloaded-bed reference is registered against each source
frame using background features, then bed appearance is measured on either
side of the athlete. A flat-to-curved change point estimates deformation onset.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import cv2
import numpy as np

from .output import sha256
from .skill_identification import centre
from .video import decode

VERSION = 3


def deformation_onset(times, signal, proxy):
    """Fit a continuous baseline + quadratic onset, retaining an uncertainty interval."""
    t, y = np.asarray(times), np.asarray(signal)
    keep = (t >= proxy - .32) & (t <= proxy + .25) & np.isfinite(y)
    t, y = t[keep], y[keep]
    baseline = y[t < proxy - .12]
    if len(t) < 12 or len(baseline) < 4 or np.max(np.diff(t)) > .06:
        return None
    base = float(np.median(baseline))
    noise = max(.15, float(np.median(abs(baseline - base))) * 1.4826)
    amplitude = float(np.max(y) - base)
    if amplitude < max(2., noise * 8):
        return None
    crossing = np.flatnonzero((t >= proxy - .1) & (y > base + amplitude * .45))
    if not len(crossing):
        return None
    t, y = t[:crossing[0] + 1], y[:crossing[0] + 1]
    step = min(.002, float(np.median(np.diff(t))) / 2)
    candidates = []
    for stamp in np.arange(max(t[0] + .06, proxy - .2), min(proxy + .08, t[-1] - .015), step):
        design = np.column_stack([np.ones(len(t)), t - t[0], np.maximum(0, t - stamp) ** 2])
        coef = np.linalg.lstsq(design, y, rcond=None)[0]
        if coef[2] <= 0 or abs(coef[1]) > amplitude * 2:
            continue
        error = float(np.mean((design @ coef - y) ** 2))
        candidates.append((error, float(stamp)))
    if not candidates:
        return None
    error, stamp = min(candidates)
    if error ** .5 > max(noise * 3, amplitude * .1):
        return None
    plausible = [s for e, s in candidates if e <= error + noise ** 2]
    period = float(np.median(np.diff(t)))
    interval = [min(plausible) - period, max(plausible) + period]
    if interval[1] - interval[0] > .10:
        return None
    return dict(timestamp_seconds=round(stamp, 6),
                interval_seconds=[round(v, 6) for v in interval],
                fit_error=round(error ** .5, 4), signal_change=round(amplitude, 4))


def bed_region(data, contacts):
    """Choose the visible bed band from the first supported complete approach."""
    frames = data['frames']
    for contact in contacts:
        stamp = contact['timestamp_seconds']
        if stamp - frames[0]['timestamp_seconds'] < .45:
            continue
        samples = []
        for frame in frames:
            if stamp - .1 <= frame['timestamp_seconds'] <= stamp:
                ankle, hip, shoulder = (centre(frame, part) for part in ('ankle', 'hip', 'shoulder'))
                row = [*ankle, np.linalg.norm(shoulder - hip)]
                if np.isfinite(row).all() and row[2] > 15:
                    samples.append(row)
        if len(samples) >= 3:
            x, y, torso = np.median(samples, axis=0)
            w, h = data['source']['display_width'], data['source']['display_height']
            airborne = [(float(centre(f, 'hip')[1]), f['timestamp_seconds']) for f in frames
                        if stamp-.9 <= f['timestamp_seconds'] <= stamp-.12
                        and np.isfinite(centre(f, 'hip')).all()]
            if len(airborne) < 3:
                continue
            # Select observed maximum clearance. A fixed time offset can land
            # on the previous bounce, especially during preparation jumps.
            reference_seconds = min(airborne)[1]
            return dict(roi=[max(0, int(x - 5 * torso)), max(0, int(y - .55 * torso)),
                             min(w, int(x + 5 * torso)), min(h, int(y + .6 * torso))],
                        reference_seconds=reference_seconds,
                        athlete_x=float(x), torso=float(torso))
    return None


def measure_bed(data, result, source):
    contacts = result['contacts']
    region = bed_region(data, contacts)
    if region is None:
        return dict(status='unavailable', reason='no_supported_bed_region', events=[])
    scale = min(1., 800 / max(data['source']['display_width'], data['source']['display_height']))
    def gray(image):
        return cv2.cvtColor(cv2.resize(image, None, fx=scale, fy=scale), cv2.COLOR_BGR2GRAY)
    for timing, image in decode(source, data['source']):
        if timing['timestamp_seconds'] >= region['reference_seconds']:
            reference = gray(image)
            break
    x1, y1, x2, y2 = [round(v * scale) for v in region['roi']]
    mask = np.full_like(reference, 255)
    mask[y1:] = 0
    cx, radius = region['athlete_x'] * scale, region['torso'] * scale * 1.5
    mask[:, max(0, round(cx-radius)):round(cx+radius)] = 0
    corners = cv2.goodFeaturesToTrack(reference, 100, .01, 8, mask=mask)
    if corners is None or len(corners) < 8 or y2-y1 < 8:
        return dict(status='unavailable', reason='insufficient_background_or_bed', events=[])
    times = np.array([f['timestamp_seconds'] for f in data['frames']])
    signals = [[] for _ in contacts]
    exclusions = []
    for contact in contacts:
        nearby = [f for f in data['frames'] if abs(f['timestamp_seconds'] - contact['timestamp_seconds']) < .12]
        xs = [centre(f, 'hip')[0] for f in nearby]
        finite = [v for v in xs if np.isfinite(v)]
        center = float(np.median(finite)) if finite else region['athlete_x']
        exclusions.append((round((center-region['torso']) * scale), round((center+region['torso']) * scale)))
    for timing, image in decode(source, data['source']):
        stamp, index = timing['timestamp_seconds'], timing['frame_index']
        active = [i for i, c in enumerate(contacts) if c['timestamp_seconds']-.4 <= stamp <= c['timestamp_seconds']+.75]
        if not active:
            continue
        if index >= len(times) or abs(stamp - times[index]) > 1e-6:
            raise ValueError('Video and pose frame timestamps disagree')
        current = gray(image)
        dest, status, error = cv2.calcOpticalFlowPyrLK(reference, current, corners, None, winSize=(25,25), maxLevel=3)
        good = (status[:,0] > 0) & (error[:,0] < 20)
        delta = (dest-corners)[:,0][good]
        shift = np.median(delta,axis=0) if len(delta) else np.array([np.nan,np.nan])
        transform, inliers = (cv2.estimateAffinePartial2D(corners[good],dest[good],method=cv2.RANSAC,
                              ransacReprojThreshold=1.5) if good.sum() >= 8 else (None,None))
        if len(delta) >= 8 and np.median(np.linalg.norm(delta-shift,axis=1)) < 1.5:
            transform = np.float32([[1,0,shift[0]],[0,1,shift[1]]])
            inliers = np.ones((len(delta),1))
        reliable = (transform is not None and inliers.sum() >= 8 and inliers.mean() >= .6
                    and .9 <= np.linalg.norm(transform[:,0]) <= 1.1)
        if reliable:
            aligned = cv2.warpAffine(current, transform, (reference.shape[1],reference.shape[0]),
                                     flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
            diff = cv2.absdiff(aligned, reference)
        for i in active:
            left, right = exclusions[i]
            values = []
            if reliable:
                # Keep independent strips: agreement rejects an athlete or
                # another moving object accidentally included on one side.
                for lo, hi in ((x1, min(x2,left)), (max(x1,right),x2)):
                    patch = diff[y1:y2,max(0,lo):max(0,hi)]
                    values.append(float(np.mean(patch)) if patch.size >= 100 else None)
            else:
                values = [None, None]
            signals[i].append([stamp, *values])
    events = []
    for contact, rows in zip(contacts, signals):
        values = np.array([[np.nan if v is None else v for v in row] for row in rows])
        event = dict(proxy_seconds=contact['timestamp_seconds'], landing=None, release=None, samples=rows)
        if len(values):
            for edge, offset in (('landing', 0), ('release', .35)):
                found = []
                for column in (1,2):
                    t, y = values[:,0], values[:,column]
                    if edge == 'release':
                        t, y = -t[::-1], y[::-1]
                    proxy = contact['timestamp_seconds'] + offset
                    detection = deformation_onset(t, y, -proxy if edge == 'release' else proxy)
                    if detection:
                        if edge == 'release':
                            detection['timestamp_seconds'] *= -1
                            detection['interval_seconds'] = [-v for v in detection['interval_seconds'][::-1]]
                        found.append(detection)
                if not found:
                    continue
                if len(found) == 2 and abs(found[0]['timestamp_seconds']-found[1]['timestamp_seconds']) > .035:
                    continue
                stamp = float(np.mean([f['timestamp_seconds'] for f in found]))
                frame = int(np.argmin(abs(times-stamp)))
                lo = max(float(times[0]), min(f['interval_seconds'][0] for f in found))
                hi = min(float(times[-1]), max(f['interval_seconds'][1] for f in found))
                event[edge] = dict(timestamp_seconds=float(times[frame]), frame_index=data['frames'][frame]['frame_index'],
                                   interval_seconds=[lo,hi], method='visible_bed_deformation_onset' if edge == 'landing' else 'visible_bed_recovery',
                                   supported_sides=len(found), status='video_estimate_needs_review')
        events.append(event)
    return dict(status='measured', region=region, events=events)


def add_bed_contact_times(data, result, source, cache_path=None):
    """Replace pose-velocity timing with source-video bed evidence."""
    digest = sha256(source)
    if digest != data['source'].get('sha256'):
        raise ValueError('Bed timing source does not match pose video')
    signature = [c['timestamp_seconds'] for c in result['contacts']]
    pose_digest = hashlib.sha256(json.dumps(data.get('frames', []),sort_keys=True,allow_nan=False).encode()).hexdigest()
    cached = None
    if cache_path and Path(cache_path).is_file():
        cached = json.loads(Path(cache_path).read_text(encoding='utf-8'))
        if cached.get('version') != VERSION or cached.get('source_sha256') != digest or cached.get('contacts') != signature or cached.get('pose_sha256') != pose_digest:
            cached = None
    if cached is None:
        cached = dict(version=VERSION, source_sha256=digest, pose_sha256=pose_digest, contacts=signature, **measure_bed(data,result,source))
        if cache_path:
            pending = Path(cache_path).with_suffix('.pending.json')
            pending.write_text(json.dumps(cached, indent=2, allow_nan=False), encoding='utf-8')
            pending.replace(cache_path)
    by_contact = {event['proxy_seconds']:event for event in cached['events']}
    for contact in result['contacts']:
        contact['bed_contact'] = by_contact.get(contact['timestamp_seconds'], {}).get('landing')
    for skill in result['skills']:
        departure = by_contact.get(skill.get('start_seconds'), {}).get('release')
        arrival = by_contact.get(skill.get('end_seconds'), {}).get('landing')
        skill['landing_contact'] = arrival
        evidence = dict(seconds=None, takeoff_seconds=None, landing_seconds=arrival['timestamp_seconds'] if arrival else None,
                        method='visible_bed_deformation', status='unavailable', reasons=[])
        if departure:
            evidence['takeoff_seconds'] = departure['timestamp_seconds']
            evidence['takeoff_interval_seconds'] = departure['interval_seconds']
        if arrival:
            evidence['landing_interval_seconds'] = arrival['interval_seconds']
        if departure and arrival and .15 < arrival['timestamp_seconds']-departure['timestamp_seconds'] < 3:
            evidence.update(seconds=round(arrival['timestamp_seconds']-departure['timestamp_seconds'],6), status='estimated_needs_review')
            evidence['interval_seconds'] = [round(arrival['interval_seconds'][0]-departure['interval_seconds'][1],6),
                                            round(arrival['interval_seconds'][1]-departure['interval_seconds'][0],6)]
        else:
            evidence['reasons'] = ['partial_clip' if skill.get('start_clipped') or skill.get('end_clipped') else 'bed_contact_or_release_unresolved']
        skill['time_of_flight'] = evidence
        skill['time_of_flight_seconds'] = evidence['seconds']
    result['bed_timing'] = {k:v for k,v in cached.items() if k != 'events'}
    return result
