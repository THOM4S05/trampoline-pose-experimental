"""Compare the decoder against saved experimental jobs; optionally refresh one."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trampoline_pose.twist_width import attach


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-job')
    parser.add_argument('--refresh-all',action='store_true')
    parser.add_argument('--report-dir',type=Path,default=ROOT/'results/width-decoder')
    args=parser.parse_args()
    report=args.report_dir.resolve()
    report.mkdir(parents=True,exist_ok=True)
    comparisons=[]
    for path in sorted((ROOT/'.portal/jobs').glob('*/skills.json')):
        directory=path.parent
        job=json.loads((directory/'job.json').read_text())
        data=json.loads((directory/'joints.json').read_text())
        before=json.loads(path.read_text())
        after=attach(data,json.loads(path.read_text()))
        comparisons.append(dict(job_id=directory.name,name=job['name'],flights=[
            dict(skill_index=a['skill_index'],before=b['twist']['candidate_count'],
                 after=a['twist']['candidate_count'],reasons=a['twist']['reasons'],
                 events=a['twist']['events']) for b,a in zip(before['skills'],after['skills'])]))
        if args.refresh_all or directory.name==args.refresh_job:
            backup=report/('before-decoder-v'+str(after['twist_experiment']['decoder_version']))/directory.name
            backup.mkdir(parents=True,exist_ok=True)
            for name in ('skills.json','skills.csv','job.json'):
                if not (backup/name).exists():
                    shutil.copy2(directory/name,backup/name)
    report.mkdir(parents=True,exist_ok=True)
    (report/'decoder-comparison.json').write_text(json.dumps(comparisons,indent=2,allow_nan=False))
    if args.refresh_job or args.refresh_all:
        from trampoline_pose.portal import JobStore
        from trampoline_pose.types import TrackerConfig
        store=JobStore(ROOT/'.portal/jobs',TrackerConfig())
        try:
            ids=[row['job_id'] for row in comparisons] if args.refresh_all else [args.refresh_job]
            for job_id in ids:
                job=store.jobs[job_id]
                store.analyze_skills(job)
                if job['analysis']['state']!='done':
                    raise RuntimeError(job['analysis'])
        finally:
            store.worker.shutdown(wait=True)
    for row in comparisons:
        print(row['name'],[(f['skill_index'],f['before'],f['after']) for f in row['flights']])


if __name__=='__main__':
    main()
