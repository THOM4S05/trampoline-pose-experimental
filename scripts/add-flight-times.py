"""Add video flight estimates to completed saved jobs, preserving old results."""
import argparse
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from trampoline_pose.skill_identification import write_csv
from trampoline_pose.bed_contact import add_bed_contact_times, VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path('.portal'))
    parser.add_argument('--redo', action='store_true', help='Recalculate existing video timing estimates')
    parser.add_argument('--job', help='Process one job ID')
    args = parser.parse_args()
    backup = args.data_dir / 'flight-time-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    for directory in sorted((args.data_dir / 'jobs').iterdir()):
        if args.job and directory.name != args.job:
            continue
        result_path, pose_path = directory / 'skills.json', directory / 'joints.json'
        job_path = directory / 'job.json'
        if not all(path.is_file() for path in (result_path, pose_path, job_path)):
            continue
        job = json.loads(job_path.read_text(encoding='utf-8'))
        if job.get('analysis', {}).get('state') != 'done':
            continue
        result = json.loads(result_path.read_text(encoding='utf-8'))
        if not args.redo and result.get('bed_timing', {}).get('version') == VERSION:
            continue
        add_bed_contact_times(json.loads(pose_path.read_text(encoding='utf-8')), result,
                              directory / ('source' + job['extension']), directory / 'bed-motion.json')
        saved = backup / directory.name
        saved.mkdir(parents=True, exist_ok=True)
        csv_path = directory / 'skills.csv'
        for path in (result_path, csv_path):
            if path.is_file():
                shutil.copy2(path, saved / path.name)
        json_tmp = directory / 'skills.flight-time.pending.json'
        json_tmp.write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
        if csv_path.is_file():
            with csv_path.open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            by_index = {str(s['skill_index']): s for s in result['skills']}
            for row in rows:
                skill = by_index.get(row['skill_index'])
                if skill:
                    row.update(time_of_flight_seconds=skill['time_of_flight_seconds'],
                               time_of_flight=skill['time_of_flight'], landing_contact=skill['landing_contact'])
            csv_tmp = directory / 'skills.flight-time.pending.csv'
            write_csv(csv_tmp, rows)
            csv_tmp.replace(csv_path)
        json_tmp.replace(result_path)
        available = sum(s['time_of_flight_seconds'] is not None for s in result['skills'])
        print(f'{directory.name}: {available}/{len(result["skills"])} flight estimates')


if __name__ == '__main__':
    main()
