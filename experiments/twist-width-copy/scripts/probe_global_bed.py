from pathlib import Path
import sys,json,cv2,numpy as np
from scipy.ndimage import gaussian_filter1d,percentile_filter
from scipy.signal import find_peaks
root=Path('experiments/twist-width-copy');sys.path.insert(0,str(root/'src'))
from trampoline_pose.video import decode
from trampoline_pose.skill_identification import centre
p=root/'.portal/jobs/82ca1f7b2df443ffb10eeb3fad06f6cc';d=json.loads((p/'joints.json').read_text());r=json.loads((root/'results/instagram-tracking/bed-region-probe.json').read_text())['region'];scale=.625
ref=None
for t,im in decode(p/'source.mp4',d['source']):
 if t['timestamp_seconds']>=r['reference_seconds']:ref=cv2.cvtColor(cv2.resize(im,None,fx=scale,fy=scale),cv2.COLOR_BGR2GRAY);break
x1,y1,x2,y2=[round(v*scale) for v in r['roi']];mask=np.full_like(ref,255);mask[y1:]=0;cx=r['athlete_x']*scale;rad=r['torso']*scale*1.5;mask[:,max(0,round(cx-rad)):round(cx+rad)]=0;corners=cv2.goodFeaturesToTrack(ref,100,.01,8,mask=mask);rows=[]
for timing,im in decode(p/'source.mp4',d['source']):
 f=d['frames'][timing['frame_index']];stamp=timing['timestamp_seconds'];cur=cv2.cvtColor(cv2.resize(im,None,fx=scale,fy=scale),cv2.COLOR_BGR2GRAY);dest,status,err=cv2.calcOpticalFlowPyrLK(ref,cur,corners,None,winSize=(25,25),maxLevel=3);good=(status[:,0]>0)&(err[:,0]<20);delta=(dest-corners)[:,0][good];shift=np.median(delta,axis=0) if len(delta) else np.array([np.nan,np.nan]);mat,inliers=cv2.estimateAffinePartial2D(corners[good],dest[good],method=cv2.RANSAC,ransacReprojThreshold=1.5) if good.sum()>=8 else (None,None)
 if len(delta)>=8 and np.median(np.linalg.norm(delta-shift,axis=1))<1.5:mat=np.float32([[1,0,shift[0]],[0,1,shift[1]]]);inliers=np.ones((len(delta),1))
 values=[None,None]
 if mat is not None and inliers.sum()>=8 and inliers.mean()>=.6 and .9<=np.linalg.norm(mat[:,0])<=1.1 and f['diagnostics'].get('reason')!='scene_cut_requires_new_seed':
  aligned=cv2.warpAffine(cur,mat,(ref.shape[1],ref.shape[0]),flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP);diff=cv2.absdiff(aligned,ref);hip=centre(f,'hip');box=f.get('bbox_xyxy');center=float(hip[0]) if np.isfinite(hip).all() else (box[0]+box[2])/2 if box is not None else r['athlete_x'];left=round((center-r['torso'])*scale);right=round((center+r['torso'])*scale)
  values=[]
  for lo,hi in ((x1,min(x2,left)),(max(x1,right),x2)):
   patch=diff[y1:y2,max(0,lo):max(0,hi)];values.append(float(np.mean(patch)) if patch.size>=100 else None)
 rows.append([stamp,*values])
a=np.array([[np.nan if v is None else v for v in row] for row in rows]);valid=np.isfinite(a[:,1:]).all(axis=1);ids=np.flatnonzero(valid);signals=np.full((len(a),2),np.nan);peaks=[]
for g in np.split(ids,np.flatnonzero(np.diff(ids)>1)+1):
 if len(g)<20:continue
 values=a[g,1:];sm=gaussian_filter1d(values,.025/(1/30),axis=0);baseline=percentile_filter(sm,percentile=15,size=(41,1),mode='nearest');excess=np.maximum(0,sm-baseline);q=excess.min(axis=1);found,_=find_peaks(q,prominence=2,distance=18);signals[g]=excess
 for j in found:peaks.append((int(g[j]),float(q[j])))
print('peaks',[(round(a[i,0],3),round(q,2)) for i,q in peaks]);(root/'results/instagram-tracking/global-bed-probe.json').write_text(json.dumps({'region':r,'samples':rows,'peaks':peaks},indent=2,allow_nan=False))
