"""Experimental SAM 3D Body adapter. Model imports are isolated to run().

Audited upstream revision b5c765a0d89d789985e186d396315e7590887b94.
Only camera-corrected MHR70 keypoints are interpreted. The uncorrected rig
rotations and their rest frames are retained as raw data, never treated as yaw.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import os
from pathlib import Path
import platform
import sys
import time
import subprocess

import numpy as np
import psutil

from .output import sha256
from .backend import sha256_tree
from .skill_identification import usable
from .twist_geometry import segment_frame
from .twist_sidecar import frame_record, new_sidecar, validate, verify_source, verify_timing
from .video import decode

UPSTREAM_REVISION = "b5c765a0d89d789985e186d396315e7590887b94"
ESTIMATOR_SHA256 = "8bfa34316d82eabbe185c1cd64a77c47670785cdb0fa489b1481fb468266a145"
AUDITED_FILES = {
    "sam_3d_body/sam_3d_body_estimator.py": ESTIMATOR_SHA256,
    "sam_3d_body/models/heads/mhr_head.py": "03793d51ef82484c5d9906358c6314981c0bff9dbcc6f6e6b175bd977a251b35",
    "sam_3d_body/metadata/mhr70.py": "695c2c7d472e32757c480114fdb054d54ee4af53f69b2a6e040b00a55b270dc9",
    "sam_3d_body/build_models.py": "445b5408109232c770b892cbced52c34c3a104a76c685885e66963dcc349a41e",
    "sam_3d_body/models/meta_arch/sam3d_body.py": "851b7475f18b56891aa02606e7c0ee9e03120fa208cc85df5127b792e1abfeee",
}
MHR70 = dict(left_shoulder=5, right_shoulder=6, left_hip=9, right_hip=10, neck=69)


def precision_settings(requested, original_half, original_type, bf16_supported):
    """Explicit override only; never silently run unsupported checkpoint precision."""
    if requested == "checkpoint":
        half, kind = bool(original_half), original_type
    elif requested in ("float16", "float32"):
        half, kind = requested == "float16", "float16"
    else:
        raise ValueError("Unknown model precision")
    if half and kind == "bfloat16" and not bf16_supported:
        raise RuntimeError("Checkpoint requests bfloat16, unsupported by this GPU; choose an explicit experimental --precision")
    return half, kind


def load_checkpoint_state(model, state):
    """Require every learned weight; fixed MHR buffers come from the hashed .pt."""
    incompatible = model.load_state_dict(state, strict=False)
    # The released checkpoint omits the zero training-mask token and two unused
    # hand-PCA snapshots. Audited source initializes these; body inference does
    # not consume the hand snapshots or apply an input mask.
    noninference = {"backbone.encoder.mask_token", "head_pose.hand_pose_comps_ori",
                    "head_pose_hand.hand_pose_comps_ori"}
    missing = [name for name in incompatible.missing_keys if ".mhr." not in name and name not in noninference]
    if missing or incompatible.unexpected_keys:
        raise RuntimeError(f"Learned checkpoint mismatch: missing={missing}; unexpected={incompatible.unexpected_keys}")
    return dict(missing_fixed_mhr_buffers=[name for name in incompatible.missing_keys if ".mhr." in name],
                missing_known_noninference_keys=[name for name in incompatible.missing_keys if name in noninference],
                unexpected_keys=[])


def load_local_model(torch, args, config_path):
    """Audited model construction with pinned local backbone and weights-only loading.

    TorchScript MHR still executes model code; this is not a security sandbox.
    All changes from the upstream convenience loader are explicit in provenance.
    """
    from sam_3d_body.models.meta_arch import SAM3DBody
    from sam_3d_body.utils.config import get_config
    cfg = get_config(str(config_path))
    half, kind = precision_settings(args.precision, cfg.TRAIN.USE_FP16,
                                    cfg.TRAIN.get("FP16_TYPE", "float16"),
                                    torch.cuda.is_bf16_supported(including_emulation=False))
    cfg.defrost()
    cfg.TRAIN.USE_FP16 = half
    cfg.TRAIN.FP16_TYPE = kind
    cfg.MODEL.MHR_HEAD.MHR_MODEL_PATH = str(args.mhr.resolve())
    cfg.freeze()
    original_hub_load = torch.hub.load
    original_jit_load = torch.jit.load

    def logged_rig_load(*values, **options):
        print("Loading the local MHR TorchScript asset", flush=True)
        rig = original_jit_load(*values, **options)
        print("MHR TorchScript asset loaded", flush=True)
        return rig

    def local_backbone(repo, name, *values, **options):
        if repo != "facebookresearch/dinov3" or options.get("pretrained", True):
            raise RuntimeError("Unexpected backbone download/model request")
        # Import only the required backbone, avoiding unrelated hubconf detector,
        # depth and text heads and their optional training dependencies.
        sys.path.insert(0, str(args.backbone_repository.resolve()))
        from dinov3.hub import backbones
        options.pop("source", None)
        return getattr(backbones, name)(*values, **options)

    torch.hub.load = local_backbone
    torch.jit.load = logged_rig_load
    try:
        print(f"Constructing model with explicit precision {args.precision}", flush=True)
        model = SAM3DBody(cfg)
    finally:
        torch.hub.load = original_hub_load
        torch.jit.load = original_jit_load
    # Transfer before mapping the checkpoint to avoid keeping a full CPU model
    # and checkpoint resident together on machines with limited system RAM.
    model = model.to("cuda")
    print("Reading checkpoint weights (weights_only=True, mmap=True)", flush=True)
    checkpoint = torch.load(str(args.checkpoint), map_location="cpu", weights_only=True, mmap=True)
    state = checkpoint["state_dict"] if "state_dict" in checkpoint else checkpoint
    model._twist_checkpoint_audit = load_checkpoint_state(model, state)
    del state, checkpoint
    model = model.eval()
    return model, cfg


def adapt_prediction(prediction, original):
    """MHR70 is NOT COCO17: hip indices are 9/10, not 11/12.

    Source head divides MHR coordinates by 100 then flips y,z into camera space.
    Do not apply this flip again. Matrices remain in the DISPLAYED camera frame.
    MHR70 alone lacks an independent pelvis superior axis: explicit abstention.
    """
    points = np.asarray(prediction["pred_keypoints_3d"], dtype=float)
    pixels = np.asarray(prediction["pred_keypoints_2d"], dtype=float)
    if points.shape != (70, 3) or pixels.shape != (70, 2) or not np.isfinite(points).all() or not np.isfinite(pixels).all():
        raise ValueError("Unexpected/nonfinite MHR70 output; upstream API may have changed")
    ls, rs, lh, rh = [points[MHR70[name]] for name in ("left_shoulder", "right_shoulder", "left_hip", "right_hip")]
    shoulder, hip = (ls + rs) / 2, (lh + rh) / 2
    torso = segment_frame(ls, rs, hip, shoulder)
    pelvis_proxy = segment_frame(lh, rh, hip, shoulder)
    errors = []
    observed = {name: usable(original, name) for name in ("left_shoulder", "right_shoulder", "left_hip", "right_hip")}
    if all(p is not None for p in observed.values()):
        length = np.linalg.norm((observed["left_shoulder"] + observed["right_shoulder"]
                                 - observed["left_hip"] - observed["right_hip"]) / 2)
        if length > 10:
            errors = [np.linalg.norm(pixels[MHR70[name]] - p) / length for name, p in observed.items()]
    residual = float(np.sqrt(np.mean(np.square(errors)))) if errors else None
    # Both anatomical side assignments are retained. Reprojection does not resolve depth.
    swap = np.diag([-1., -1., 1.])
    hypotheses = [dict(torso_matrix=(torso @ side).tolist(), pelvis_matrix=(pelvis_proxy @ side).tolist(),
        pelvis_independent=False, side_assignment=label, cost=0., angular_uncertainty_rad=None,
        reprojection_error_torso_lengths=residual)
        for side, label in [(np.eye(3), "model_assignment"), (swap, "anatomical_side_alternative")]]
    return frame_record(original, valid=True, hypotheses=hypotheses,
        reasons=["monocular_depth_and_side_assignment_unverified", "pelvis_longitudinal_axis_shared_with_torso"],
        units="metres_from_upstream_head", camera_coordinates="displayed image x-right y-down z-forward")


def run(args):
    from .twist_experiment import read_json, write_json
    data = read_json(args.pose)
    verify_source(data, args.video)
    estimator_path = args.repository / "sam_3d_body/sam_3d_body_estimator.py"
    for name, expected in AUDITED_FILES.items():
        path = args.repository / name
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"Use the audited SAM repository revision; source hash differs: {name}")
    config_path = args.checkpoint.parent / "model_config.yaml"
    assets = dict(checkpoint=args.checkpoint, config=config_path, mhr=args.mhr)
    missing = [str(p) for p in assets.values() if not p.is_file()]
    if missing:
        raise FileNotFoundError("Gated local model assets required: " + ", ".join(missing))
    # No downloads and no changes to the tracking environment.
    if Path(sys.prefix).resolve() == (Path(__file__).resolve().parents[2] / ".venv").resolve():
        raise RuntimeError("Run SAM inference in a separate environment, not the tracker .venv")
    sys.path.insert(0, str(args.repository.resolve()))
    # This adapter uses the supplied hashed TorchScript rig, never a separately
    # installed Momentum package with a different asset search path.
    os.environ["MOMENTUM_ENABLED"] = "0"
    import torch
    from sam_3d_body import SAM3DBodyEstimator
    if not torch.cuda.is_available():
        raise RuntimeError("Audited convenience estimator requires CUDA; CPU inference is unverified")
    started = time.perf_counter()
    torch.cuda.reset_peak_memory_stats()
    if not (args.backbone_repository / "hubconf.py").is_file():
        raise ValueError("Local DINOv3 source is required; refusing an implicit torch.hub download")
    torch.set_num_threads(4)
    model, cfg = load_local_model(torch, args, config_path)
    estimator = SAM3DBodyEstimator(model, cfg, human_detector=None)
    provenance = dict(backend="sam-3d-body", upstream_revision=UPSTREAM_REVISION,
        estimator_sha256=sha256(estimator_path), python_source_tree_sha256=sha256_tree(args.repository / "sam_3d_body"),
        adapter_source_sha256=sha256(Path(__file__)),
        geometry_source_sha256=sha256(Path(__file__).with_name("twist_geometry.py")),
        tracking_usability_source_sha256=sha256(Path(__file__).with_name("skill_identification.py")),
        backbone_revision=subprocess.check_output(["git", "-C", str(args.backbone_repository), "rev-parse", "HEAD"], text=True).strip(),
        backbone_source_sha256=sha256_tree(args.backbone_repository / "dinov3"),
        checkpoint_key_audit=model._twist_checkpoint_audit,
        mhr_joint_names=list(getattr(model.head_pose.mhr, "joint_names_list", [])),
        assets={name:dict(path=str(p.resolve()), sha256=sha256(p)) for name, p in assets.items()},
        python=sys.version, platform=platform.platform(), device=torch.cuda.get_device_name(),
        compute_capability=list(torch.cuda.get_device_capability()),
        dependencies={name:importlib.metadata.version(name) for name in (
            "torch", "torchvision", "numpy", "scipy", "opencv-python", "av", "psutil",
            "pytorch-lightning", "torchmetrics", "timm", "roma", "yacs", "omegaconf", "einops")},
        license_url="https://github.com/facebookresearch/sam-3d-body/blob/" + UPSTREAM_REVISION + "/LICENSE")
    configuration = dict(inference_type="body", dtype=str(model.backbone_dtype),
        rig_backend="local TorchScript; MOMENTUM_ENABLED=0",
        precision_override=args.precision, effective_config=cfg.dump(), checkpoint_loader="weights_only=True; mmap=True; learned keys strict; fixed MHR buffers from hashed asset",
        backbone_loader="pinned local source; pretrained=False; no implicit downloads",
        existing_boxes_only=True, additional_crop_rotation_degrees=0, masks=False, intrinsics="upstream_default_unverified",
        frame_indices=args.frames, limit=args.limit, full=args.full)
    result = new_sidecar(data, provenance, configuration)
    targets = set(args.frames) if args.frames else set(f["frame_index"] for f in data["frames"])
    if not targets.issubset({f["frame_index"] for f in data["frames"]}):
        raise ValueError("Requested native frame ID is not in tracking")
    if not args.full:
        targets = set(sorted(targets)[:args.limit])
    originals = {f["frame_index"]: f for f in data["frames"]}
    raw = []
    previous_target = None
    for timing, image in decode(args.video, data["source"]):
        index = timing["frame_index"]
        if index not in targets:
            continue
        original = originals[index]
        # Sparse smoke targets may bracket a loss. Retain that loss explicitly
        # so a decoder cannot accidentally bridge it after importing the sidecar.
        if previous_target is not None:
            for missing_index in sorted(i for i in originals if previous_target < i < index):
                skipped = originals[missing_index]
                if skipped["track_state"] != "tracked":
                    result["frames"].append(frame_record(skipped, reasons=["tracking_loss_between_smoke_targets"]))
        previous_target = index
        verify_timing({**timing, "track_id": original.get("track_id")}, original)
        if original["track_state"] != "tracked" or original.get("bbox_xyxy") is None or original.get("diagnostics", {}).get("possible_identity_ambiguity"):
            record = frame_record(original, reasons=["tracking_unavailable_or_ambiguous"])
        else:
            print(f"Inferring native frame {index} at {timing['timestamp_seconds']:.6f}s", flush=True)
            frame_started = time.perf_counter()
            predictions = estimator.process_one_image(np.ascontiguousarray(image[:, :, ::-1]),
                bboxes=np.asarray([original["bbox_xyxy"]], dtype=np.float32), inference_type="body")
            frame_elapsed = time.perf_counter() - frame_started
            if len(predictions) != 1:
                record = frame_record(original, reasons=["backend_output_not_single_tracked_athlete"])
            else:
                prediction = predictions[0]
                raw.append(dict(**timing, prediction={k:np.asarray(v).tolist() for k, v in prediction.items()
                    if k in ("pred_keypoints_3d", "pred_keypoints_2d", "pred_cam_t", "global_rot", "pred_global_rots", "pred_joint_coords")}))
                try:
                    record = adapt_prediction(prediction, original)
                except ValueError as exc:
                    record = frame_record(original, reasons=[str(exc)])
            record["inference_seconds"] = frame_elapsed
        result["frames"].append(record)
        targets.remove(index)
        if not targets:
            break
    if targets:
        raise ValueError("Not all requested frames decoded")
    torch.cuda.synchronize()
    rss = psutil.Process().memory_info()
    result["runtime"] = dict(wall_seconds=time.perf_counter() - started,
        process_peak_rss_bytes=getattr(rss, "peak_wset", rss.rss),
        gpu_peak_allocated_bytes=torch.cuda.max_memory_allocated(), gpu_peak_reserved_bytes=torch.cuda.max_memory_reserved())
    validate(result, data)
    write_json(args.output.with_suffix(".raw.json"), dict(provenance=provenance, frames=raw))
    write_json(args.output, result)
    print(f"Wrote {len(result['frames'])} real model observations to {args.output}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pose", "video", "repository", "checkpoint", "mhr", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--backbone-repository", type=Path, required=True, help="Pinned local DINOv3 source")
    parser.add_argument("--precision", choices=["checkpoint", "float16", "float32"], default="checkpoint")
    parser.add_argument("--frames", type=int, nargs="+")
    parser.add_argument("--limit", type=int, default=8, help="Bounded smoke test; full videos require --full")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be positive")
    started = time.perf_counter()
    try:
        run(args)
    except Exception as exc:
        from .twist_experiment import write_json
        rss = psutil.Process().memory_info()
        failure = dict(inference_status="not_completed", error_type=type(exc).__name__, error=str(exc),
                       wall_seconds=time.perf_counter() - started,
                       process_peak_rss_bytes=getattr(rss, "peak_wset", rss.rss),
                       gpu_peak_allocated_bytes=None, no_predictions_exported=True)
        torch = sys.modules.get("torch")
        if torch is not None and torch.cuda.is_available():
            failure["gpu_peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
        write_json(args.output.with_suffix(".failure.json"), failure)
        raise


if __name__ == "__main__":
    main()
