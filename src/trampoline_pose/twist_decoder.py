"""Conservative multiple-hypothesis longitudinal-twist experiment, no ML imports.

Support means conditional geometric evidence under explicit error/rate bounds.
It is not a calibrated reliability claim about monocular reconstructions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import numpy as np

from .twist_geometry import TAU, cardan, upright_heading, rotation_matrix, wrap
from .twist_sidecar import fingerprint

VERSION = "0.1.0"


@dataclass(frozen=True)
class DecoderSettings:
    max_turns_per_second: float = 6.
    max_gap_seconds: float = .08
    min_coverage: float = .95
    half_turn_tolerance: float = .075
    minimum_score_margin: float = 4.
    max_reprojection_error: float = .2
    max_segment_disagreement_degrees: float = 30.
    reversal_threshold_turns: float = .12
    beam_width: int = 64

    def __post_init__(self):
        values = asdict(self)
        if any(not math.isfinite(v) or v <= 0 for v in values.values()):
            raise ValueError("Decoder thresholds must be finite and positive")
        if self.min_coverage > 1 or self.half_turn_tolerance >= .25 or self.beam_width < 2:
            raise ValueError("Invalid decoder coverage, rounding tolerance or beam size")


def _phase(hypothesis, reference, branch):
    m = hypothesis["torso_matrix"]
    return (upright_heading(m, reference) if branch == "upright"
            else cardan(m, reference)["twist"])


def _classify(delta, endpoint_error, settings):
    turns = abs(delta) / TAU
    nearest = round(turns * 2) / 2
    return nearest if abs(turns - nearest) + endpoint_error / TAU <= settings.half_turn_tolerance else None


def _decode_core(records, start, end, reference, branch, boundary_verified, settings):
    reasons = set()
    if not boundary_verified:
        reasons.add("flight_boundaries_unverified")
    rows = [r for r in records if start <= r["timestamp_seconds"] <= end]
    observations = []
    for r in rows:
        if not r.get("valid"):
            continue
        phases = []
        for number, h in enumerate(r.get("hypotheses", [])):
            try:
                phase = _phase(h, reference, branch)
            except ValueError:
                reasons.add("singular_or_outside_orientation_domain")
                continue
            error = h.get("angular_uncertainty_rad")
            if error is None:
                reasons.add("orientation_error_bound_unverified")
            if h.get("reprojection_error_torso_lengths") is None:
                reasons.add("reprojection_unavailable")
            elif h["reprojection_error_torso_lengths"] > settings.max_reprojection_error:
                reasons.add("reprojection_inconsistent")
                continue
            pelvis = h.get("pelvis_matrix")
            if pelvis is None or not h.get("pelvis_independent", False):
                reasons.add("independent_pelvis_orientation_unavailable")
            else:
                try:
                    p = {**h, "torso_matrix": pelvis}
                    disagreement = abs(wrap(_phase(p, reference, branch) - phase))
                    axis_angle = math.acos(float(np.clip(np.dot(np.asarray(pelvis)[:, 2],
                                                          np.asarray(h["torso_matrix"])[:, 2]), -1, 1)))
                    if max(disagreement, axis_angle) > math.radians(settings.max_segment_disagreement_degrees):
                        reasons.add("torso_pelvis_disagreement")
                except ValueError:
                    reasons.add("pelvis_orientation_degenerate")
            phases.append(dict(phase=phase, error=error if error is not None else 0.,
                               cost=float(h.get("cost", 0)), number=number))
        if phases:
            observations.append((r, phases))
    duration = end - start
    if len({r.get("track_id") for r in rows}) > 1:
        reasons.add("athlete_identity_changed")
    supported_intervals = []
    covered = 0.
    for (a, _), (b, _) in zip(observations, observations[1:]):
        dt = b["timestamp_seconds"] - a["timestamp_seconds"]
        # Missing records do not silently bridge a tracking loss even at high FPS.
        between = [r for r in rows if a["timestamp_seconds"] < r["timestamp_seconds"] < b["timestamp_seconds"]]
        if dt > settings.max_gap_seconds + 1e-9 or any(not r.get("valid") for r in between):
            reasons.add("unsupported_gap")
        else:
            covered += dt
            if supported_intervals and abs(supported_intervals[-1][1] - a["timestamp_seconds"]) < 1e-8:
                supported_intervals[-1][1] = b["timestamp_seconds"]
            else:
                supported_intervals.append([a["timestamp_seconds"], b["timestamp_seconds"]])
    coverage = covered / duration if duration > 0 else 0.
    result = dict(count=None, candidate_count=None, candidate_counts=[], net_turns=None,
                  absolute_rotation_turns=None, direction=None, status="unknown",
                  method="experimental_segment_cardan_beam", count_semantics="absolute_net_turns; abstain_on_reversal",
                  coverage=min(1., coverage), reasons=[], supporting_intervals_seconds=supported_intervals,
                  observed_samples=len(observations), hypotheses=[], reconstructed_motion=False,
                  heuristic_scores_are_probabilities=False)
    if len(observations) < 3:
        result["reasons"] = sorted(reasons | {"insufficient_orientation"})
        return result
    if observations[0][0]["timestamp_seconds"] - start > settings.max_gap_seconds or end - observations[-1][0]["timestamp_seconds"] > settings.max_gap_seconds:
        reasons.add("endpoints_unobserved")
    if coverage < settings.min_coverage:
        reasons.add("low_temporal_coverage")
    # Any unsampled boundary motion also needs a bounded endpoint error budget.
    boundary_error = TAU * settings.max_turns_per_second * (
        observations[0][0]["timestamp_seconds"] - start + end - observations[-1][0]["timestamp_seconds"])
    if "unsupported_gap" in reasons or "athlete_identity_changed" in reasons:
        # No whole-flight path is reconstructed across a loss; retained evidence is segmented.
        result["reasons"] = sorted(reasons)
        return result
    first_r, first = observations[0]
    paths = [dict(angle=h["phase"], delta=0., absolute=0., positive=0., negative=0.,
                  velocity=None, score=h["cost"], error=h["error"], start_error=h["error"],
                  history=[dict(frame_index=first_r["frame_index"], timestamp_seconds=first_r["timestamp_seconds"],
                                hypothesis=h["number"], unwrapped_twist_rad=h["phase"])]) for h in first]
    for (previous, _), (record, hypotheses) in zip(observations, observations[1:]):
        dt = record["timestamp_seconds"] - previous["timestamp_seconds"]
        expanded = []
        for path in paths:
            for h in hypotheses:
                error = h["error"] + path["error"]
                reach = TAU * settings.max_turns_per_second * dt + error
                if reach >= math.pi:
                    reasons.add("temporal_aliasing")
                raw = wrap(h["phase"] - path["angle"])
                for winding in range(-math.ceil(reach / TAU) - 1, math.ceil(reach / TAU) + 2):
                    step = raw + winding * TAU
                    if abs(step) > reach + 1e-8:
                        continue
                    velocity = step / dt
                    # A bounded, robust ranking term; acceleration is never a hard constraint.
                    acceleration_cost = 0. if path["velocity"] is None else min(abs(velocity - path["velocity"]) / TAU, 2.) * .05
                    angle = path["angle"] + step
                    expanded.append(dict(angle=angle, delta=path["delta"] + step,
                        absolute=path["absolute"] + abs(step),
                        positive=path["positive"] + max(0., step - error),
                        negative=path["negative"] + max(0., -step - error),
                        velocity=velocity, score=path["score"] + h["cost"] + acceleration_cost,
                        error=h["error"], start_error=path["start_error"],
                        history=path["history"] + [dict(frame_index=record["frame_index"],
                            timestamp_seconds=record["timestamp_seconds"], hypothesis=h["number"],
                            unwrapped_twist_rad=angle)]))
        if not expanded:
            result["reasons"] = sorted(reasons | {"motion_exceeds_configured_bound"})
            return result
        # Keep distinct windings and side assignments, not just the shortest final quaternion.
        unique = {}
        for p in sorted(expanded, key=lambda p: p["score"]):
            key = (p["history"][-1]["hypothesis"], round(p["delta"] / .1), round(p["velocity"] / 2),
                   round(p["positive"] / .2), round(p["negative"] / .2))
            unique.setdefault(key, p)
        ordered = list(unique.values())
        if len(ordered) > settings.beam_width and ordered[settings.beam_width]["score"] - ordered[0]["score"] < settings.minimum_score_margin:
            reasons.add("plausible_hypotheses_pruned")
        paths = ordered[:settings.beam_width]
    best = min(paths, key=lambda p: p["score"])
    near = [p for p in paths if p["score"] - best["score"] < settings.minimum_score_margin]
    classes = [_classify(p["delta"], p["start_error"] + p["error"] + boundary_error, settings) for p in near]
    best_count = _classify(best["delta"], best["start_error"] + best["error"], settings)
    result.update(candidate_count=best_count, candidate_counts=sorted({c for c in classes if c is not None}),
                  net_turns=best["delta"] / TAU, absolute_rotation_turns=best["absolute"] / TAU,
                  direction="positive" if best["delta"] > .01 else "negative" if best["delta"] < -.01 else None,
                  candidate_history=best["history"])
    competing = [p["score"] - best["score"] for p in paths
                 if _classify(p["delta"], p["start_error"] + p["error"], settings) != best_count]
    # None means no retained competing class, not infinite confidence.
    result["score_margin"] = min(competing) if competing else None
    if min(best["positive"], best["negative"]) / TAU > settings.reversal_threshold_turns:
        reasons.add("twist_reversal_net_differs_from_total")
    if not classes or classes[0] is None:
        reasons.add("angular_displacement_or_boundary_error_not_near_half_turn")
    if any(c != classes[0] for c in classes):
        reasons.add("competing_winding_or_side_hypotheses")
    result["hypotheses"] = [dict(net_turns=p["delta"] / TAU,
        absolute_rotation_turns=p["absolute"] / TAU,
        candidate_count=_classify(p["delta"], p["start_error"] + p["error"], settings),
        relative_heuristic_cost=p["score"] - best["score"]) for p in paths[:16]]
    if not reasons:
        result.update(count=classes[0], status="supported_conditional")
    elif result["candidate_count"] is not None:
        result["status"] = "tentative"
    result["reasons"] = sorted(reasons)
    return result


def decode_flight(records, window, reference, branch="cardan", settings=DecoderSettings()):
    """Decode only orientation evidence; never accepts skill names or reference counts.

    window has start/end intervals (seconds) and boundary_verified. All four
    endpoint combinations must support the same count before promotion.
    """
    if branch not in ("cardan", "upright"):
        raise ValueError("Unknown orientation branch")
    reference = rotation_matrix(reference)
    start, end = window["start_interval_seconds"], window["end_interval_seconds"]
    if (len(start) != 2 or len(end) != 2 or not np.isfinite([*start, *end]).all()
            or start[0] > start[1] or end[0] > end[1] or start[1] >= end[0]):
        raise ValueError("Invalid or overlapping flight boundary intervals")
    # Verify native order for direct callers, even without a sidecar validator.
    if any(b["timestamp_seconds"] <= a["timestamp_seconds"] for a, b in zip(records, records[1:])):
        raise ValueError("Non-increasing observation times")
    kwargs = dict(reference=reference, branch=branch,
                  boundary_verified=bool(window.get("boundary_verified")), settings=settings)
    centre = _decode_core(records, sum(start) / 2, sum(end) / 2, **kwargs)
    variants = [_decode_core(records, a, b, **kwargs) for a in sorted(set(start)) for b in sorted(set(end))]
    centre["boundary_sensitivity"] = [dict(start_seconds=a, end_seconds=b,
        count=r["count"], candidate_count=r["candidate_count"], net_turns=r["net_turns"], reasons=r["reasons"])
        for (a, b), r in zip([(a, b) for a in sorted(set(start)) for b in sorted(set(end))], variants)]
    if centre["count"] is not None and any(r["count"] != centre["count"] for r in variants):
        centre["count"] = None
        centre["status"] = "tentative"
        centre["reasons"] = sorted(set(centre["reasons"]) | {"boundary_sensitive"})
    centre.update(twist_schema_version=VERSION, branch=branch, window=window,
                  reference_basis_camera=reference.tolist(), settings=asdict(settings),
                  orientation_input_sha256=fingerprint(records),
                  decoder_signature=fingerprint(dict(version=VERSION, settings=asdict(settings),
                                                     reference=reference.tolist(), branch=branch, window=window,
                                                     orientation_input_sha256=fingerprint(records))))
    return centre
