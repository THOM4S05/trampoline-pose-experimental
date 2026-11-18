"""Run copied skill analysis plus CSV-only twist experiment and HTML review."""
import argparse
import csv
import html
import json
from pathlib import Path

from analyze_skills import load_pose
from trampoline_pose.skill_identification import analyze
from trampoline_pose.twist_width import attach


def review(result):
    panels = []
    for skill in result['skills']:
        twist = skill['twist']
        rows = twist['raw_evidence']
        start, end = skill['visible_start_seconds'], skill['visible_end_seconds']
        def x(t):
            return 45 + 850 * (t - start) / max(end - start, .001)
        traces = []
        for part, color in [('shoulder', '#2266cc'), ('hip', '#cc6600')]:
            points = []
            previous = None
            for r in rows:
                value = r[part + '_fraction']
                t = r['timestamp_seconds']
                if value is None or (previous is not None and t - previous > .08):
                    if points:
                        traces.append(f'<polyline fill="none" stroke="{color}" points="{" ".join(points)}"/>')
                    points = []
                if value is not None:
                    points.append(f'{x(t):.2f},{205 - 150 * min(value, 1.3):.2f}')
                previous = t
            if points:
                traces.append(f'<polyline fill="none" stroke="{color}" points="{" ".join(points)}"/>')
        for fraction in (.35, .65):
            y = 205 - 150 * fraction
            traces.append(f'<path d="M45 {y} H895" stroke="#aaa" stroke-dasharray="4 4"/><text x="5" y="{y}">{fraction}</text>')
        for event in twist['events']:
            px = x(event['broad_seconds'])
            traces.append(f'<path d="M{px} 10 V210" stroke="#559955"/><text x="{px + 3}" y="25">passage</text>')
        candidate = twist['candidate_count']
        label = 'unknown' if candidate is None else f'{candidate:g} candidate twists'
        reasons = html.escape(', '.join(twist['reasons']) or 'No quality gate failed; still requires visual confirmation.')
        panels.append(f'<section><h2>Skill {skill["skill_index"]}: {label}</h2><p>{start:.3f}–{end:.3f}s · {twist["completed_passages"]} completed passages</p><svg viewBox="0 0 930 240" role="img" aria-label="Shoulder and hip widths over flight"><path d="M45 10 V210 H895" fill="none" stroke="#888"/>{"".join(traces)}<text x="45" y="235">{start:.2f}s</text><text x="845" y="235">{end:.2f}s</text></svg><p>{reasons}</p></section>')
    return '<!doctype html><meta charset="utf-8"><title>Twist width experiment</title><style>body{font:16px system-ui;max-width:1050px;margin:32px auto;padding:0 20px;background:#f7f8fa;color:#172033}section{background:white;padding:20px;margin:20px 0;border:1px solid #ddd;border-radius:10px}svg{width:100%;font:12px system-ui}h2{font-size:20px}</style><h1>Twist width experiment</h1><p>Blue: shoulders. Orange: hips. Widths divided by a constant recording-wide q95 for each segment; raw pixels are in evidence.csv. Green lines mark completed narrow → broad → narrow passages.</p><p><b>All counts are tentative.</b> Width cannot establish rotation direction or exclude reversals, foreshortening or pose errors. Check each passage against video and check takeoff/landing facing with somersault rotation in mind. No video processing or model inference was run.</p>' + ''.join(panels)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    source = args.input.resolve()
    output = args.output_dir.resolve()
    if output == source.parent or output in source.parents:
        parser.error('Choose a separate output directory to protect source tracking files')
    data = load_pose(source)
    result = attach(data, analyze(data))
    output.mkdir(parents=True, exist_ok=True)
    (output / 'analysis.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    summaries = [dict(skill_index=s['skill_index'], start_seconds=s['visible_start_seconds'],
                      end_seconds=s['visible_end_seconds'], candidate_twists=s['twist']['candidate_count'],
                      status=s['twist']['status'], completed_passages=s['twist']['completed_passages'],
                      reasons=';'.join(s['twist']['reasons'])) for s in result['skills']]
    evidence = [dict(skill_index=s['skill_index'], **r) for s in result['skills'] for r in s['twist']['raw_evidence']]
    for name, rows in [('skills.csv', summaries), ('evidence.csv', evidence)]:
        with (output / name).open('w', newline='', encoding='utf-8') as stream:
            if rows:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    (output / 'review.html').write_text(review(result), encoding='utf-8')
    print(json.dumps(dict(output=str(output), skills=len(summaries), tentative=sum(r['status'] == 'tentative' for r in summaries))))


if __name__ == '__main__':
    main()
