"""Backend-neutral orientation sidecars bound to the original video and track."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
import math

import numpy as np

from .output import sha256
from .twist_geometry import CONVENTION, rotation_matrix

VERSION = "0.1.0"


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def binding(data):
    # Include every exported tracking/configuration field, not just box coordinates.
    return dict(source_sha256=data["source"]["sha256"], tracking_sha256=fingerprint(data))


def cache_key(data, provenance, configuration):
    return fingerprint(dict(schema=VERSION, convention=CONVENTION, **binding(data),
                            provenance=provenance, configuration=configuration))


def new_sidecar(data, provenance, configuration):
    return dict(orientation_schema_version=VERSION, convention=CONVENTION,
                camera_mode="fixed", **binding(data), provenance=provenance,
                configuration=configuration, cache_key=cache_key(data, provenance, configuration),
                frames=[])


def verify_source(data, source):
    if sha256(source) != data["source"].get("sha256"):
        raise ValueError("Original video SHA256 does not match saved tracking")


def verify_timing(record, original):
    for key in ("frame_index", "source_pts", "source_time_base", "track_id"):
        if record.get(key) != original.get(key):
            raise ValueError(f"Orientation/track {key} mismatch")
    if abs(record["timestamp_seconds"] - original["timestamp_seconds"]) > 1e-7:
        raise ValueError("Orientation/track timestamp mismatch")


def validate(sidecar, data, source=None):
    if source is not None:
        verify_source(data, source)
    if (sidecar.get("orientation_schema_version") != VERSION
            or sidecar.get("convention") != CONVENTION or sidecar.get("camera_mode") != "fixed"):
        raise ValueError("Unsupported orientation schema, geometry or moving camera")
    for key, expected in binding(data).items():
        if sidecar.get(key) != expected:
            raise ValueError(f"Stale orientation sidecar: {key} mismatch")
    if sidecar.get("cache_key") != cache_key(data, sidecar["provenance"], sidecar["configuration"]):
        raise ValueError("Orientation cache configuration/provenance mismatch")
    originals = {f["frame_index"]: f for f in data["frames"]}
    if len(originals) != len(data["frames"]):
        raise ValueError("Duplicate tracking frame IDs")
    previous, first_pts, previous_index = -math.inf, None, -1
    seen = set()
    for record in sidecar["frames"]:
        index = record["frame_index"]
        if index in seen or index not in originals or index <= previous_index:
            raise ValueError("Duplicate, unordered or unknown native orientation frame")
        seen.add(index)
        original = originals[index]
        if previous_index >= 0:
            omitted_losses = [f for i, f in originals.items() if previous_index < i < index
                              and f.get("track_state") != "tracked"]
            if omitted_losses:
                raise ValueError("Sidecar omitted tracking loss between observations")
        verify_timing(record, original)
        if first_pts is None:
            f = data["frames"][0]
            first_pts = f["source_pts"] * Fraction(f["source_time_base"])
        absolute = record["source_pts"] * Fraction(record["source_time_base"])
        if abs(float(absolute - first_pts) - record["timestamp_seconds"]) > 1e-6:
            raise ValueError("Native source PTS disagrees with elapsed time")
        if not math.isfinite(record["timestamp_seconds"]) or record["timestamp_seconds"] <= previous:
            raise ValueError("Non-increasing or nonfinite native time")
        previous, previous_index = record["timestamp_seconds"], index
        if record.get("bbox_xyxy") != original.get("bbox_xyxy"):
            raise ValueError("Orientation used a different athlete box")
        if record.get("tracking_crop_transform") != original.get("crop_transform"):
            raise ValueError("Tracking crop provenance changed")
        if record.get("valid") and (original.get("track_state") != "tracked"
                                    or original.get("diagnostics", {}).get("possible_identity_ambiguity")):
            raise ValueError("Orientation invented through tracking loss/identity ambiguity")
        pixel = np.asarray(record["source_to_model_pixels"], dtype=float)
        if pixel.shape != (3, 3) or not np.isfinite(pixel).all() or abs(np.linalg.det(pixel)) < 1e-9:
            raise ValueError("Invalid source-to-model pixel transform")
        rotation_matrix(record["source_to_model_camera"])
        hypotheses = record.get("hypotheses", [])
        if record.get("valid") and not hypotheses:
            raise ValueError("Valid orientation lacks hypotheses")
        for h in hypotheses:
            rotation_matrix(h["torso_matrix"])
            if h.get("pelvis_matrix") is not None:
                rotation_matrix(h["pelvis_matrix"])
            for key in ("cost", "angular_uncertainty_rad", "reprojection_error_torso_lengths"):
                v = h.get(key)
                if v is not None and (not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0):
                    raise ValueError(f"Invalid hypothesis {key}")
    return sidecar


def frame_record(original, **values):
    record = dict(**{k: original.get(k) for k in ("frame_index", "timestamp_seconds", "source_pts",
                "source_time_base", "track_id", "bbox_xyxy")},
                tracking_crop_transform=original.get("crop_transform"),
                source_to_model_pixels=np.eye(3).tolist(), source_to_model_camera=np.eye(3).tolist(),
                valid=False, hypotheses=[], reasons=[])
    record.update(values)
    return record
