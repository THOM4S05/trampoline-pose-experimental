"""Native-frame evidence images for the sustained shape selected by analysis."""
import math
import cv2

from .output import sha256
from .render import overlay
from .video import decode


def save_shape_images(data, result, source_path, directory):
    selected, manifest = {}, {}
    by_index = {frame['frame_index']: frame for frame in data['frames']}
    for skill in result['skills']:
        key = str(skill['skill_index'])
        review = skill['execution'].get('review_shape_timestamp_seconds') is not None
        stamp = skill['execution'].get('review_shape_timestamp_seconds') if review else skill['execution'].get('shape_timestamp_seconds')
        kickout = skill.get('kickout', {}).get('selected')
        if kickout is not None:
            record = by_index[kickout['frame_index']]
            selected.setdefault(record['frame_index'], []).append(
                (f'kickout-{key}', record, kickout['timestamp_seconds'], 'native_opening_evidence'))
        if stamp is None:
            manifest[key] = dict(available=False, message='No supported tightest-shape time was selected.')
            continue
        frames = [f for f in data['frames'] if skill['visible_start_seconds'] <= f['timestamp_seconds'] <= skill['visible_end_seconds']]
        if not frames or not math.isfinite(stamp):
            raise ValueError('Selected shape time has no matching pose frame')
        record = min(frames, key=lambda f: abs(f['timestamp_seconds'] - stamp))
        method = skill['execution'].get('review_shape_selection_method', 'occluded_shape_review_midpoint') if review else 'supported_sustained_shape'
        selected.setdefault(record['frame_index'], []).append((key, record, stamp, method))
    rendered = save_native_images(data, source_path, directory, selected)
    for skill in result['skills']:
        image = rendered.pop(f"kickout-{skill['skill_index']}", None)
        if image is not None:
            skill['kickout']['image'] = image
    return manifest | rendered


def save_native_images(data, source_path, directory, selected):
    if sha256(source_path) != data['source']['sha256']:
        raise ValueError('Source video changed; refusing mismatched skill images')
    directory.mkdir(exist_ok=True)
    manifest = {}
    pending = set(selected)
    if not pending:
        return manifest
    for timing, image in decode(source_path, data['source']):
        index = timing['frame_index']
        if index not in pending:
            continue
        for key, record, stamp, method in selected[index]:
            if abs(timing['timestamp_seconds'] - record['timestamp_seconds']) > 1e-6:
                raise ValueError('Source frame timestamp differs from the selected pose')
            if any(timing[field] != record[field] for field in ('source_pts', 'source_time_base')):
                raise ValueError('Source frame PTS or time base differs from the selected pose')
            drawn = overlay(image, record)
            box = record.get('bbox_xyxy')
            if box is not None and all(math.isfinite(v) for v in box):
                x1, y1, x2, y2 = box
                px, py = max(6, (x2 - x1) * .1), max(6, (y2 - y1) * .1)
                left, top = max(0, math.floor(x1 - px)), max(0, math.floor(y1 - py))
                right, bottom = min(drawn.shape[1], math.ceil(x2 + px)), min(drawn.shape[0], math.ceil(y2 + py))
                if right > left and bottom > top:
                    drawn = drawn[top:bottom, left:right]
            scale = min(1., 1280 / max(drawn.shape[:2]))
            if scale < 1:
                drawn = cv2.resize(drawn, (round(drawn.shape[1] * scale), round(drawn.shape[0] * scale)))
            filename = f'{key}.jpg'
            ok, encoded = cv2.imencode('.jpg', drawn, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                raise ValueError('Unable to save skill overlay image')
            temporary = directory / f'{key}.pending'
            temporary.write_bytes(encoded.tobytes())
            temporary.replace(directory / filename)
            manifest[key] = dict(available=True, frame_index=index,
                                 timestamp_seconds=timing['timestamp_seconds'],
                                 source_pts=timing['source_pts'], source_time_base=timing['source_time_base'],
                                 selection_method=method,
                                 selected_shape_timestamp_seconds=stamp)
        pending.remove(index)
        if not pending:
            break
    if pending:
        raise ValueError('Source ended before the selected skill frames')
    return manifest
