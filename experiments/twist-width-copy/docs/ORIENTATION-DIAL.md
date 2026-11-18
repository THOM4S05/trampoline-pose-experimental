# Frame-synced orientation dial

The experimental inbox and Skill Analysis pages show a compact dial directly
below the review player. It is available for existing tracked jobs without
rerunning pose tracking or skill analysis.

Two simple arrow hands rotate with the image-plane hip-centre-to-shoulder-centre
axis: 0° upright, 90° leaning right, 180° inverted, 270° leaning left. This is
the same torso-axis geometry used by rotation evidence; it displays the
per-frame measurement rather than the analyzer's resampled/smoothed angle.

The long arrow points towards the shoulders and the shorter arrow towards the
hips, like two clock hands on one body axis. The dial is 76 px across, without
readouts or width bars. Its accessible label retains the frame time and angle.
The hands show image-plane tilt rather than an inferred 3D heading.

The authenticated `/api/jobs/<job-id>/orientation` endpoint returns a compact
trace with original frame indices and presentation timestamps. It contains no
source file paths or full joint exports. Up to three traces are cached, keyed
by the joint export's modification time and size, so a tracking rerun invalidates
the cache. The dial works even before skill analysis is run.

Playback uses displayed-frame callbacks where supported, with an animation
fallback. Paused seeking and frame stepping also update the dial. The selected
source frame is the last presentation timestamp at or before the video time;
there is no nominal-frame-rate calculation or interpolation across missing
poses. Switching clips cancels/ignores stale requests and clears prior evidence.
Uncertain tracks, missing torso points, crop-edge exclusions and a collapsed
torso axis hide the needle instead of retaining an old angle.

Verification: 249 Python tests pass, including angle conventions, missing-pose
handling, VFR timestamps, endpoint privacy and cache invalidation. All 36 player,
skill-navigation and orientation JavaScript tests pass, including playback,
seeking and clip-switch races. The live experimental page, JavaScript asset and
orientation endpoint were checked on IMG_3386 (653 samples, approximately 50 kB).
An interactive visual preview was unavailable because local browser use is
disabled in Work settings. No main-portal files or results were modified.
