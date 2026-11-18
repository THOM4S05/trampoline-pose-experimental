"""Verify that a public export contains only selected, completed result assets."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'shared_export', Path(__file__).parents[1] / 'scripts' / 'prepare-shared-viewer.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def job(root, job_id, state='done'):
    directory = root / job_id
    write(directory / 'job.json', dict(id=job_id, name='private-original.mov',
          label='Shared clip', state=state, selection={'secret': 'box'},
          analysis={'state': 'done'}, local_path='C:/private/video'))
    (directory / 'overlay.mp4').write_bytes(b'overlay-only')
    (directory / 'source.mov').write_bytes(b'private original')
    (directory / 'access-key.txt').write_text('private-secret')
    write(directory / 'skills.json', dict(source_path='C:/private/video',
          skills=[dict(skill_index=1, start_seconds=0, end_seconds=1,
                       visible_start_seconds=0, visible_end_seconds=1)], contacts=[]))
    write(directory / 'joints.json', {'private': 'raw-joints'})
    write(directory / 'frames.json', [0, .04, .08])
    return directory


def export(root, out, ids):
    return exporter.export_site(root, out, ids,
                                lambda _: {'samples': [[0, 0, 0]]}, lambda _: None)


def test_export_excludes_private_data_and_unselected_jobs(tmp_path):
    root, out = tmp_path / 'jobs', tmp_path / 'site'
    first, second = 'a' * 32, 'b' * 32
    directory = job(root, first)
    job(root, second)
    write(directory / 'skill-reference.json', dict(private_note='DO NOT SHARE',
          routine_start_seconds=0, skills=[dict(skill_index=10, start_seconds=0,
          end_seconds=1, skill_identity='Tuck', private_person='DO NOT SHARE')]))
    write(directory / 'skill-images.json', {'1': dict(available=True, frame_index=0,
          timestamp_seconds=0, local_path='C:/private/image')})
    (directory / 'skill-images').mkdir()
    (directory / 'skill-images' / '1.jpg').write_bytes(b'image')
    summary = export(root, out, [first])
    assert summary['videos'] == 1 and summary['github_ready']
    assert not (out / 'data' / second).exists()
    names = {p.name for p in out.rglob('*')}
    assert not {'job.json', 'source.mov', 'access-key.txt', 'joints.json'} & names
    payloads = '\n'.join(p.read_text() for p in (out / 'data').rglob('*.json'))
    assert 'C:/private' not in payloads
    assert 'DO NOT SHARE' not in payloads
    analysis = json.loads((out / 'data' / first / 'analysis.json').read_text())
    assert analysis['reference']['skills'][0]['skill_index'] == 1
    assert json.loads((out / 'data' / first / 'frames.json').read_text())['timestamps'] == [0, .04, .08]
    assert (directory / 'source.mov').read_bytes() == b'private original'


def test_export_requires_fresh_directory_and_completed_selection(tmp_path):
    root, out = tmp_path / 'jobs', tmp_path / 'site'
    first, second = 'a' * 32, 'b' * 32
    job(root, first)
    job(root, second, state='processing')
    for ids in ([], ['../private'], [second], [first, first]):
        with pytest.raises(ValueError):
            export(root, out, ids)
        assert not out.exists()
    out.mkdir()
    (out / 'keep.txt').write_text('existing work')
    with pytest.raises(ValueError, match='already exists'):
        export(root, out, [first])
    assert (out / 'keep.txt').read_text() == 'existing work'


def test_no_live_backend_or_mutation_controls_in_viewer():
    source = exporter.SOURCE
    html = (source / 'index.html').read_text(encoding='utf-8')
    assert 'type="file"' not in html
    assert 'start-analysis' not in html
    for script in (source / 'assets').glob('*.js'):
        text = script.read_text(encoding='utf-8')
        assert '/api/' not in text
        assert not any(verb in text for verb in ("method:'POST'", "method: 'PATCH'", "method:'DELETE'"))
