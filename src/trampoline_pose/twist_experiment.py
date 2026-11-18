"""Local-only review, 2D baseline and selective evaluation for twist experiments."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import time

import cv2
import numpy as np
import psutil
from scipy.signal import find_peaks

from .output import sha256
from .skill_identification import usable
from .twist_decoder import DecoderSettings, decode_flight
from .twist_sidecar import binding, fingerprint, validate, verify_source, verify_timing
from .video import decode


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pending.replace(path)


def protocol():
    """Thresholds declared before inspecting labels; no appearance training."""
    return dict(protocol_version="0.1.0", decoder=asdict(DecoderSettings()),
                baseline=dict(width_quantile=.95, minimum_prominence=.25,
                              minimum_event_spacing_seconds=.12, temporal_filter_radius_seconds=.035),
                partition_policy="development only until athlete and session identities are independently established",
                label_policy="explicit reviewed observed execution; absent labels excluded; references excluded",
                count_semantics="absolute_net_turns; reversal trials reported separately",
                release_gate="no production backend selected without independent count/coverage evaluation")


def audit_jobs(root):
    rows, seen = [], set()
    for path in sorted(Path(root).glob("*/job.json")):
        job = read_json(path)
        pose = path.parent / "joints.json"
        if not pose.exists():
            continue
        data = read_json(pose)
        digest = data["source"]["sha256"]
        if digest in seen:
            continue
        seen.add(digest)
        source = path.parent / ("source" + job["extension"])
        verify_source(data, source)
        rows.append(dict(job_id=path.parent.name, name=job["name"], source=str(source),
            pose=str(pose), skills=str(path.parent / "skills.json"), **binding(data),
            source_hash_verified=True, frames=len(data["frames"]),
            native_time_base=data["source"]["source_time_base"], rotation=data["source"]["rotation_degrees_ccw"],
            athlete_identity=None, session=None,
            tracked=sum(f["track_state"] == "tracked" for f in data["frames"])))
    return rows


def _tile(image, record):
    height, width = image.shape[:2]
    box = record.get("bbox_xyxy")
    if box:
        x1, y1, x2, y2 = box
        px, py = .18 * (x2 - x1), .12 * (y2 - y1)
        l, t = max(0, math.floor(x1 - px)), max(0, math.floor(y1 - py))
        r, b = min(width, math.ceil(x2 + px)), min(height, math.ceil(y2 + py))
    else:
        l, t, r, b = 0, 0, width, height
    crop = image[t:b, l:r]
    if not crop.size:
        raise ValueError("Empty tracked review crop")
    scale = min(224 / crop.shape[1], 250 / crop.shape[0])
    crop = cv2.resize(crop, (max(1, round(crop.shape[1] * scale)), max(1, round(crop.shape[0] * scale))))
    tile = np.full((282, 224, 3), 240, np.uint8)
    tile[:crop.shape[0], :crop.shape[1]] = crop
    label = f"f{record['frame_index']} {record['timestamp_seconds']:.4f}s"
    cv2.putText(tile, label, (3, 267), cv2.FONT_HERSHEY_SIMPLEX, .42, (0, 0, 0), 1)
    return tile, dict(crop_xyxy=[l, t, r, b], resize_scale=scale)


def prepare_review(data, results, source, indices, directory):
    verify_source(data, source)
    if results.get("source_sha256") != data["source"]["sha256"]:
        raise ValueError("Analysis/source mismatch")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    manifest = dict(manifest_version="0.1.0", protocol=protocol(), recordings=[dict(
        id=data["source"]["sha256"], source=str(Path(source).resolve()),
        athlete_id=None, session_id=None, **binding(data))], flights=[])
    selected = {}
    tiles = {}
    for skill in results["skills"]:
        if skill["skill_index"] not in indices:
            continue
        timing = skill.get("time_of_flight", {})
        # Video bed estimates remain review-needed; do not promote them automatically.
        start = timing.get("takeoff_seconds")
        end = timing.get("landing_seconds")
        if start is None:
            start = skill.get("start_seconds", skill.get("visible_start_seconds"))
        if end is None:
            end = skill.get("end_seconds", skill.get("visible_end_seconds"))
        if start is None or end is None or start >= end:
            continue
        fid = f"{data['source']['sha256'][:12]}-flight-{skill['skill_index']}"
        frames = [f for f in data["frames"] if start - .1 <= f["timestamp_seconds"] <= end + .1]
        flight = dict(id=fid, recording_id=data["source"]["sha256"], skill_index=skill["skill_index"],
            partition="development", start_interval_seconds=timing.get("takeoff_interval_seconds", [start - .05, start + .05]),
            end_interval_seconds=timing.get("landing_interval_seconds", [end - .05, end + .05]),
            nominal_start_seconds=start, nominal_end_seconds=end, boundary_verified=False,
            boundary_provenance="saved video estimate" if timing.get("takeoff_seconds") is not None else "saved contact proposal",
            start_clipped=bool(skill.get("start_clipped")), end_clipped=bool(skill.get("end_clipped")),
            frame_indices=[f["frame_index"] for f in frames], review_sheets=[], frames=[])
        manifest["flights"].append(flight)
        tiles[fid] = []
        for f in frames:
            selected.setdefault(f["frame_index"], []).append((flight, f))
    for native, image in decode(source, data["source"]):
        for flight, original in selected.pop(native["frame_index"], []):
            verify_timing({**native, "track_id": original.get("track_id")}, original)
            tile, transform = _tile(image, original)
            tiles[flight["id"]].append(tile)
            flight["frames"].append({**native, **transform,
                **{key: original.get(key) for key in ("track_id", "track_state", "bbox_xyxy")}})
        if not selected:
            break
    if selected:
        raise ValueError("Source ended before requested native frames")
    for flight in manifest["flights"]:
        panels = tiles[flight["id"]]
        for offset in range(0, len(panels), 64):
            subset = panels[offset:offset + 64]
            sheet = np.full((282 * math.ceil(len(subset) / 8), 224 * 8, 3), 255, np.uint8)
            for k, tile in enumerate(subset):
                y, x = (k // 8) * 282, (k % 8) * 224
                sheet[y:y+282, x:x+224] = tile
            name = f"{flight['id']}-{offset // 64 + 1}.jpg"
            if not cv2.imwrite(str(directory / name), sheet, [cv2.IMWRITE_JPEG_QUALITY, 93]):
                raise ValueError("Could not save review sheet")
            flight["review_sheets"].append(str((directory / name).resolve()))
    return manifest


def shoulder_feature(frame):
    points = [usable(frame, name) for name in ("left_shoulder", "right_shoulder", "left_hip", "right_hip")]
    if any(p is None for p in points):
        return None
    ls, rs, lh, rh = points
    length = np.linalg.norm((ls + rs - lh - rh) / 2)
    if length < 10:
        return None
    return float(np.linalg.norm(rs - ls) / length)


def baseline(data, flight, declared_protocol):
    """Connolly-inspired width *diagnostic*, not a reimplementation of their classifier.

    Counts width minima naively to expose failure modes. Front/back, shape and
    side correctness are unobservable here, so this method NEVER supports a count.
    """
    config = declared_protocol["baseline"]
    all_features = [shoulder_feature(f) for f in data["frames"]]
    pool = [v for v in all_features if v is not None]
    scale = float(np.quantile(pool, config["width_quantile"])) if pool else 0
    start, end = flight["nominal_start_seconds"], flight["nominal_end_seconds"]
    rows = [dict(frame_index=f["frame_index"], timestamp_seconds=f["timestamp_seconds"],
                 normalized_width=v / scale if v is not None and scale > 0 else None)
            for f, v in zip(data["frames"], all_features) if start <= f["timestamp_seconds"] <= end]
    valid = [r for r in rows if r["normalized_width"] is not None]
    t = np.array([r["timestamp_seconds"] for r in valid])
    y = np.array([r["normalized_width"] for r in valid])
    radius = config["temporal_filter_radius_seconds"]
    filtered = np.array([np.median(y[np.abs(t - stamp) <= radius]) for stamp in t])
    peaks, _ = find_peaks(-filtered, prominence=config["minimum_prominence"])
    accepted = []
    for p in peaks:
        if not accepted or t[p] - t[accepted[-1]] >= config["minimum_event_spacing_seconds"]:
            accepted.append(p)
    gap = any(b["timestamp_seconds"] - a["timestamp_seconds"] > .08 for a, b in zip(valid, valid[1:]))
    covered = sum(b["timestamp_seconds"] - a["timestamp_seconds"] for a, b in zip(valid, valid[1:])
                  if b["timestamp_seconds"] - a["timestamp_seconds"] <= .08)
    reasons = ["projected_width_cannot_resolve_front_back_depth_or_hidden_turns"]
    if gap:
        reasons.append("unsupported_torso_gap")
    candidate = len(accepted) / 2 if len(valid) >= 3 and not gap else None
    if flight.get("start_clipped") or flight.get("end_clipped"):
        candidate = None
        reasons.append("partial_flight")
    return dict(flight_id=flight["id"], source_sha256=data["source"]["sha256"],
        count=None, candidate_count=candidate, status="tentative" if candidate is not None else "unknown",
        method="2d_normalized_shoulder_width_minima", coverage=min(1., covered / (end - start)),
        reasons=reasons, supporting_minima=[valid[p]["frame_index"] for p in accepted],
        raw_evidence=rows, scale_q95_torso_lengths=scale)


def _metrics(pairs, field):
    accepted = [(label, p[field]) for label, p in pairs if p.get(field) is not None]
    confusion = {}
    for label, p in pairs:
        key = str(label)
        predicted = str(p[field]) if p.get(field) is not None else "unknown"
        confusion.setdefault(key, {})[predicted] = confusion.get(key, {}).get(predicted, 0) + 1
    n = len(accepted)
    zeros = [(a, b) for a, b in accepted if a == 0]
    return dict(eligible=len(pairs), accepted=n, coverage=n / len(pairs) if pairs else None,
        exact_accuracy=sum(a == b for a, b in accepted) / n if n else None,
        half_turn_error_rate=sum(abs(a - b) == .5 for a, b in accepted) / n if n else None,
        false_twist_rate_on_accepted_zero=sum(b != 0 for _, b in zeros) / len(zeros) if zeros else None,
        zero_labelled=sum(a == 0 for a, _ in pairs), zero_accepted=len(zeros), confusion=confusion)


def evaluate(manifest, annotations, prediction_sets, partition="development", allow_agent=False):
    if annotations.get("manifest_sha256") != fingerprint(manifest):
        raise ValueError("Annotations refer to a different review manifest")
    ids = {f["id"]: f for f in manifest["flights"]}
    if len(ids) != len(manifest["flights"]):
        raise ValueError("Duplicate flight IDs")
    recordings = {r["id"]: r for r in manifest["recordings"]}
    if partition == "heldout":
        groups = {}
        for f in manifest["flights"]:
            r = recordings[f["recording_id"]]
            if not r.get("athlete_id") or not r.get("session_id"):
                raise ValueError("Held-out claims require independently established athlete/session identities")
            for key in (r["id"], r["athlete_id"], r["session_id"]):
                groups.setdefault(key, set()).add(f["partition"])
        if any(len(partitions) > 1 for partitions in groups.values()):
            raise ValueError("Recording/athlete/session leakage across partitions")
    labels, excluded, seen_annotations, tags_by_flight = {}, [], set(), {}
    for annotation in annotations["annotations"]:
        fid = annotation["flight_id"]
        if fid not in ids or fid in seen_annotations:
            raise ValueError("Unknown or duplicate annotation ID")
        seen_annotations.add(fid)
        if ids[fid]["partition"] != partition:
            continue
        value = annotation.get("observed_twist_turns")
        if (annotation.get("certainty") != "clear" or value is None
                or annotation.get("provenance") not in (["human_review", "agent_visual_review"] if allow_agent else ["human_review"])
                or annotation.get("reversal", False)):
            excluded.append(fid)
            continue
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value * 2 != round(value * 2):
            raise ValueError("Invalid observed twist label")
        labels[fid] = value
        tags_by_flight[fid] = annotation.get("tags", [])
    report = dict(evaluation_schema_version="0.1.0", partition=partition,
        evidence_scope="development visual audit; not human ground truth" if allow_agent else "human-reviewed labels",
        manifest_sha256=fingerprint(manifest), protocol_sha256=fingerprint(manifest["protocol"]),
        labelled=len(labels), excluded_uncertain_or_reference=excluded,
        missing_annotations=[fid for fid, f in ids.items() if f["partition"] == partition and fid not in labels and fid not in excluded], methods={})
    for name, predictions in prediction_sets.items():
        if predictions.get("manifest_sha256") != fingerprint(manifest):
            raise ValueError("Predictions refer to a different manifest")
        rows = predictions["predictions"]
        lookup = {p["flight_id"]: p for p in rows}
        if len(lookup) != len(rows) or any(fid not in ids for fid in lookup):
            raise ValueError("Duplicate or unknown prediction ID")
        for fid, p in lookup.items():
            if p.get("source_sha256") != recordings[ids[fid]["recording_id"]]["source_sha256"]:
                raise ValueError("Prediction/video source mismatch")
            if p.get("count") is not None and p.get("status") not in (None, "supported", "supported_conditional"):
                raise ValueError("Tentative prediction cannot contain a supported count")
            for key in ("count", "candidate_count"):
                value = p.get(key)
                if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                    raise ValueError("Invalid predicted count")
        complete = all(fid in lookup for fid in labels)
        pairs = [(v, lookup.get(fid, {})) for fid, v in labels.items()]
        available = predictions.get("inference_status") != "unavailable"
        report["methods"][name] = dict(inference_status=predictions.get("inference_status", "completed"),
            complete=complete, supported=_metrics(pairs, "count") if available else None,
            tentative_only=_metrics(pairs, "candidate_count") if available else None,
            runtime=predictions.get("runtime"),
            failures=[dict(flight_id=fid, label=v, predicted=p.get("count"),
                           candidate=p.get("candidate_count"), reasons=p.get("reasons", []))
                      for fid, v in labels.items() for p in [lookup.get(fid, {})] if p.get("count") != v],
            selective_accuracy_vs_margin=[dict(minimum_margin=threshold,
                **_metrics([(v, p if threshold == 0 or (p.get("score_margin") is not None and p["score_margin"] >= threshold) else {}) for v, p in pairs], "count"))
                for threshold in [0, 2, 4, 8]] if available else [])
        report["methods"][name]["strata"] = {tag:dict(
            supported=_metrics([(v, lookup.get(fid, {})) for fid, v in labels.items() if tag in tags_by_flight[fid]], "count"),
            tentative_only=_metrics([(v, lookup.get(fid, {})) for fid, v in labels.items() if tag in tags_by_flight[fid]], "candidate_count"))
            for tag in sorted({tag for tags in tags_by_flight.values() for tag in tags})} if available else {}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit")
    audit.add_argument("--jobs", type=Path, default=Path(".portal/jobs"))
    audit.add_argument("--output", type=Path, required=True)
    prep = commands.add_parser("review")
    for name in ("pose", "skills", "video", "output_dir"):
        prep.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    prep.add_argument("--flights", type=int, nargs="+", required=True)
    run = commands.add_parser("run")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--orientations", type=Path)
    run.add_argument("--reference", type=Path, help="Explicit fixed camera basis + upright/cardan branch per flight")
    ev = commands.add_parser("evaluate")
    ev.add_argument("--manifest", type=Path, required=True)
    ev.add_argument("--annotations", type=Path, required=True)
    ev.add_argument("--predictions", type=Path, nargs="+", required=True)
    ev.add_argument("--output", type=Path, required=True)
    ev.add_argument("--partition", choices=["development", "heldout"], default="development")
    ev.add_argument("--allow-agent-review", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "audit":
        value = audit_jobs(args.jobs)
    elif args.command == "review":
        data = read_json(args.pose)
        value = prepare_review(data, read_json(args.skills), args.video, args.flights, args.output_dir)
        value["recordings"][0]["pose"] = str(args.pose.resolve())
        write_json(args.output_dir / "manifest.json", value)
        write_json(args.output_dir / "annotations-template.json", dict(manifest_sha256=fingerprint(value), annotations=[dict(
            flight_id=f["id"], observed_twist_turns=None, certainty="unreviewed", provenance=None,
            orientation_observations=[], boundary_review=None) for f in value["flights"]]))
        print(f"Wrote {len(value['flights'])} native-frame review flights to {args.output_dir}")
        return 0
    elif args.command == "run":
        manifest = read_json(args.manifest)
        started = time.perf_counter()
        poses = {}
        for r in manifest["recordings"]:
            data = read_json(r["pose"])
            verify_source(data, r["source"])
            if binding(data) != {k: r[k] for k in binding(data)}:
                raise ValueError("Review manifest tracking changed")
            poses[r["id"]] = data
        predictions = []
        if args.orientations:
            if not args.reference or len(poses) != 1:
                parser.error("Orientation decoding requires --reference and one recording per run")
            sidecar = read_json(args.orientations)
            validate(sidecar, next(iter(poses.values())))
            references = read_json(args.reference)
            for f in manifest["flights"]:
                ref = references[f["id"]]
                window = {k: f[k] for k in ("start_interval_seconds", "end_interval_seconds", "boundary_verified")}
                result = decode_flight(sidecar["frames"], window, ref["basis_camera"], ref["branch"],
                                       DecoderSettings(**manifest["protocol"]["decoder"]))
                if f.get("start_clipped") or f.get("end_clipped"):
                    result.update(count=None, status="unknown", reasons=sorted(set(result["reasons"]) | {"partial_flight"}))
                predictions.append(dict(flight_id=f["id"], source_sha256=f["recording_id"], **result))
            method = "3d_segment_cardan"
        else:
            method = "2d_width_baseline"
            predictions = [baseline(poses[f["recording_id"]], f, manifest["protocol"]) for f in manifest["flights"]]
        rss = psutil.Process().memory_info()
        value = dict(method=method, inference_status="completed", manifest_sha256=fingerprint(manifest),
                     predictions=predictions, runtime=dict(wall_seconds=time.perf_counter() - started,
                     process_peak_rss_bytes=getattr(rss, "peak_wset", rss.rss),
                     gpu_peak_bytes=None, includes_source_hash_and_pose_load=True))
    else:
        manifest = read_json(args.manifest)
        sets = {p.stem: read_json(p) for p in args.predictions}
        value = evaluate(manifest, read_json(args.annotations), sets, args.partition, args.allow_agent_review)
    write_json(args.output, value)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
