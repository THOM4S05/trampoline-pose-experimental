from pathlib import Path
import json,sys
root=Path('experiments/twist-width-copy');sys.path.insert(0,str(root/'src'))
from trampoline_pose.skill_identification import analyze
from trampoline_pose.bed_contact import add_bed_contact_times
from trampoline_pose.twist_width import attach
p=root/'.portal/jobs/82ca1f7b2df443ffb10eeb3fad06f6cc';d=json.loads((p/'joints.json').read_text());out=p/'bed-retry';out.mkdir(exist_ok=True)
a=analyze(d);add_bed_contact_times(d,a,p/'source.mp4',out/'bed-motion.json',profile='video_recovery');attach(d,a);(out/'skills.json').write_text(json.dumps(a,indent=2,allow_nan=False));print('region',a['bed_timing']['region']);print('additional',a['bed_timing']['additional_video_contacts']);print('contacts',len(a['contacts']),'landings',sum(bool(c.get('bed_contact')) for c in a['contacts']))
for s in a['skills']:print(s['skill_index'],s['visible_start_seconds'],s['visible_end_seconds'],s['landing_contact'],s['time_of_flight_seconds'])
