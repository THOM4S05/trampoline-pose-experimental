"""Submit user-labelled home examples to the isolated local portal."""
import argparse
import http.cookiejar
import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://localhost:8766'
CLIENT = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def request(path, data=None, method=None, raw=False):
    headers = {'Origin': BASE, 'X-Portal-Request': '1'}
    if data is not None:
        headers['Content-Type'] = 'application/octet-stream' if raw else 'application/json'
        data = data if raw else json.dumps(data).encode()
    with CLIENT.open(urllib.request.Request(BASE + path, data=data, headers=headers, method=method), timeout=60) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['submit', 'status', 'analyze'])
    args = parser.parse_args()
    request('/api/login', {'key': (ROOT / '.portal/access-key.txt').read_text().strip()})
    out = ROOT / 'results/home-examples'
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / 'manifest.json'
    if args.action == 'submit':
        examples = []
        jobs = request('/api/jobs')['jobs']
        for name, count, box in [('FullTwistHome', 1, [520, 260, 650, 560]),
                                  ('HalfTwistHome', .5, [320, 140, 435, 350])]:
            path = Path.home() / 'Downloads' / (name + '.mp4')
            job = next((j for j in jobs if j['name'] == path.name), None)
            if job is None:
                content = path.read_bytes()
                job = request('/api/jobs', {'name': path.name, 'size': len(content)})
                jid = job['id']
                for offset in range(0, len(content), 1024 * 1024):
                    request(f'/api/jobs/{jid}/upload?offset={offset}', content[offset:offset + 1024 * 1024], 'PUT', raw=True)
                request(f'/api/jobs/{jid}/finish', {}, 'POST')
            examples.append(dict(name=name, job_id=job['id'], expected_total_twists=count,
                                 label_source='user', partition='development', initial_selection_box=box))
        manifest.write_text(json.dumps(examples, indent=2), encoding='utf-8')
        for example in examples:
            jid = example['job_id']
            deadline = time.monotonic() + 40
            while True:
                job = request(f'/api/jobs/{jid}?frames=0')
                if job['state'] not in ('uploading', 'preparing'):
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError('Video preparation still running; retry submit')
                time.sleep(.25)
            if job['state'] == 'ready':
                job = request(f'/api/jobs/{jid}/run', {'frame_index':0, 'bbox_xyxy':example['initial_selection_box']})
            print(example['name'], jid, job['state'], flush=True)
    else:
        for example in json.loads(manifest.read_text(encoding='utf-8')):
            jid = example['job_id']
            job = request(f'/api/jobs/{jid}?frames=0')
            analysis = job.get('analysis', {})
            if args.action == 'analyze' and job['state'] == 'done' and analysis.get('state') not in ('queued', 'running') and (analysis.get('state') != 'done' or analysis.get('twist_version', 0) < 3):
                request(f'/api/jobs/{jid}/analysis', {'redo': True}, 'POST')
                job = request(f'/api/jobs/{jid}?frames=0')
            print(json.dumps(dict(name=example['name'], job_id=jid, state=job['state'], progress=job.get('progress'),
                                  analysis=job.get('analysis'), message=job.get('message'))), flush=True)


if __name__ == '__main__':
    main()
