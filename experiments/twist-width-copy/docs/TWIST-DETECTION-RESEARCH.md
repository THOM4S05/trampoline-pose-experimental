# Twist detection research and implementation recommendation

Research checked 23 October 2026. This is a design recommendation, not a tested detector. No model was installed or benchmarked during this research.

## Recommendation

For existing single-camera footage, implement an optional, offline, video-informed 3D torso-orientation stage and an uncertainty-aware temporal twist decoder. Benchmark SAM 3D Body first, with GVHMR as a contrasting temporal baseline if feasible. Keep a cheap 2D evidence baseline to measure whether 3D actually helps. Choose the production backend using held-out twist-count results, not published mesh accuracy or attractive overlays.

For future capture where accuracy takes priority over using one camera, synchronized calibrated views provide a stronger measurement route. A second complementary view helps resolve depth and occlusion; more views can improve redundancy. This is a separate capture mode, not a prerequisite for useful single-camera experiments. The recent trampoline study evaluates three to eight cameras, so it does not establish a two-camera accuracy guarantee.

## Findings from primary sources

### Direct trampoline evidence

[Connolly et al., 2017](https://arxiv.org/pdf/1709.03399) use normalized projected shoulder separation as a twist feature within a reference-based skill classifier. They report 80.7% skill identification on 714 examples across 20 classes. This is not isolated twist-count accuracy. Shoulder separation is useful evidence but cannot alone distinguish chest from back, rotation direction, or hidden cycles. Treat this as a reproducible baseline, not an accuracy solution.

[Drolet-Roy et al., revised August 2026](https://arxiv.org/html/2604.01322v2) directly study extreme trampoline poses and fine-tune ViTPose-S using real sports and synthetic trampoline images. They report an average 42.7% reduction in triangulated 3D joint error. This is multi-view joint reconstruction, not monocular twist-count validation. Anatomical-side errors remain especially relevant. Their linked [repository README](https://github.com/VisionICLab/trampoline_syn_data) currently says code will be available soon. Do not assume downloadable trained assets exist.

### Image-based 3D candidate: SAM 3D Body

The [paper](https://arxiv.org/abs/2602.15989) describes full-body mesh recovery with optional keypoint/mask prompts and a focus on unusual poses. The official [estimator source](https://github.com/facebookresearch/sam-3d-body/blob/main/sam_3d_body/sam_3d_body_estimator.py) accepts existing bounding boxes and optional masks/intrinsics, and exports 3D joints and rotations. These interfaces make it a practical first experiment with this project's existing athlete tracking. Verify actual conventions and released prompt support rather than assuming every paper feature exists in the convenience API.

Independent frame estimates need temporal disambiguation. [SAM-Body4D](https://arxiv.org/html/2512.08406v1) explicitly addresses temporal inconsistency and occlusion when applying image HMR to video. It is a possible later comparison, not a necessary dependency: this project already has single-athlete identity tracking. Its reported temporal improvements are not trampoline twist-count evidence.

The official [installation guide](https://github.com/facebookresearch/sam-3d-body/blob/main/INSTALL.md) requires checkpoint access through Hugging Face. Inspect the [SAM License](https://github.com/facebookresearch/sam-3d-body/blob/main/LICENSE) and asset terms before integration. Do not assume a permissive license from the MHR rig applies to every model component. Compatibility and memory use on the GTX 1070 are unverified. In particular, check dtype/device assumptions; the inspected estimator contains a hard-coded CUDA transfer.

### Temporal comparison: GVHMR

[GVHMR](https://github.com/zju3dv/GVHMR) estimates video-based motion in gravity-view coordinates and supports a static-camera mode that skips visual odometry. Its temporal model is useful as a different source of orientation evidence. World translation is not itself needed to count torso twists.

Its [installation instructions](https://github.com/zju3dv/GVHMR/blob/main/docs/INSTALL.md) use a separate Python 3.10 environment and registered SMPL/SMPL-X assets. Its [requirements](https://github.com/zju3dv/GVHMR/blob/main/requirements.txt) pin a different PyTorch stack from this project. The [source license](https://github.com/zju3dv/GVHMR/blob/main/LICENSE) restricts use to educational, research and nonprofit purposes. Evaluate its treatment of airborne poses and any contact/ground correction rather than assuming ordinary locomotion priors work on a trampoline.

### Relevant emerging alternative: AnyLift

[AnyLift, CVPR 2026](https://arxiv.org/html/2604.17818v1) specifically studies gymnastics and martial-arts video reconstruction from 2D trajectories. Its gymnastics evaluation uses reprojection and motion-distribution metrics rather than ground-truth twist counts. The linked [repository](https://github.com/awfuact/anylift) currently contains project-page assets, not a verified runnable inference release. Monitor availability; do not make implementation depend on it.

## Correct rotation geometry matters

[Yeadon's whole-body orientation convention](https://isbweb.org/standards/yeadon1.html) separates somersault, tilt and twist using successive lateral, frontal and longitudinal rotations. Implement and document an explicit convention, including the reference somersault axis and signs. Derive the chosen matrix decomposition and verify it on generated known rotations before applying it to model estimates.

Use rotation matrices/quaternions internally and unwrap a supported twist-angle sequence across time. Root/pelvis rotation alone is not necessarily whole-body orientation, especially in a pike or when upper and lower torso rotate differently. Compare torso and pelvis estimates, flag disagreement, and justify the operational body frame.

Do not count world yaw, 2D shoulder crossings, endpoint facing, a quaternion's final orientation, or the accumulated shortest quaternion distance as twist turns. A full turn can finish at its initial orientation. Likewise, integrating angular velocity projected onto the longitudinal body axis is not generally identical to the twist coordinate under simultaneous somersault and tilt. Parallel-transport/swing-twist alternatives need their own convention and validation; they are not automatically equivalent to sport twist counts.

Upright jumps need a suitable separate heading treatment because a somersault reference axis may be unobservable. Handle coordinate singularities and degenerate projected axes explicitly. Uncertain boundaries, missing frames, temporal aliasing and side-label ambiguity can make several turn counts observationally compatible.

## Project fit

- `backend.py` provides RTMDet/ViTPose 2D inference; preserve it initially.
- `video.py` preserves native source presentation timestamps and display rotation. Reuse it; never fabricate constant-rate timestamps for VFR input.
- `skill_identification.py` currently exports `twist="deferred"`. Its seat-transition facing estimate is tentative evidence and must not silently become a supported general twist count.
- `bed_contact.py` supplies separate source-video contact evidence. Use supported flight windows when available, and test sensitivity to boundary uncertainty; bed deformation is not automatically an exact departure timestamp.
- `web/skills.js` already understands a numeric twist or an object with `count`. Preserve unknown values and distinguish candidate from supported counts.
- `reports/hardware.json` records Windows 10, a GTX 1070 with 8 GB VRAM and about 16 GB RAM. Recheck live hardware before installing. Main project dependencies target Python 3.11 and historical inference runs used PyTorch 2.0.1/CUDA 11.8.
- The checkout has extensive existing uncommitted work. Preserve it.

Keep model inference in a separate environment/process and exchange versioned sidecar data. Cache with source hash, native frame/PTS identity, pose/crop provenance, model and configuration hashes, coordinate conventions and decoder version. Do not upgrade the working tracking environment to satisfy another model.

## Evaluation and rollout

Start with the local `20250405_102511` routine: existing user references include a Barani and half twist from seat to feet, alongside negative examples. These are development labels with proposed alignment, not independent ground truth. Verify native-frame alignment and visually audit actual execution before evaluating. Do not train or threshold-tune on labels later reported as held-out results.

Build an annotation manifest that records actual total turns, direction if clear, departure/landing intervals, uncertain labels and visible intermediate orientation. Include zero, half, full and higher twists, twisting and non-twisting somersaults, seat/body contacts, left/right label failures, blur, occlusion, clipped flights, reversed twist and different viewpoints. Split by athlete and recording session, keeping every crop/augmentation of one source sequence in one partition.

Report exact-count confusion, false twists on non-twisting flights, half-turn errors, supported prediction coverage, accuracy among accepted predictions, and accuracy/coverage curves. Keep total count separate from distribution across somersaults. Include runtime and peak memory. If enough independent data are unavailable, explicitly report a development-only result.

Implement a small testable orientation decoder and review artifacts first. Then compare real model outputs, inspect failures, and select a backend. Only then integrate an optional experimental portal stage. If monocular evidence cannot support the requested accuracy at useful coverage, recommend improved capture or calibrated multi-view acquisition instead of forcing confident counts.
