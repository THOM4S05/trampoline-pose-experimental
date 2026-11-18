"""Paired width phases checked against facing for upright feet-to-feet jumps."""
import numpy as np

from .skill_identification import centre,usable


def jump_candidate(data,rows,refs,skill,previous,settings):
    if (previous['candidate_count'] is not None or skill.get('start_clipped') or skill.get('end_clipped')
            or skill.get('rotation',{}).get('somersault_count')!=0
            or skill.get('takeoff_position')!='feet' or skill.get('landing_position')!='feet'
            or set(previous['reasons'])-{'incomplete_passage','side_on_start_not_established','side_on_finish_not_established'}):
        return None
    start,end=previous['start_seconds'],previous['end_seconds']
    selected=[r for r in rows if start<=r['timestamp_seconds']<=end]
    if len(selected)<5 or any(r[p+'_fraction'] is None for r in selected for p in ('shoulder','hip')):
        return None
    if (refs['shoulder'] is None or refs['shoulder']<settings.minimum_shoulder_reference_px
            or refs['hip'] is None or refs['hip']<settings.minimum_hip_reference_px):
        return None
    times=np.array([r['timestamp_seconds'] for r in selected])
    if np.max(np.diff(times))>settings.max_gap_seconds:
        return None
    values=np.array([[r[p+'_fraction'] for p in ('shoulder','hip')] for r in selected])
    if np.max(np.median(values[times<=start+.12],axis=0))>settings.zero_max_width_fraction:
        return None
    broad=values.min(axis=1)>=settings.broad_fraction
    ids=np.flatnonzero(broad)
    runs=[g for g in np.split(ids,np.flatnonzero(np.diff(ids)>1)+1)
          if len(g)>=2 and times[g[-1]]-times[g[0]]+1e-9>=settings.stable_seconds]
    phases=[]
    for run in runs:
        if not phases:
            phases.append(run)
            continue
        left=phases[-1]
        threshold=np.minimum(values[left].max(axis=0),values[run].max(axis=0))-settings.paired_valley_drop
        valley=np.flatnonzero((np.arange(len(times))>left[-1])&(np.arange(len(times))<run[0])
                             &(values<=threshold).all(axis=1))
        sustained=any(len(g)>=2 and times[g[-1]]-times[g[0]]+1e-9>=settings.stable_seconds
                      for g in np.split(valley,np.flatnonzero(np.diff(valley)>1)+1))
        if sustained:phases.append(run)
        else:phases[-1]=np.r_[left,run]
    if not phases or len(phases)>6:
        return None

    def facing(lo,hi):
        votes=[]
        for frame in data['frames']:
            t=frame['timestamp_seconds']
            if not lo<=t<=hi:continue
            sh,hip,ear=[centre(frame,p) for p in ('shoulder','hip','ear')]
            nose=usable(frame,'nose')
            length=np.linalg.norm(sh-hip)
            if (nose is None or not np.isfinite([*sh,*hip,*ear]).all() or length<10
                    or (hip[1]-sh[1])/length<.85):continue
            offset=float((nose[0]-ear[0])/length)
            if abs(offset)>=.035:votes.append((t,1 if offset>0 else -1))
        agreement=abs(sum(v for _,v in votes))/len(votes) if votes else 0.
        if len(votes)<3 or votes[-1][0]-votes[0][0]<.025 or agreement<.8:
            return None
        return dict(direction=1 if sum(v for _,v in votes)>0 else -1,
                    start_seconds=votes[0][0],end_seconds=votes[-1][0],
                    vote_count=len(votes),agreement=agreement)
    first=facing(max(0,start-.08),start+.15)
    last=facing(end-.05,min(end+.12,skill['visible_end_seconds']))
    if first is None or last is None:
        return None
    if (first['direction']!=last['direction'])!=(len(phases)%2==1):
        return None
    events=[]
    for phase in phases:
        peak=int(phase[np.argmax(values[phase].min(axis=1))])
        events.append(dict(start_frame=selected[int(phase[0])]['frame_index'],
            end_frame=selected[int(phase[-1])]['frame_index'],broad_frame=selected[peak]['frame_index'],
            broad_seconds=float(times[peak]),candidate_half_turns=1,
            completion_method='paired_width_phase_with_endpoint_facing'))
    return dict(candidate_count=len(phases)*.5,events=events,
        facing_check=dict(method='upright_nose_relative_to_ears',start=first,finish=last,
                          matching_half_turn_parity=True),
        review_reasons=previous['reasons'],
        finish_note='Landing facing supports the candidate; final torso-width completion needs review.')
