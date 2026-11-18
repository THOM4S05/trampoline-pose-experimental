"""Generated geometry establishes software behavior, never real-video accuracy."""
import copy
from fractions import Fraction
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from trampoline_pose.twist_decoder import DecoderSettings, decode_flight
from trampoline_pose.twist_geometry import (cardan, image_ccw_camera, quaternion_matrix,
                                           rotation_matrix, segment_frame, undo_crop_camera)
from trampoline_pose.twist_sidecar import (cache_key, fingerprint, frame_record, new_sidecar,
                                          validate, verify_source)
from trampoline_pose.twist_sam3d import adapt_prediction, run as run_sam, precision_settings, load_checkpoint_state
from trampoline_pose.twist_experiment import baseline, evaluate, protocol
from trampoline_pose.geometry import apply_affine, inverse_affine


def sequence(turns=1, somersaults=1, tilt=.2, times=None):
    times = np.linspace(0, 1, 61) if times is None else np.asarray(times)
    progress = (times - times[0]) / (times[-1] - times[0])
    twists = turns * 2 * np.pi * progress if np.isscalar(turns) else np.asarray(turns)
    tilts = np.full(len(times), tilt) if np.isscalar(tilt) else np.asarray(tilt)
    # SciPy's independently implemented intrinsic XYZ convention supplies truth.
    matrices = Rotation.from_euler("XYZ", np.column_stack((somersaults * 2 * np.pi * progress, tilts, twists))).as_matrix()
    return [dict(frame_index=i, timestamp_seconds=float(t), track_id="athlete", valid=True,
        hypotheses=[dict(torso_matrix=m.tolist(), pelvis_matrix=m.tolist(), pelvis_independent=True,
            cost=0., angular_uncertainty_rad=.001, reprojection_error_torso_lengths=.01)])
        for i, (t, m) in enumerate(zip(times, matrices))]


def decode(rows, **kwargs):
    window = kwargs.pop("window", dict(start_interval_seconds=[0., 0.], end_interval_seconds=[1., 1.], boundary_verified=True))
    return decode_flight(rows, window, np.eye(3), **kwargs)


@pytest.mark.parametrize("turns", [0., .5, 1., 1.5, 2., 3., -.5, -2.])
@pytest.mark.parametrize("somersaults", [0, 1, -1, 2])
def test_known_twists_with_combined_somersaults_and_nonzero_tilt(turns, somersaults):
    result = decode(sequence(turns, somersaults))
    assert result["count"] == abs(turns), result["reasons"]
    assert result["net_turns"] == pytest.approx(turns)
    assert result["absolute_rotation_turns"] == pytest.approx(abs(turns))
    assert result["reconstructed_motion"] is False


def test_tilt_changes_without_twist_do_not_create_twist():
    t = np.linspace(0, 1, 61)
    result = decode(sequence(0, 2, tilt=.6 * np.sin(2 * np.pi * t)))
    assert result["count"] == 0
    assert result["absolute_rotation_turns"] < 1e-10


def test_nonuniform_speed_and_native_vfr_spacing():
    t = np.r_[0, np.cumsum(np.tile([.007, .018, .025], 20))]
    t /= t[-1]
    rows = sequence(turns=4 * np.pi * t**2, times=t, somersaults=2)
    result = decode(rows)
    assert result["count"] == 2
    assert result["candidate_history"][7]["timestamp_seconds"] == t[7]


def test_upright_heading_domain_and_inverted_abstention():
    assert decode(sequence(.5, 0, tilt=0), branch="upright")["count"] == .5
    result = decode(sequence(.5, 1), branch="upright")
    assert result["count"] is None
    assert "singular_or_outside_orientation_domain" in result["reasons"]


def test_singularity_and_torso_pelvis_pike_disagreement():
    result = decode(sequence(1, tilt=np.pi / 2))
    assert result["count"] is None
    rows = sequence(1)
    for r in rows[20:40]:
        h = r["hypotheses"][0]
        h["pelvis_matrix"] = (np.asarray(h["torso_matrix"]) @ Rotation.from_euler("x", .9).as_matrix()).tolist()
    result = decode(rows)
    assert result["count"] is None
    assert "torso_pelvis_disagreement" in result["reasons"]


def test_quaternion_signs_crop_camera_and_static_view_changes():
    rows = sequence(1.5)
    q = image_ccw_camera(90)
    for i, row in enumerate(rows):
        h = row["hypotheses"][0]
        m = np.asarray(h["torso_matrix"])
        quat = Rotation.from_matrix(m).as_quat() * (-1 if i % 2 else 1)
        np.testing.assert_allclose(quaternion_matrix(quat), m, atol=1e-12)
        np.testing.assert_allclose(undo_crop_camera(q @ m, q), m, atol=1e-12)
        h["torso_matrix"] = (q @ m).tolist()
        h["pelvis_matrix"] = (q @ m).tolist()
    window = dict(start_interval_seconds=[0, 0], end_interval_seconds=[1, 1], boundary_verified=True)
    assert decode_flight(rows, window, q)["count"] == 1.5
    # Pixel coordinates additionally need a translation (width-1), whereas
    # camera vectors require only Q. Undoing just this 2D affine leaves Q wrong.
    affine = np.array([[0, 1, 0], [-1, 0, 639.]])
    points = np.array([[0, 0], [639, 479], [123, 87]])
    np.testing.assert_allclose(apply_affine(apply_affine(points, affine), inverse_affine(affine)), points)
    m = Rotation.from_euler("XYZ", [.5, .2, 1.]).as_matrix()
    assert not np.allclose(q @ m, m)
    np.testing.assert_allclose(undo_crop_camera(q @ m, q), m, atol=1e-12)


def test_transient_side_swaps_have_explicit_competing_assignments():
    rows = sequence(1)
    swap = np.diag([-1, -1, 1])
    for i, row in enumerate(rows):
        h = row["hypotheses"][0]
        alternative = copy.deepcopy(h)
        for name in ("torso_matrix", "pelvis_matrix"):
            alternative[name] = (np.asarray(h[name]) @ swap).tolist()
        row["hypotheses"].append(alternative)
        if 20 <= i <= 25:
            row["hypotheses"].reverse()
    result = decode(rows)
    assert result["count"] == 1, result["reasons"]


def test_ambiguous_phase_history_cannot_be_won_by_a_smoothness_prior():
    rows = sequence(0)
    alternative = sequence(1)
    for a, b in zip(rows, alternative):
        a["hypotheses"].extend(b["hypotheses"])
    result = decode(rows)
    assert result["count"] is None
    assert "competing_winding_or_side_hypotheses" in result["reasons"] or "plausible_hypotheses_pruned" in result["reasons"]


def test_tracking_loss_and_large_gaps_never_reconstruct_a_whole_flight():
    rows = sequence(1)
    rows[30]["valid"] = False
    result = decode(rows)
    assert result["count"] is result["candidate_count"] is None
    assert result["net_turns"] is None
    assert len(result["supporting_intervals_seconds"]) == 2
    result = decode(rows[:20] + rows[40:])
    assert "unsupported_gap" in result["reasons"]
    rows = sequence(1)
    rows[30]["track_id"] = "other_athlete"
    assert "athlete_identity_changed" in decode(rows)["reasons"]


def test_aliasing_does_not_choose_zero_from_same_endpoint_facing():
    result = decode(sequence(0, times=[0, .5, 1]))
    assert result["count"] is None
    assert "unsupported_gap" in result["reasons"]
    settings = DecoderSettings(max_gap_seconds=.2, max_turns_per_second=10)
    result = decode(sequence(0, times=np.linspace(0, 1, 11)), settings=settings)
    assert result["count"] is None
    assert "temporal_aliasing" in result["reasons"]


def test_reversal_reports_net_and_absolute_rotation_separately():
    twists = np.r_[np.linspace(0, np.pi, 31), np.linspace(np.pi, 0, 31)[1:]]
    result = decode(sequence(twists, 0))
    assert result["count"] is None
    assert result["net_turns"] == pytest.approx(0)
    assert result["absolute_rotation_turns"] == pytest.approx(1)
    assert "twist_reversal_net_differs_from_total" in result["reasons"]


def test_unrounded_displacement_unsupported_rounding_and_boundary_sensitivity():
    result = decode(sequence(.31))
    assert result["count"] is result["candidate_count"] is None
    assert result["net_turns"] == pytest.approx(.31)
    assert result["decoder_signature"] != decode(sequence(.32))["decoder_signature"]
    result = decode(sequence(.5), window=dict(start_interval_seconds=[0, .15],
                                             end_interval_seconds=[.85, 1], boundary_verified=True))
    assert result["count"] is None
    assert len(result["boundary_sensitivity"]) == 4
    result = decode(sequence(0), window=dict(start_interval_seconds=[0, 0],
                                            end_interval_seconds=[1, 1], boundary_verified=False))
    assert result["count"] is None
    assert result["candidate_count"] == 0


def test_unverified_error_or_pelvis_and_bad_reprojection_abstain():
    for key, value, reason in [("angular_uncertainty_rad", None, "orientation_error_bound_unverified"),
                               ("pelvis_independent", False, "independent_pelvis_orientation_unavailable"),
                               ("reprojection_error_torso_lengths", .8, "reprojection_inconsistent")]:
        rows = sequence(1)
        for r in rows:
            r["hypotheses"][0][key] = value
        result = decode(rows)
        assert result["count"] is None
        assert reason in result["reasons"]


def test_degenerate_geometry_reflection_and_wrong_quaternion():
    for m in [np.diag([-1, 1, 1]), np.eye(3) * 2, np.full((3, 3), np.nan)]:
        with pytest.raises(ValueError):
            rotation_matrix(m)
    with pytest.raises(ValueError):
        segment_frame([0, 0, 0], [0, 0, 1], [0, 0, 0], [0, 0, 1])
    with pytest.raises(ValueError):
        quaternion_matrix([0, 0, 0, 2])
    with pytest.raises(ValueError):
        cardan(Rotation.from_euler("y", 90, degrees=True).as_matrix(), np.eye(3))


def pose_fixture():
    frames = [dict(frame_index=i, timestamp_seconds=t, source_pts=pts, source_time_base="1/1000",
        track_id="athlete", bbox_xyxy=[0, 0, 100, 200], crop_transform={"test": True}, track_state="tracked")
        for i, (t, pts) in enumerate([(0., 100), (.023, 123), (.057, 157)])]
    return dict(source={"sha256": "a" * 64}, selection={"frame_index": 0}, frames=frames)


def test_sidecar_source_hash_cache_crop_and_pts_invalidation(tmp_path):
    data = pose_fixture()
    sidecar = new_sidecar(data, {"checkpoint_sha256": "b" * 64}, {"dtype": "float32"})
    sidecar["frames"] = [frame_record(f) for f in data["frames"]]
    validate(sidecar, data)
    original_key = sidecar["cache_key"]
    assert cache_key(data, sidecar["provenance"], {"dtype": "float16"}) != original_key
    for mutate in [lambda s:s["frames"][1].update(source_pts=124),
                   lambda s:s["frames"][1].update(track_id="other"),
                   lambda s:s["frames"][1].update(bbox_xyxy=[1, 1, 10, 20]),
                   lambda s:s["frames"][1].update(tracking_crop_transform={}),
                   lambda s:s.update(camera_mode="moving"),
                   lambda s:s["configuration"].update(dtype="float16"),
                   lambda s:s["frames"].reverse()]:
        changed = copy.deepcopy(sidecar)
        mutate(changed)
        with pytest.raises(ValueError):
            validate(changed, data)
    source = tmp_path / "wrong.mp4"
    source.write_bytes(b"wrong original")
    with pytest.raises(ValueError, match="SHA256"):
        verify_source(data, source)
    data["frames"][1]["track_state"] = "lost"
    sidecar = new_sidecar(data, {}, {})
    sidecar["frames"] = [frame_record(data["frames"][1], valid=True)]
    with pytest.raises(ValueError, match="tracking loss"):
        validate(sidecar, data)


def test_mhr70_adapter_conventions_and_raw_side_ambiguity():
    points = np.zeros((70, 3))
    points[5], points[6] = [-.2, 0, 0], [.2, 0, 0]
    points[9], points[10] = [-.1, 0, -1], [.1, 0, -1]
    prediction = dict(pred_keypoints_3d=points, pred_keypoints_2d=np.zeros((70, 2)))
    record = adapt_prediction(prediction, pose_fixture()["frames"][0])
    np.testing.assert_allclose(record["hypotheses"][0]["torso_matrix"], np.eye(3))
    assert len(record["hypotheses"]) == 2
    assert record["hypotheses"][0]["pelvis_independent"] is False
    assert record["hypotheses"][0]["angular_uncertainty_rad"] is None
    prediction["pred_keypoints_3d"] = np.zeros((17, 3))
    with pytest.raises(ValueError, match="MHR70"):
        adapt_prediction(prediction, pose_fixture()["frames"][0])


def test_model_runner_rejects_changed_api_before_loading_any_model(tmp_path):
    import json
    from trampoline_pose.output import sha256
    video = tmp_path / "source.mp4"
    video.write_bytes(b"not decoded because API verification fails first")
    pose = tmp_path / "joints.json"
    pose.write_text(json.dumps(dict(source={"sha256":sha256(video)})), encoding="utf-8")
    repository = tmp_path / "upstream"
    file = repository / "sam_3d_body/sam_3d_body_estimator.py"
    file.parent.mkdir(parents=True)
    file.write_text("# changed API", encoding="utf-8")
    args = SimpleNamespace(pose=pose, video=video, repository=repository)
    with pytest.raises(ValueError, match="source hash differs"):
        run_sam(args)


def test_unsupported_bfloat16_requires_explicit_precision_override():
    with pytest.raises(RuntimeError, match="bfloat16"):
        precision_settings("checkpoint", True, "bfloat16", False)
    assert precision_settings("float16", True, "bfloat16", False) == (True, "float16")
    assert precision_settings("float32", True, "bfloat16", False) == (False, "float16")
    assert precision_settings("checkpoint", True, "bfloat16", True) == (True, "bfloat16")


def test_checkpoint_only_permits_missing_fixed_rig_buffers():
    class Model:
        def load_state_dict(self, state, strict):
            return SimpleNamespace(missing_keys=state, unexpected_keys=[])
    assert load_checkpoint_state(Model(), ["head_pose.mhr.buffer"])["missing_fixed_mhr_buffers"]
    assert load_checkpoint_state(Model(), ["backbone.encoder.mask_token"])["missing_known_noninference_keys"]
    with pytest.raises(RuntimeError, match="Learned checkpoint mismatch"):
        load_checkpoint_state(Model(), ["backbone.encoder.blocks.0.weight"])


def evaluation_fixture():
    manifest = dict(protocol=protocol(), recordings=[dict(id="source",source_sha256="hash",athlete_id=None,session_id=None)],
        flights=[dict(id=str(i), recording_id="source", partition="development") for i in range(4)])
    annotations = dict(manifest_sha256=fingerprint(manifest), annotations=[dict(flight_id=str(i),
        observed_twist_turns=v, certainty="clear", provenance="human_review") for i, v in enumerate([0, .5, None, 1])])
    predictions = dict(manifest_sha256=fingerprint(manifest), predictions=[dict(flight_id=str(i), source_sha256="hash", count=v,
        candidate_count=.5) for i, v in enumerate([.5, None, 0, 1])])
    return manifest, annotations, predictions


def test_evaluation_counts_unknowns_never_infers_zero_from_absent_label():
    m, a, p = evaluation_fixture()
    report = evaluate(m, a, {"baseline": p})
    metrics = report["methods"]["baseline"]["supported"]
    assert metrics["eligible"] == 3
    assert metrics["coverage"] == pytest.approx(2 / 3)
    assert metrics["exact_accuracy"] == .5
    assert metrics["half_turn_error_rate"] == .5
    assert metrics["false_twist_rate_on_accepted_zero"] == 1
    assert metrics["confusion"]["0.5"]["unknown"] == 1
    assert report["excluded_uncertain_or_reference"] == ["2"]


def test_evaluation_rejects_reference_labels_stale_manifests_and_leakage():
    m, a, p = evaluation_fixture()
    a["annotations"][0]["provenance"] = "user_reference"
    assert evaluate(m, a, {"method": p})["labelled"] == 2
    with pytest.raises(ValueError, match="identities"):
        evaluate(m, a, {"method": p}, partition="heldout")
    m["recordings"][0].update(athlete_id="athlete",session_id="session")
    m["flights"][0]["partition"] = "heldout"
    a["manifest_sha256"] = fingerprint(m)
    with pytest.raises(ValueError, match="leakage"):
        evaluate(m, a, {"method": p}, partition="heldout")
    a["manifest_sha256"] = "wrong"
    with pytest.raises(ValueError, match="manifest"):
        evaluate(m, a, {"method": p})


def test_unavailable_backend_has_no_fake_accuracy_or_coverage():
    m, a, p = evaluation_fixture()
    p["inference_status"] = "unavailable"
    result = evaluate(m, a, {"sam3d": p})["methods"]["sam3d"]
    assert result["supported"] is result["tentative_only"] is None


def test_head_turns_and_arm_changes_are_not_torso_evidence():
    def joint(x, y):
        return dict(status="observed", final=dict(x=x, y=y), flags=[], visibility="unknown")
    frames = [dict(frame_index=i, timestamp_seconds=i / 60, track_state="tracked", joints={
        "left_shoulder":joint(-20, 0), "right_shoulder":joint(20, 0),
        "left_hip":joint(-10, 100), "right_hip":joint(10, 100),
        "nose":joint(500 * (-1)**i, -30), "left_wrist":joint(i * 80, -500)}) for i in range(61)]
    data = dict(source={"sha256":"hash"}, frames=frames)
    flight = dict(id="head_and_arms", nominal_start_seconds=0, nominal_end_seconds=1)
    result = baseline(data, flight, protocol())
    assert result["count"] is None  # zero also requires evidence unavailable in 2D
    assert result["candidate_count"] == 0
    assert not result["supporting_minima"]


def test_sidecar_cannot_hide_lost_frames_by_omitting_them():
    data = pose_fixture()
    data["frames"][1]["track_state"] = "lost"
    sidecar = new_sidecar(data, {}, {})
    sidecar["frames"] = [frame_record(data["frames"][i]) for i in (0, 2)]
    with pytest.raises(ValueError, match="omitted tracking loss"):
        validate(sidecar, data)


def test_clipping_and_explicit_tentative_predictions_are_not_supported():
    frames = []
    data = dict(source={"sha256":"hash"}, frames=frames)
    result = baseline(data, dict(id="clipped", nominal_start_seconds=0, nominal_end_seconds=1,
                                 start_clipped=True), protocol())
    assert result["candidate_count"] is None
    m, a, p = evaluation_fixture()
    p["predictions"][0]["status"] = "tentative"
    with pytest.raises(ValueError, match="Tentative"):
        evaluate(m, a, {"method":p})
