from pathlib import Path
import sys,json,numpy as np
root=Path('experiments/twist-width-copy');sys.path.insert(0,str(root/'src'))
import trampoline_pose.bed_contact as bc
from trampoline_pose.skill_identification import centre
p=root/'.portal/jobs/82ca1f7b2df443ffb10eeb3fad06f6cc';d=json.loads((p/'joints.json').read_text());a=json.loads((p/'skills.json').read_text());original=bc.bed_region
region=original(d,a['contacts']);ankles=[centre(f,'ankle')[1] for f in d['frames'] if np.isfinite(centre(f,'ankle')).all()];torso=np.nanmedian([np.linalg.norm(centre(f,'shoulder')-centre(f,'hip')) for f in d['frames']]);y=float(np.quantile(ankles,.92));region.update(roi=[region['roi'][0],int(y-.6*torso),region['roi'][2],int(y+torso)],torso=float(torso));bc.bed_region=lambda *args:region
print('region',region,flush=True)
r=bc.measure_bed(d,a,p/'source.mp4')
out=root/'results/instagram-tracking/bed-region-probe.json';out.write_text(json.dumps(r,indent=2,allow_nan=False))
for e in r['events']:print(e['proxy_seconds'],e['landing'],e['release'],flush=True)
