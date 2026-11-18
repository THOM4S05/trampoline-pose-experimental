"""Losslessly move saved review-video indexes to the front, keeping backups."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import time

import av


def index_at_start(path):
    size = path.stat().st_size
    boxes = []
    with path.open('rb') as stream:
        offset = 0
        while offset + 8 <= size:
            stream.seek(offset)
            length, kind = struct.unpack('>I4s', stream.read(8))
            if length == 1:
                length = struct.unpack('>Q', stream.read(8))[0]
            if length == 0:
                length = size - offset
            if length < 8 or offset + length > size:
                raise ValueError('Invalid MP4 box')
            boxes.append(kind)
            offset += length
    return b'moov' in boxes and b'mdat' in boxes and boxes.index(b'moov') < boxes.index(b'mdat')


def media_signature(path):
    """Compare compressed video/audio and their exact presentation times."""
    digest = hashlib.sha256()
    counts = {}
    with av.open(str(path)) as container:
        for packet in container.demux():
            if not packet.size:
                continue
            stream = packet.stream
            if stream.type not in {'video', 'audio'}:
                continue
            identity = (stream.index, stream.type, stream.codec_context.name)
            timing = tuple(str(value * packet.time_base) if value is not None else None
                           for value in (packet.pts, packet.dts, packet.duration))
            digest.update(repr((identity, timing, packet.size)).encode())
            digest.update(bytes(packet))
            counts[stream.index] = counts.get(stream.index, 0) + 1
    if not counts:
        raise ValueError('Video has no media packets')
    return digest.hexdigest(), counts


def optimize(path, backup):
    if index_at_start(path):
        return False
    original_stat = path.stat()
    signature = media_signature(path)
    temporary = path.with_name('overlay.faststart.tmp.mp4')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(path), '-map', '0',
                    '-c', 'copy', '-movflags', '+faststart', str(temporary)], check=True)
    if not index_at_start(temporary) or media_signature(temporary) != signature:
        raise ValueError('Optimized video verification failed; original retained')
    if (path.stat().st_mtime_ns, path.stat().st_size) != (original_stat.st_mtime_ns, original_stat.st_size):
        raise ValueError('Video changed during optimization; original retained')
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        raise ValueError('Backup already exists; original retained')
    shutil.copy2(path, backup)
    for attempt in range(8):
        try:
            temporary.replace(path)
            return True
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(.25)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path('.portal'))
    args = parser.parse_args()
    root = args.data_dir.resolve()
    backup_root = root / 'playback-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    completed = skipped = 0
    for metadata in sorted((root / 'jobs').glob('*/job.json')):
        job = json.loads(metadata.read_text(encoding='utf-8'))
        path = metadata.parent / 'overlay.mp4'
        if job.get('state') != 'done' or not path.is_file() or path.stat().st_size < 1024:
            continue
        if optimize(path, backup_root / metadata.parent.name / path.name):
            completed += 1
        else:
            skipped += 1
        print(f'Optimized {completed}; already ready {skipped}', flush=True)
    print(f'Finished: {completed} optimized, {skipped} already ready. Backups: {backup_root}', flush=True)


if __name__ == '__main__':
    main()
