"""Native-frame bed deformation evidence for contact and release timing.

Pose evidence initializes the bed area; paired video motion can discover
contacts missed by the pose proposals. Timing comes from background-registered
bed appearance on either side of the athlete. Local references handle camera
pans, and stopping landings retain wider timing intervals when necessary.
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
from scipy.ndimage import gaussian_filter1d,percentile_filter
from scipy.signal import find_peaks

VERSION = 4


def deformation_onset(times, signal, proxy, max_uncertainty_seconds=.10):
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
    if interval[1] - interval[0] > max_uncertainty_seconds:
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
            # Approach-frame ankles can still be far above the mesh during a
            # fast descent. Check against the routine's lower ankle envelope,
            # rather than treating that early approach height as the bed.
            ankle_ys=[centre(f,'ankle')[1] for f in frames if np.isfinite(centre(f,'ankle')).all()]
            method='supported_approach'
            horizontal_torso=torso
            top,bottom=y-.55*torso,y+.6*torso
            if len(ankle_ys)>=12:
                floor=float(np.quantile(ankle_ys,.92))
                if floor-y>torso:
                    lengths=[np.linalg.norm(centre(f,'shoulder')-centre(f,'hip')) for f in frames]
                    lengths=[v for v in lengths if np.isfinite(v) and v>15]
                    torso=float(np.median(lengths)) if lengths else torso
                    top,bottom=floor-.6*torso,floor+torso
                    method='lower_ankle_envelope_checked_by_video'
            return dict(roi=[max(0, int(x - 5 * horizontal_torso)), max(0, int(top)),
                             min(w, int(x + 5 * horizontal_torso)), min(h, int(bottom))],
                        reference_seconds=reference_seconds,
                        athlete_x=float(x), torso=float(torso),method=method)
    return None


def discover_contacts(rows,data,region):
    """Search paired bed deformation across the clip, independently of pose peaks."""
    values=np.array([[np.nan if v is None else v for v in row] for row in rows])
    if len(values)<12:return []
    times=values[:,0]
    period=float(np.median(np.diff(times)))
    good=np.flatnonzero(np.isfinite(values[:,1:]).all(axis=1))
    blocks=np.split(good,np.flatnonzero((np.diff(good)>1)|(np.diff(times[good])>max(.06,period*1.5)))+1)
    events=[]
    for block in blocks:
        if len(block)<12:continue
        signal=gaussian_filter1d(values[block,1:],max(.025/period,.25),axis=0)
        window=max(3,int(1.35/period)|1)
        floor=percentile_filter(signal,percentile=15,size=(window,1),mode='nearest')
        paired=np.maximum(0,signal-floor).min(axis=1)
        peaks,_=find_peaks(paired,prominence=2.,distance=max(1,int(.6/period)))
        for peak in peaks:
            index=int(block[peak]);stamp=float(times[index])
            # Reject unrelated motion while the athlete is high above the bed.
            nearby=[f for f in data['frames'] if abs(f['timestamp_seconds']-stamp)<=.15]
            hips=[centre(f,'hip')[1] for f in nearby]
            hips=[v for v in hips if np.isfinite(v)]
            if not hips or max(hips)<region['roi'][1]-2.5*region['torso']:continue
            options=[[],[]]
            for column in (1,2):
                for offset in (0.,-.1,-.15):
                    detection=deformation_onset(times,values[:,column],stamp+offset)
                    if detection:options[column-1].append(detection)
            pairs=[(a,b) for a in options[0] for b in options[1]
                   if abs(a['timestamp_seconds']-b['timestamp_seconds'])<=.035]
            if not pairs:
                events.append(dict(proxy_seconds=stamp,landing=None,release=None,
                    compression_peak_seconds=stamp,discovered_from='paired_bed_motion'))
                continue
            pair=min(pairs,key=lambda p:sum(x['fit_error']/max(x['signal_change'],1) for x in p))
            onset=float(np.mean([v['timestamp_seconds'] for v in pair]))
            frame=int(np.argmin(abs(times-onset)))
            landing=dict(timestamp_seconds=float(times[frame]),frame_index=data['frames'][frame]['frame_index'],
                interval_seconds=[max(float(times[0]),min(x['interval_seconds'][0] for x in pair)),
                                  min(float(times[-1]),max(x['interval_seconds'][1] for x in pair))],
                method='paired_visible_bed_deformation_onset',supported_sides=2,status='video_estimate_needs_review')
            releases=[]
            for column in (1,2):
                release=deformation_onset(-times[::-1],values[::-1,column],-(stamp+.25))
                if release:
                    release['timestamp_seconds']*=-1
                    release['interval_seconds']=[-v for v in release['interval_seconds'][::-1]]
                    releases.append(release)
            release=None
            if releases and (len(releases)==1 or abs(releases[0]['timestamp_seconds']-releases[1]['timestamp_seconds'])<=.035):
                rs=float(np.mean([v['timestamp_seconds'] for v in releases]));ri=int(np.argmin(abs(times-rs)))
                if onset+.08<rs<stamp+.5:
                    release=dict(timestamp_seconds=float(times[ri]),frame_index=data['frames'][ri]['frame_index'],
                        interval_seconds=[min(x['interval_seconds'][0] for x in releases),max(x['interval_seconds'][1] for x in releases)],
                        method='visible_bed_recovery',supported_sides=len(releases),status='video_estimate_needs_review')
            events.append(dict(proxy_seconds=landing['timestamp_seconds'],landing=landing,release=release,
                compression_peak_seconds=stamp,discovered_from='paired_bed_motion'))
    return events


def local_bed_retry(data,source,region,events):
    """Remeasure unresolved contacts against a nearby unloaded-bed view.

    Long clips can pan beyond the optical-flow range of the original reference.
    A fresh pre-contact reference preserves the registration and timing checks.
    """
    plans=[]
    for event in events:
        if event.get('landing') is not None:continue
        proxy=event['proxy_seconds']
        airborne=[(float(centre(f,'hip')[1]),f['timestamp_seconds']) for f in data['frames']
                  if proxy-.9<=f['timestamp_seconds']<=proxy-.25 and np.isfinite(centre(f,'hip')).all()]
        if len(airborne)<3:continue
        height,stamp=min(airborne)
        reference_frame=min(data['frames'],key=lambda f:abs(f['timestamp_seconds']-stamp))
        ankle=centre(reference_frame,'ankle')
        feet_clear=np.isfinite(ankle).all() and ankle[1]<region['roi'][1]+.1*region['torso']
        if height>region['roi'][1]-2.5*region['torso'] and not feet_clear:continue
        plans.append(dict(event=event,reference_seconds=stamp,samples=[],reference=None,corners=None))
    if not plans:return
    scale=min(1.,800/max(data['source']['display_width'],data['source']['display_height']))
    x1,y1,x2,y2=[round(v*scale) for v in region['roi']]
    for timing,image in decode(source,data['source'],len(data['frames'])):
        stamp,index=timing['timestamp_seconds'],timing['frame_index']
        active=[p for p in plans if p['reference_seconds']<=stamp<=p['event']['proxy_seconds']+.75]
        if not active:continue
        current=cv2.cvtColor(cv2.resize(image,None,fx=scale,fy=scale),cv2.COLOR_BGR2GRAY)
        frame=data['frames'][index];hip=centre(frame,'hip');box=frame.get('bbox_xyxy')
        center=float(hip[0]) if np.isfinite(hip).all() else (box[0]+box[2])/2 if box is not None else region['athlete_x']
        for plan in active:
            if plan['reference'] is None:
                plan['reference']=current.copy()
                mask=np.full_like(current,255);mask[y1:]=0
                lo,hi=round((center-1.5*region['torso'])*scale),round((center+1.5*region['torso'])*scale)
                mask[:,max(0,lo):min(current.shape[1],hi)]=0
                plan['corners']=cv2.goodFeaturesToTrack(current,100,.01,8,mask=mask)
            corners=plan['corners'];pair=[None,None]
            if corners is not None and len(corners)>=8 and frame.get('diagnostics',{}).get('reason')!='scene_cut_requires_new_seed':
                dest,status,error=cv2.calcOpticalFlowPyrLK(plan['reference'],current,corners,None,winSize=(25,25),maxLevel=3)
                good=(status[:,0]>0)&(error[:,0]<20)
                transform,inliers=(cv2.estimateAffinePartial2D(corners[good],dest[good],method=cv2.RANSAC,ransacReprojThreshold=1.5) if good.sum()>=8 else (None,None))
                delta=(dest-corners)[:,0][good]
                shift=np.median(delta,axis=0) if len(delta) else np.array([np.nan,np.nan])
                if len(delta)>=8 and np.median(np.linalg.norm(delta-shift,axis=1))<1.5:
                    transform=np.float32([[1,0,shift[0]],[0,1,shift[1]]]);inliers=np.ones((len(delta),1))
                if transform is not None and inliers.sum()>=8 and inliers.mean()>=.6 and .9<=np.linalg.norm(transform[:,0])<=1.1:
                    aligned=cv2.warpAffine(current,transform,(current.shape[1],current.shape[0]),flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP)
                    diff=cv2.absdiff(aligned,plan['reference']);left,right=round((center-region['torso'])*scale),round((center+region['torso'])*scale)
                    pair=[]
                    for lo,hi in ((x1,min(x2,left)),(max(x1,right),x2)):
                        patch=diff[y1:y2,max(0,lo):max(0,hi)]
                        pair.append(float(np.mean(patch)) if patch.size>=100 else None)
            plan['samples'].append([stamp,*pair])
    times=np.array([f['timestamp_seconds'] for f in data['frames']])
    for plan in plans:
        plan['event']['local_reference_seconds']=plan['reference_seconds']
        plan['event']['local_samples']=plan['samples']
        values=np.array([[np.nan if v is None else v for v in row] for row in plan['samples']])
        if len(values)<12:continue
        proxy=plan['event']['proxy_seconds'];options=[[],[]]
        for column in (1,2):
            for offset in (0.,-.1,-.15):
                found=deformation_onset(values[:,0],values[:,column],proxy+offset)
                if found:options[column-1].append(found)
        pairs=[(a,b) for a in options[0] for b in options[1] if abs(a['timestamp_seconds']-b['timestamp_seconds'])<=.035]
        if not pairs and plan['event'].get('discovered_from'):
            # A low-rate stopping landing can have a wider timing interval.
            # Retain that uncertainty explicitly; still require BOTH sides.
            wider=[[],[]]
            for column in (1,2):
                for offset in (0.,-.1,-.15):
                    found=deformation_onset(values[:,0],values[:,column],proxy+offset,max_uncertainty_seconds=.20)
                    if found:wider[column-1].append(found)
            pairs=[(a,b) for a in wider[0] for b in wider[1] if abs(a['timestamp_seconds']-b['timestamp_seconds'])<=.035]
        if pairs:
            pair=min(pairs,key=lambda p:sum(x['fit_error']/max(x['signal_change'],1) for x in p))
        elif not plan['event'].get('discovered_from') and bool(options[0])!=bool(options[1]):
            # A pose-proposed contact may use one reliable visible side, as in
            # the original estimator. New independent contacts still need both.
            pair=[min(options[0] or options[1],key=lambda x:x['fit_error']/max(x['signal_change'],1))]
        else:continue
        stamp=float(np.mean([v['timestamp_seconds'] for v in pair]));index=int(np.argmin(abs(times-stamp)))
        landing=dict(timestamp_seconds=float(times[index]),frame_index=data['frames'][index]['frame_index'],
            interval_seconds=[min(v['interval_seconds'][0] for v in pair),max(v['interval_seconds'][1] for v in pair)],
            method='paired_local_bed_deformation_onset' if len(pair)==2 else 'local_visible_bed_deformation_onset',
            supported_sides=len(pair),status='video_estimate_needs_review',
            reference_seconds=plan['reference_seconds'])
        if landing['interval_seconds'][1]-landing['interval_seconds'][0]>.10:
            landing['timing_quality']='wide_review_interval'
        plan['event']['landing']=landing
        if plan['event'].get('discovered_from'):
            plan['event']['proxy_seconds']=landing['timestamp_seconds']


def measure_bed(data, result, source):
    contacts = result['contacts']
    region = bed_region(data, contacts)
    if region is None:
        return dict(status='unavailable', reason='no_supported_bed_region', events=[])
    scale = min(1., 800 / max(data['source']['display_width'], data['source']['display_height']))
    def gray(image):
        return cv2.cvtColor(cv2.resize(image, None, fx=scale, fy=scale), cv2.COLOR_BGR2GRAY)
    for timing, image in decode(source, data['source'], len(data['frames'])):
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
    global_signal=[]
    exclusions = []
    for contact in contacts:
        nearby = [f for f in data['frames'] if abs(f['timestamp_seconds'] - contact['timestamp_seconds']) < .12]
        xs = [centre(f, 'hip')[0] for f in nearby]
        finite = [v for v in xs if np.isfinite(v)]
        center = float(np.median(finite)) if finite else region['athlete_x']
        exclusions.append((round((center-region['torso']) * scale), round((center+region['torso']) * scale)))
    for timing, image in decode(source, data['source'], len(data['frames'])):
        stamp, index = timing['timestamp_seconds'], timing['frame_index']
        active = [i for i, c in enumerate(contacts) if c['timestamp_seconds']-.4 <= stamp <= c['timestamp_seconds']+.75]
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
        # A dynamic athlete exclusion also works when a landing was absent
        # from the pose-proxy list. Do not scan past a scene-cut lockout.
        frame=data['frames'][index]
        if reliable and frame.get('diagnostics',{}).get('reason')!='scene_cut_requires_new_seed':
            hip=centre(frame,'hip');box=frame.get('bbox_xyxy')
            center=float(hip[0]) if np.isfinite(hip).all() else (box[0]+box[2])/2 if box is not None else region['athlete_x']
            left,right=round((center-region['torso'])*scale),round((center+region['torso'])*scale)
            pair=[]
            for lo,hi in ((x1,min(x2,left)),(max(x1,right),x2)):
                patch=diff[y1:y2,max(0,lo):max(0,hi)]
                pair.append(float(np.mean(patch)) if patch.size>=100 else None)
        else:pair=[None,None]
        global_signal.append([stamp,*pair])
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
    discovered=discover_contacts(global_signal,data,region)
    local_bed_retry(data,source,region,[*events,*discovered])
    # Independent video detections can refine an existing rough proxy too.
    for event in events:
        matches=[e for e in discovered if e.get('landing') is not None and abs(e['proxy_seconds']-event['proxy_seconds'])<=.3]
        if matches:
            match=min(matches,key=lambda e:abs(e['proxy_seconds']-event['proxy_seconds']))
            if event['landing'] is None:event['landing']=match['landing']
            if event['release'] is None:event['release']=match['release']
    discovered=[e for e in discovered if e.get('landing') is not None]
    return dict(status='measured', region=region, events=events,
                discovered_contacts=discovered,global_samples=global_signal)


def add_bed_contact_times(data, result, source, cache_path=None, profile='standard'):
    """Use the original estimator unless video recovery is explicitly enabled."""
    if profile=='standard':
        from .bed_contact_standard import add_bed_contact_times as standard
        standard(data,result,source,cache_path)
        result['bed_timing']['profile']='standard'
        return result
    if profile!='video_recovery':
        raise ValueError('Unknown bed-contact profile')
    result=_add_recovery_bed_contact_times(data,result,source,cache_path)
    result['bed_timing']['profile']='video_recovery'
    return result


def _add_recovery_bed_contact_times(data, result, source, cache_path=None):
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
    discovered=cached.get('discovered_contacts',[])
    additions=[]
    separation=result.get('settings',{}).get('min_bounce_seconds',.6)
    for event in discovered:
        stamp=event['proxy_seconds']
        if any(abs(c['timestamp_seconds']-stamp)<separation for c in result['contacts']):continue
        landing=event['landing']
        contact=dict(frame_index=landing['frame_index'],timestamp_seconds=stamp,
            method='paired_visible_bed_deformation',status='video_estimate_needs_review',
            review_interval_seconds=landing['interval_seconds'],rotation_end_seconds=stamp,
            note='Contact discovered in both visible bed strips; review source frames.')
        if event['release']:contact['rotation_start_seconds']=event['release']['timestamp_seconds']
        additions.append(contact)
    if additions:
        from .skill_identification import analyze,Settings
        facing=result.get('facing',{})
        rebuilt=analyze(data,settings=Settings(**result['settings']),
                        facing_override=facing['screen_direction'] if facing.get('method')=='user_override' else None,
                        additional_contacts=additions)
        result.clear();result.update(rebuilt)
    by_contact = {event['proxy_seconds']:event for event in [*cached['events'],*discovered]}
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
    result['bed_timing'] = {k:v for k,v in cached.items() if k not in ('events','discovered_contacts','global_samples')}
    result['bed_timing']['additional_video_contacts']=len(additions)
    return result
