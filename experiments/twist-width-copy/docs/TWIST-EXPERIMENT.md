# Offline twist experiment

This is an optional research path, checked on 23 October 2026. **No dependable
real-video twist detector has been established and no production backend has
been selected.** Tracking and normal skill analysis still run without it.

The implementation supplies a pure orientation decoder, a versioned sidecar
contract, a bounded SAM 3D Body runner, a deliberately weak 2D diagnostic, native
frame review sheets and an evaluation harness. Private evidence is written to
the existing ignored `reports/twist-experiment/` directory. No recordings are
uploaded. See `DECISION.md` there for this machine's results.

## Current evidence and decision

The source audit verified SHA256 against saved joints for 13 distinct original
recordings. Four recordings supplied 24 development review windows, 1,806 native
frame panels and 36 sheets. Visual notes distinguish observed execution from
the earlier user references. There are **zero independently human-reviewed
count labels**. Fifteen provisional agent visual labels were usable for a
diagnostic comparison; nine windows retained unknown counts. No athlete/session
disjoint evaluation is possible with the available identity metadata.

The width baseline supported no counts. Of ten tentative candidates on those
15 provisionally labelled windows, six matched the visual notes and four added
false twists to zero-twist examples. Its only labelled half twist was unknown.
This is evidence against promoting that baseline, not a benchmark accuracy claim.
The multi-somersault challenge has sheets but no established full/higher twist
count. Full and higher **labelled** real-video examples remain missing.

After the initial access failure, the user supplied the three gated assets.
SAM 3D Body now runs on this GTX 1070 8 GB in a separate environment using
PyTorch 2.7.1+cu118 and an explicit float16 override (native bfloat16 is unavailable).
Two development flight windows requested 83 native frames: 79 produced finite
3D observations and four abstained because tracking was uncertain. The bounded
worker completed in 90.9 seconds, with 3.36 GiB peak allocated GPU memory and
4.43 GiB peak worker RAM. The tracker environment remains PyTorch 2.0.1+cu118.
This establishes limited runtime compatibility, not count accuracy. No calibrated
reference, independent pelvis orientation or empirical angular error bound is
available, so supported counts remain unknown. See the private
`reports/twist-experiment/MODEL-COMPATIBILITY.md` for measurements and provenance.
The earlier 24-window evaluation is still the 2D diagnostic; it was not replaced
by these two model trials. GVHMR inference has not run.

## Geometry and meaning of a count

`twist_geometry.py` uses active rotation matrices with columns **anatomical
right, anterior, superior**. Superior is an explicitly measured segment long
axis; right is the anatomical lateral vector orthogonalized to it; anterior is
`superior × right`. Reflections and degenerate landmarks are rejected.

The canonical camera is the displayed source image's OpenCV frame: x right,
y down, z forward. `video.decode()` applies source display rotation once and
retains original frame IDs, PTS and time bases. Model outputs must already be in
this camera frame. Root-relative translation and length units do not affect
orientation, but raw units must be recorded by the adapter.

For a fixed reference basis B, whose x axis is the fixed somersault reference
axis and z axis is upward, define:

```text
R = B.T @ R_body = Rx(somersault) @ Ry(tilt) @ Rz(twist)
tilt       = asin(R[0,2])
somersault = atan2(-R[1,2], R[2,2])
twist      = atan2(-R[0,1], R[0,0])
```

This is the lateral/frontal/longitudinal Cardan order described by
[Yeadon](https://isbweb.org/standards/yeadon1.html), applied here to a **segment
proxy**. Positive angles obey the right-hand rule; the optional direction is
`positive`/`negative`, not an inferred sport left/right label. With a neutral
right/anterior/superior reference, positive somersault rotates the head toward
the posterior side. A fixed reference axis must be established independently
of intended skill labels. Arbitrary camera yaw cannot replace this reference.

The extraction uses the branch `|tilt| < 90 degrees` and rejects
`|cos(tilt)| < 0.2`. Branch crossings, uncertain reference axes and highly
non-planar movement require further work. The separate `upright` branch uses
lateral heading only while every usable torso remains within 25 degrees of
upward. It rejects inverted or substantially leaning poses. It must not be used
as world-yaw counting during somersaults.

This is **not** a validated inertia-axis whole-body estimator. Pike, trunk
torsion and different segment axes can invalidate the proxy. Independent pelvis
orientation is required for conditional support and is compared with the torso
in both twist phase and longitudinal-axis direction. Disagreement above
30 degrees causes abstention. A shared torso/pelvis long axis is explicitly
insufficient. The present MHR70 adapter therefore produces orientation
candidates, not supported sport counts. Mapping the rig's independent pelvis
and upper-torso axes, including their rest frames, is an outstanding experiment.

The decoder unwraps the **twist coordinate**, never quaternion path length or
angular velocity dotted with the body axis. It retains side-assignment and
winding alternatives in a beam. Quaternion signs are equivalent. Motion is
bounded in elapsed native time; acceleration contributes a small robust ranking
cost, with no constant-speed constraint. Plausible paths discarded by the beam
cause abstention. These costs and the margin are heuristic, not probabilities.

`net_turns` is signed unrounded displacement. `absolute_rotation_turns` is the
raw sum of absolute phase increments, which is noise sensitive. A classified
`count` means the magnitude of net displacement near a half-turn multiple,
with no material reversal. When both signs accumulate more than the configured
reversal allowance, count is null and the differing quantities remain visible.
Distribution of turns across successive somersaults is not estimated.

The 6 turns/second bound, 80 ms maximum gap and other thresholds are experimental
assumptions. Angular error bounds mean bounds in the **extracted twist
coordinate**, including reference/camera uncertainty. They require independent
validation; a model's low reprojection residual or a raw SO(3) error does not
supply one, particularly near a Cardan singularity. Hidden faster motion can violate the
assumed sampling bound. `supported_conditional` describes geometry under these
assumptions, not calibrated monocular reliability. All real outputs from the
current adapter abstain until these missing evidence conditions are resolved.

## Sidecars and exports

`twist_sidecar.py` binds version `0.1.0` observations to the original SHA256 and
a canonical hash of the complete saved tracking document. Native time, source
PTS/time base, athlete ID, saved box and tracking crop must match. Tracking loss,
identity ambiguity, moving cameras and omitted loss records are rejected as
valid observations. A model never runs a second person detector.

Each observation records validity, reasons, source-to-model pixel and camera
transforms, and alternative torso/pelvis matrices with non-probabilistic costs,
angular error bounds and optional normalized reprojection residuals. Matrices
are already restored to the source camera. For a rotated crop with camera
change Q, this restoration is `R_source = Q.T @ R_crop`; undoing only its 2D
pixel affine is incorrect. The SAM runner uses the full displayed image API
and saved box, with **no extra rotated crop**. Its identity pixel/camera
transforms describe that API input, not the internal resized neural tensor;
the upstream internal crop is determined by the saved box and hashed config.

Orientation cache keys include source/tracking hashes, model provenance,
configuration, upstream Python source tree and coordinate convention. Decoder signatures include version,
settings, reference, boundary intervals and orientation input hash; decoded results are recomputed,
not reused from an unchecked result cache. Raw SAM outputs have a separate
`.raw.json` file. Conditional histories describe selected hypotheses, never
reconstructed observations through missing tracking.

Flight evidence contains nullable `count`, `candidate_count`, alternatives,
unrounded displacement, direction, method/status, temporal coverage, supporting
intervals, reasons, selected history and endpoint sensitivity. All combinations
of departure/landing interval endpoints must agree for conditional support.
Unreviewed bed estimates and contact proposals are not promoted to verified
departure/landing boundaries. Unsupported gaps prevent a whole-flight history.

## Model/API audit

The SAM adapter targets revision
`b5c765a0d89d789985e186d396315e7590887b94`; the estimator SHA256 is checked before
loading. The [official estimator source](https://github.com/facebookresearch/sam-3d-body/blob/b5c765a0d89d789985e186d396315e7590887b94/sam_3d_body/sam_3d_body_estimator.py)
accepts existing boxes, optional masks and intrinsics, and `inference_type="body"`.
NumPy images are RGB, unlike decoded BGR. Although its intrinsics annotation
says NumPy, the inspected code calls `.to()` on provided intrinsics. There is no
exposed keypoint-prompt parameter in this convenience method. CUDA transfers are
hard-coded. Its image outputs need temporal disambiguation; they are not twist
measurements. The runner does not download anything automatically.

The [MHR70 metadata](https://github.com/facebookresearch/sam-3d-body/blob/b5c765a0d89d789985e186d396315e7590887b94/sam_3d_body/metadata/mhr70.py)
places shoulders at 5/6, hips at **9/10**, neck at 69. It is not COCO17.
The [head implementation](https://github.com/facebookresearch/sam-3d-body/blob/b5c765a0d89d789985e186d396315e7590887b94/sam_3d_body/models/heads/mhr_head.py)
divides MHR positions by 100, then flips y/z for exported keypoints and joint
positions. The adapter does not repeat that flip. Exported `global_rot` is an
Euler vector; joint rotations are separate matrices and do not receive the
same camera correction in that head. Their rig rest frames are not interpreted
here. Reprojection checks compare exported 2D torso points with saved observed
points; agreement is only a consistency check.

Follow the [SAM install guide](https://github.com/facebookresearch/sam-3d-body/blob/b5c765a0d89d789985e186d396315e7590887b94/INSTALL.md)
in a separate environment. Check access to all three assets before installing
the larger stack. Source and weights use the
[SAM License](https://github.com/facebookresearch/sam-3d-body/blob/b5c765a0d89d789985e186d396315e7590887b94/LICENSE),
not this repository's license. The runner refuses inference inside the tracker
`.venv`. It checks local asset hashes and records actual dependency versions,
dtype, device and measured runtime/memory when inference succeeds. A preflight
probe is deliberately labelled as such.

[GVHMR installation](https://github.com/zju3dv/GVHMR/blob/main/docs/INSTALL.md)
specifies Python 3.10 and registered SMPL/SMPL-X assets. Its
[license](https://github.com/zju3dv/GVHMR/blob/main/LICENSE) limits use to
educational, research and nonprofit purposes. A future adapter must use the
saved athlete and assess contact/ground priors on airborne poses; the stock
demo is not an identity-safe drop-in replacement. Static-camera support does
not establish twist-count accuracy.

The [trampoline fine-tuning repository](https://github.com/VisionICLab/trampoline_syn_data)
still advertises forthcoming code. The checked
[AnyLift tree](https://github.com/awfuact/anylift/tree/3b9b2045e05121e90a9d6582a2ac42a6c2f6fb75)
contained project-page assets, not a verified inference release. Neither blocks
the local experiment. Connolly's
[2017 skill-classification result](https://arxiv.org/abs/1709.03399) is not
twist-count accuracy; our width-minima diagnostic is inspired by its projected
shoulder feature and does not reproduce its classifier.

## Reproducible commands

Run from the repository root in PowerShell. These commands use existing
lightweight dependencies and saved tracking, without rerunning pose inference.

```powershell
.\.venv\Scripts\python.exe scripts/twist_experiment.py audit --output reports/twist-experiment/inventory.json
.\.venv\Scripts\python.exe scripts/twist_experiment.py review --pose PATH_TO_JOINTS --skills PATH_TO_SKILLS --video PATH_TO_ORIGINAL --flights 2 3 --output-dir reports/twist-experiment/review
.\.venv\Scripts\python.exe scripts/twist_experiment.py run --manifest reports/twist-experiment/manifest.json --output reports/twist-experiment/baseline.json
.\.venv\Scripts\python.exe scripts/twist_experiment.py evaluate --manifest reports/twist-experiment/manifest.json --annotations reports/twist-experiment/annotations.json --predictions reports/twist-experiment/baseline.json reports/twist-experiment/sam3d-unavailable.json reports/twist-experiment/gvhmr-unavailable.json --allow-agent-review --output reports/twist-experiment/evaluation.json
```

Review emits a blank annotation template. Annotate actual execution and certainty
separately from predictions. `human_review`, `agent_visual_review` and user
references are distinct provenance values. Default evaluation admits only
explicit human-reviewed labels; the flag above intentionally requests the
provisional development diagnostic. Missing labels never become zeros. The
manifest pins the protocol before labels are scored. Held-out evaluation refuses
unknown identities or recording/athlete/session overlap between partitions.

The standard-library preflight can run with a separate Python interpreter:

```powershell
ISOLATED_PYTHON scripts/probe_twist_backend.py --model-dir models/sam-3d-body --torch-python .venv/Scripts/python.exe --network --output reports/twist-experiment/model-preflight-network.json
```

After assets, a compatible isolated environment and the audited upstream source
are available, use this **bounded**, unverified-on-this-machine command first:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
ISOLATED_PYTHON scripts/sam3d_twist.py --pose PATH_TO_JOINTS --video PATH_TO_ORIGINAL --repository PATH_TO_PINNED_SAM_REPO --backbone-repository PATH_TO_PINNED_DINOV3_REPO --checkpoint PATH_TO_MODEL_CKPT --mhr PATH_TO_MHR_MODEL_PT --precision float16 --frames 500 507 511 521 --limit 4 --output reports/twist-experiment/sam-smoke.json
```

The config must be `model_config.yaml` beside the checkpoint. Install
`requirements-twist-sam3d.txt` only into a new inference environment. DINOv3
source must also be local, with its revision recorded; no backbone weights are
downloaded implicitly. The loader uses `weights_only=True` and memory mapping
for the checkpoint, checks all learned keys and obtains fixed rig buffers from
the separately hashed TorchScript asset. TorchScript still executes model code;
a separate Python environment is not a security sandbox.

The downloaded config requests bfloat16, which the inspected GTX 1070 does not
support. `--precision float16` is an explicit experimental override, recorded
with the complete effective config. `--precision float32` is another experiment;
neither override is an accuracy or memory guarantee. The default `checkpoint`
choice refuses unsupported bfloat16 rather than falling back silently. The optional
`--full` flag permits all requested frames only after a successful smoke test;
recheck memory and outputs before using it. No automatic dtype workaround or
CPU fallback is assumed to work on Pascal hardware.

Decode a verified sidecar on one recording per invocation:

```powershell
.\.venv\Scripts\python.exe scripts/twist_experiment.py run --manifest SINGLE_RECORDING_MANIFEST --orientations ORIENTATION_SIDECAR --reference REFERENCE_JSON --output reports/twist-experiment/decoded.json
```

`REFERENCE_JSON` maps flight IDs to `{"basis_camera":[[...],[...],[...]],
"branch":"cardan"}` or `"upright"`. Choose a physically established reference,
not identity by default. No calibrated reference is supplied for the current 3D
experiment. A mock sidecar must never be reported as a model result.

## Checks and remaining work

The full local suite passed 179 Python tests, including 56 twist checks;
20 navigation and 3 video-player JavaScript tests passed. Generated sequences
cover combined somersault/tilt/twist, zero through three turns, changing tilt,
upright/inverted branches, pike disagreement, quaternion signs, camera/crop
transforms, side swaps, VFR/gaps, aliasing, reversal, source/cache mismatch and
evaluation leakage. These establish geometry and software behavior only.

Browser naming consumes supported counts; tentative seat-facing names and user
references cannot silently supply twist. Candidate/unknown values are displayed
separately. Legacy numeric and count-only exports remain readable. No optional
model stage was added to portal processing because useful count accuracy and
coverage have not yet been established.

Next, map independent torso/pelvis rig frames; establish error bounds and the fixed reference; annotate
native departure/landing intervals; and obtain independently reviewed zero,
half, full and higher counts across known athletes/sessions. Include head/arm
motion, anatomical side errors, inversion, blur, body contact and reversal.
Then compare real 3D and 2D outputs on identical frozen flights. Failures here
support keeping contacts/torso unobstructed and retaining native frame rate.
Synchronized calibrated complementary views are a stronger future measurement
experiment, with no untested two-camera accuracy guarantee.
