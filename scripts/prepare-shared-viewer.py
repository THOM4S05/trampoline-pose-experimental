"""Export selected experimental results to a self-contained, read-only website.

No server, model loading, inference, or changes to the original jobs. Run with
the project's Python environment (NumPy/SciPy are used for the saved dial trace).
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / 'experiments' / 'twist-width-copy'
SOURCE = ROOT / 'shared-viewer'
ID = re.compile(r'[a-f0-9]{32}')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False,
                               separators=(',', ':')), encoding='utf-8')


def completed_jobs(jobs_root):
    result = []
    for path in sorted(jobs_root.glob('*/job.json')):
        job = read_json(path)
        if (ID.fullmatch(path.parent.name) and job.get('id') == path.parent.name
                and job.get('state') == 'done'
                and job.get('analysis', {}).get('state') == 'done'):
            result.append(job)
    return result


def align_reference(reference, skills):
    # Match the local portal's time-based reference alignment. Labels remain
    # reference annotations and never replace measured skill attributes.
    rows = []
    for row in reference.get('skills', []):
        item = dict(row)
        if row.get('start_seconds') is not None and row.get('end_seconds') is not None:
            def overlap(skill):
                return max(0., min(row['end_seconds'], skill['visible_end_seconds'])
                           - max(row['start_seconds'], skill['visible_start_seconds']))
            best = max(skills, key=overlap) if skills else None
            item['reference_flight_index'] = row.get('reference_flight_index', row.get('skill_index'))
            item['skill_index'] = best['skill_index'] if best and overlap(best) > 0 else None
        rows.append(item)
    # Only fields used by the viewer are published, never raw reference notes.
    fields = ('routine_start_seconds', 'routine_end_seconds', 'window_provenance')
    row_fields = ('skill_index', 'routine_index', 'skill_identity', 'somersault_quarters',
                  'direction', 'twist_count', 'user_confirmed', 'reference_flight_index')
    return {**{k: reference[k] for k in fields if k in reference},
            'skills': [{k: row[k] for k in row_fields if k in row} for row in rows]}


def safe_input(directory, relative):
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        raise ValueError(f'Missing or unsafe saved result: {relative}')
    return path


def export_site(jobs_root, destination, selected, orientation, difficulty):
    jobs_root, destination = jobs_root.resolve(), destination.resolve()
    available = {j['id']: j for j in completed_jobs(jobs_root)}
    if not selected or len(set(selected)) != len(selected):
        raise ValueError('Select at least one unique completed video ID.')
    for job_id in selected:
        if not ID.fullmatch(job_id) or job_id not in available:
            raise ValueError(f'Not a completed analysis: {job_id}')
    # Never merge into an old export: removed clips must not remain publishable.
    # Requiring a fresh directory also prevents overwriting any existing work.
    if destination.exists():
        raise ValueError('Output already exists. Choose a new output directory.')
    if destination.is_relative_to(jobs_root) or jobs_root.is_relative_to(destination):
        raise ValueError('Output must be separate from the private jobs directory.')
    if destination.is_relative_to(SOURCE.resolve()):
        raise ValueError('Output must be outside the viewer source directory.')
    for job_id in selected:
        directory = jobs_root / job_id
        for filename in ('overlay.mp4', 'skills.json', 'joints.json', 'frames.json'):
            safe_input(directory, filename)
    destination.mkdir(parents=True)
    shutil.copytree(SOURCE / 'assets', destination / 'assets')
    shutil.copyfile(SOURCE / 'index.html', destination / 'index.html')
    (destination / '.nojekyll').touch()
    # This standalone folder can become a separate GitHub repository even
    # though video files are ignored by the parent development repository.
    (destination / '.gitignore').write_text('.DS_Store\nThumbs.db\n', encoding='utf-8')
    manifest = []
    for job_id in selected:
        job, directory = available[job_id], jobs_root / job_id
        out = destination / 'data' / job_id
        out.mkdir(parents=True)
        result = read_json(safe_input(directory, 'skills.json'))
        difficulty(result)
        reference_file = directory / 'skill-reference.json'
        reference = align_reference(read_json(safe_input(directory, 'skill-reference.json'))
                                    if reference_file.exists() else {}, result['skills'])
        images = {}
        image_manifest = directory / 'skill-images.json'
        if image_manifest.exists():
            raw_images = read_json(safe_input(directory, 'skill-images.json'))
            for key, value in raw_images.items():
                if not re.fullmatch(r'\d+', key):
                    continue
                fields = ('available', 'frame_index', 'timestamp_seconds', 'selection_method')
                images[key] = {k: value[k] for k in fields if k in value}
                if value.get('available'):
                    image = safe_input(directory, f'skill-images/{key}.jpg')
                    (out / 'skill-images').mkdir(exist_ok=True)
                    shutil.copyfile(image, out / 'skill-images' / f'{key}.jpg')
        write_json(out / 'analysis.json', dict(
            analysis=dict(state='done', message='Saved experimental analysis. Use the review tools to explore the evidence.'),
            skills=result['skills'], contacts=result.get('contacts', []),
            shape_images=images, reference=reference))
        # Raw exports may contain original paths in metadata; only the measured
        # fields used for review are included in the downloadable skills JSON.
        write_json(out / 'skills.json', dict(skills=result['skills'], contacts=result.get('contacts', [])))
        with (out / 'skills.csv').open('w', encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['flight', 'start_seconds', 'end_seconds', 'somersault_quarters',
                             'shape', 'candidate_twists', 'difficulty'])
            for skill in result['skills']:
                twist = skill.get('twist')
                twist = twist if isinstance(twist, dict) else {}
                writer.writerow([skill.get('skill_index'), skill.get('start_seconds'), skill.get('end_seconds'),
                                 skill.get('rotation', {}).get('somersault_quarters'),
                                 skill.get('execution', {}).get('execution_position'),
                                 twist.get('candidate_count'), skill.get('difficulty', {}).get('value')])
        timestamps = read_json(safe_input(directory, 'frames.json'))
        write_json(out / 'frames.json', dict(timestamps=timestamps))
        write_json(out / 'orientation.json', orientation(read_json(safe_input(directory, 'joints.json'))))
        shutil.copyfile(safe_input(directory, 'overlay.mp4'), out / 'overlay.mp4')
        label = job.get('label') or job.get('display_name') or Path(job['name']).stem
        manifest.append(dict(id=job_id, label=label, name=label, state='done', analysis=dict(state='done')))
    write_json(destination / 'data' / 'videos.json', dict(jobs=manifest))
    (destination / 'README.md').write_text(
        '# Flightroom shared viewer\n\n'
        'A static copy of selected experimental results. No backend, uploads, or inference.\n\n'
        'Everything in this folder becomes public when published to GitHub Pages. '
        'Review the selected footage and labels before publishing.\n\n'
        'Create a separate public repository, upload this folder, and enable '
        'Settings > Pages > Deploy from a branch > main > /(root).\n', encoding='utf-8')
    files = list(destination.rglob('*'))
    large = [p.relative_to(destination).as_posix() for p in files if p.is_file() and p.stat().st_size >= 100 * 1024**2]
    total = sum(p.stat().st_size for p in files if p.is_file())
    return dict(directory=str(destination), videos=len(manifest), size_mb=round(total / 1024**2, 1),
                github_ready=not large and total <= 1024**3, oversized_files=large)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs-root', type=Path, default=EXPERIMENT / '.portal' / 'jobs')
    parser.add_argument('--list', action='store_true', help='List completed analyses without exporting')
    parser.add_argument('--all', action='store_true', help='Prepare all completed clips for LOCAL review')
    parser.add_argument('--job', action='append', default=[], help='Explicit video ID to export (repeatable)')
    parser.add_argument('--output', type=Path, help='New, empty standalone output folder')
    args = parser.parse_args()
    jobs = completed_jobs(args.jobs_root)
    if args.list:
        for job in jobs:
            print(f"{job['id']}  {job.get('label') or job['name']}")
        return
    if not args.output or (not args.all and not args.job) or (args.all and args.job):
        parser.error('Use --output with either --all or one or more --job IDs.')
    # Import only saved-result utilities, never the portal, queue, or tracker.
    sys.path.insert(0, str(EXPERIMENT / 'src'))
    from trampoline_pose.orientation import orientation_samples
    from trampoline_pose.difficulty import attach_difficulty
    try:
        summary = export_site(args.jobs_root, args.output,
                              [j['id'] for j in jobs] if args.all else args.job,
                              orientation_samples, attach_difficulty)
    except (ValueError, OSError) as error:
        parser.exit(1, f'Export failed: {error}\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
