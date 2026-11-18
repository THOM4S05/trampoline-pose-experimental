"""Tentative twist passages corroborated by body-relative face direction."""
import numpy as np

from .skill_identification import centre,usable


def candidate(data,rows,skill,previous,settings):
    rotation=skill.get('rotation',{})
    turns=rotation.get('somersault_count')
    if turns is None:turns=rotation.get('candidate_somersault_count')
    if (turns is None or turns<.25 or previous['candidate_count'] is not None
            or skill.get('start_clipped') or skill.get('end_clipped')
            or any(r.endswith('_reference_too_small') for r in previous['reasons'])):
        return None
    projected=rotation.get('projected_turns')
    if projected is not None and abs(projected)<max(.15,turns-.35):
        return None
    start,end=previous['start_seconds'],previous['end_seconds']
    selected=[r for r in rows if start<=r['timestamp_seconds']<=end]
    good=[r for r in selected if all(r[p+'_fraction'] is not None for p in ('shoulder','hip'))]
    # An elapsed-time threshold is quantized to native frame timestamps.
    # Permit half a source-frame period, rather than losing an otherwise
    # bounded 80 ms observation gap to the 120 fps sampling grid.
    frame_period=float(np.median(np.diff([r['timestamp_seconds'] for r in selected]))) if len(selected)>1 else 0.
    max_gap=settings.max_gap_seconds+frame_period/2
    if (not selected or len(good)/len(selected)<.9 or len(good)<5
            or good[0]['timestamp_seconds']-start>max_gap
            or end-good[-1]['timestamp_seconds']>max_gap
            or any(b['timestamp_seconds']-a['timestamp_seconds']>max_gap
                   for a,b in zip(good,good[1:]))
            or any(r.get('track_state')=='lost' for r in selected)):
        return None
    observations=[]
    for frame in data['frames']:
        t=frame['timestamp_seconds']
        if not start<=t<=end:continue
        shoulder,hip,ear=[centre(frame,p) for p in ('shoulder','hip','ear')]
        nose=usable(frame,'nose')
        axis=shoulder-hip
        length=np.linalg.norm(axis)
        if nose is None or not np.isfinite([*axis,*ear]).all() or length<10:continue
        # Rotate the nose/ear displacement with the torso. A somersault alone
        # reverses screen-left/right, but preserves this body-relative sign.
        offset=float((nose-ear)@np.array([-axis[1],axis[0]])/length**2)
        observations.append((t,offset))
    if len(observations)<6:return None
    times,offsets=np.array(observations).T
    filtered=np.array([np.median(offsets[abs(times-t)<=.025]) for t in times])
    signed=[(t,1 if v>0 else -1) for t,v in zip(times,filtered) if abs(v)>=.08]
    runs=[]
    for t,sign in signed:
        if not runs or runs[-1]['sign']!=sign or t-runs[-1]['end']>settings.max_gap_seconds:
            runs.append(dict(sign=sign,start=t,end=t,n=1))
        else:
            runs[-1]['end']=t;runs[-1]['n']+=1
    runs=[r for r in runs if r['n']>=3 and r['end']-r['start']>=.04]
    phases=[]
    for run in runs:
        if phases and phases[-1]['sign']==run['sign']:
            phases[-1]['end']=run['end'];phases[-1]['n']+=run['n']
        else:phases.append(dict(run))
    if (len(phases)<2 or len(phases)>7 or phases[0]['start']>start+.2
            or phases[-1]['end']<end-.2):return None
    events=[]
    for before,after in zip(phases,phases[1:]):
        if after['start']-before['end']>.6:return None
        passage=[r for r in good if before['end']-.15<=r['timestamp_seconds']<=after['start']+.2]
        supported=[r for r in passage if min(r[p+'_fraction'] for p in ('shoulder','hip'))>=.45]
        groups=[]
        for row in supported:
            if not groups or row['timestamp_seconds']-groups[-1][-1]['timestamp_seconds']>.02:
                groups.append([])
            groups[-1].append(row)
        groups=[g for g in groups if len(g)>=2 and g[-1]['timestamp_seconds']-g[0]['timestamp_seconds']>=settings.stable_seconds]
        if not groups:return None
        broad=max((r for g in groups for r in g),key=lambda r:min(r[p+'_fraction'] for p in ('shoulder','hip')))
        # Head direction alone is insufficient. Both pair widths must expand
        # relative to observed narrower views on the adjoining face phases.
        for phase in (before,after):
            side=[r for r in good if phase['start']<=r['timestamp_seconds']<=phase['end']]
            if len(side)<3:return None
            if any(broad[p+'_fraction']-np.quantile([r[p+'_fraction'] for r in side],.2)<.2
                   for p in ('shoulder','hip')):return None
        events.append(dict(start_frame=passage[0]['frame_index'],end_frame=passage[-1]['frame_index'],
            broad_frame=broad['frame_index'],broad_seconds=broad['timestamp_seconds'],candidate_half_turns=1,
            completion_method='paired_broadening_with_body_relative_facing',
            facing_before=before,facing_after=after))
    return dict(candidate_count=len(events)*.5,events=events,
        facing_check=dict(method='nose_relative_to_ears_in_torso_coordinates',phases=phases,
                          observation_gap_limit_seconds=max_gap),
        review_reasons=sorted(set(previous['reasons']+previous.get('review_reasons',[])
                                 +['body_relative_facing_candidate_needs_review'])))
