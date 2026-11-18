"""Publish the reviewed Instagram retry into its experimental portal job."""
import http.cookiejar
import json
from pathlib import Path
import shutil
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trampoline_pose.output import sha256,validate

job_id='82ca1f7b2df443ffb10eeb3fad06f6cc'
directory=ROOT/'.portal/jobs'/job_id
staging=directory/'tracking-retry'
data=json.loads((staging/'joints.json').read_text())
validate(data)
assert data['source']['sha256']==sha256(directory/'source.mp4')
assert data['processed_frame_count']==884
assert data['diagnostics']['track_states']['tracked']==669
report=ROOT/'results/instagram-tracking'
backup=report/'before-retry'
backup.mkdir(exist_ok=True)
for name in ('joints.json','joints.csv','overlay.mp4','detections.json','job.json','skills.json','skills.csv','bed-motion.json','skill-images.json'):
    if (directory/name).exists() and not (backup/name).exists():
        shutil.copy2(directory/name,backup/name)
for name in ('joints.json','joints.csv','overlay.mp4','detections.json'):
    temporary=directory/(name+'.retry-pending')
    shutil.copy2(staging/name,temporary)
    temporary.replace(directory/name)
base='http://localhost:8766'
client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def request(path,body=None):
    payload=None if body is None else json.dumps(body).encode()
    req=urllib.request.Request(base+path,data=payload,headers={
        'Content-Type':'application/json','Origin':base,'X-Portal-Request':'1'})
    with client.open(req,timeout=60) as response:
        return json.load(response)
request('/api/login',{'key':(ROOT/'.portal/access-key.txt').read_text().strip()})
job=request('/api/jobs/'+job_id+'?frames=0')
if job.get('analysis',{}).get('state') not in ('queued','running'):
    request('/api/jobs/'+job_id+'/analysis',{'redo':True})
print('Published reviewed overlay and joints; skill analysis queued.')
