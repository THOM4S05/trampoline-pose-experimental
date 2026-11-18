"""Replay phase recovery against saved experimental clips without publishing."""
import copy
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
COPY = ROOT / 'experiments/twist-width-copy'
sys.path.insert(0, str(COPY / 'src'))
from trampoline_pose.skill_identification import centre, rotation_contact_check
from trampoline_pose.rotation_phases import phase_rotation_evidence, recover_rotation

report = []
for directory in sorted((COPY / '.portal/jobs').iterdir()):
    if not (directory / 'skills.json').exists() or not (directory / 'joints.json').exists():
        continue
    data = json.loads((directory / 'joints.json').read_text())
    result = json.loads((directory / 'skills.json').read_text())
    t = np.array([f['timestamp_seconds'] for f in data['frames']])
    shoulder, hip = [np.array([centre(f, p) for f in data['frames']]) for p in ('shoulder', 'hip')]
    changes = []
    for skill in result['skills']:
        rotation = skill['rotation']
        before = copy.deepcopy(rotation)
        start, end = rotation['window_start_seconds'], rotation['window_end_seconds']
        a, b = skill['visible_start_seconds'], skill['visible_end_seconds']
        context = (t >= min(a, start) - .35) & (t <= max(b, end) + .35)
        evidence = phase_rotation_evidence(t[context], shoulder[context], hip[context],
                                          start, end, a, b, skill['start_clipped'] or skill['end_clipped'])
        positions = [skill.get(p + '_position', 'unknown') for p in ('takeoff', 'landing')]
        recover_rotation(rotation, evidence, positions)
        original_positions = positions.copy()
        if evidence['status'] == 'tentative':
            for i, p in enumerate(('takeoff_phase', 'landing_phase')):
                if positions[i] == 'unknown':
                    positions[i] = {'upright': 'upright', 'horizontal': 'body'}[evidence[p]]
        rotation['contact_consistency'] = rotation_contact_check(rotation, *positions,
                                                               skill['start_clipped'] or skill['end_clipped'])
        rotation['contact_consistency']['orientation_proxies_used'] = positions != original_positions
        assert rotation.get('somersault_count') == before.get('somersault_count')
        assert rotation.get('projected_turns') == before.get('projected_turns')
        if rotation.get('candidate_somersault_count') != before.get('candidate_somersault_count'):
            changes.append(dict(flight=skill['skill_index'], before=before['candidate_somersault_count'],
                                after=rotation['candidate_somersault_count']))
    report.append(dict(job=directory.name, flights=len(result['skills']), changes=changes))
    print(directory.name, 'flights', len(result['skills']), 'changes', changes, flush=True)
    if directory.name == 'f96c0c42f29845f3b2af56191095760f':
        stage = directory / 'rotation-phase-retry'
        stage.mkdir(exist_ok=True)
        (stage / 'skills.json').write_text(json.dumps(result, indent=2, allow_nan=False))
out = ROOT / 'reports/rotation-phase-replay.json'
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(report, indent=2))
print('REPORT', out, flush=True)
