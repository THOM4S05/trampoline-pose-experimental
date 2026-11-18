"""Serve the isolated twist experiment, sharing the original model assets."""
import argparse
import logging
from pathlib import Path
import sys

COPY = Path(__file__).resolve().parents[1]
ORIGINAL = COPY.parent.parent
sys.path.insert(0, str(COPY / 'src'))

from trampoline_pose.api import PoseTracker
from trampoline_pose.portal import create_app, http_server
from trampoline_pose.types import TrackerConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--public-url', help='Exact private Tailscale HTTPS origin')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    config = TrackerConfig.from_yaml(ORIGINAL / 'configs' / 'default.yaml')
    app = create_app(COPY / '.portal', config, public_url=args.public_url, port=args.port)
    store = app.extensions['job_store']
    print('Loading existing tracking models for the twist experiment...', flush=True)
    store.tracker = PoseTracker(config)
    server = http_server(app, args.port)
    print(f'Experimental version ready: {args.public_url or f"http://localhost:{args.port}"}', flush=True)
    try:
        server.run()
    finally:
        server.close()
        store.worker.shutdown(wait=True)


if __name__ == '__main__':
    main()
