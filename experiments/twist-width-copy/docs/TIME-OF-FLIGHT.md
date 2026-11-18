# Bed contact and flight timing

The app detects the **start of visible bed deformation** from the original
video. Each skill shows a landing time, a source frame, a review interval, and
**Jump to landing**, which pauses the video at that frame. Pose segmentation
boundaries remain separate from the new landing evidence.

The detector locates the bed using an observed approach, selects an airborne
reference frame, and registers source frames against stationary background
features. It measures changes in the bed on either side of the athlete. A
continuous baseline-to-quadratic fit estimates the onset of deformation before
maximum compression. Inconsistent sides, insufficient registration, large
gaps, weak changes, and overly uncertain fits produce no detection.

Bed recovery is analysed separately for a release estimate. When both release
and the following landing are supported, their difference provides estimated
flight time and a range. Release is less reliable because an unloaded bed can
oscillate; review the feet leaving the bed. Partial or unsupported intervals
have no flight-time value. Body velocity is no longer used as a fallback.

Timing uses original presentation timestamps, including variable-rate footage.
Video hashes and timestamps must match the pose export. Three decimals do not
imply millisecond accuracy. The review interval is a heuristic sensitivity
range, not a calibrated confidence interval. Results are not competition scores.

## Validation

Tests cover known onset at 30, 60, and 240 fps; irregular timestamps; missing
frames; static beds; baseline drift; camera translation; an independently
moving person; source mismatch; caching; and seeking the landing frame.

Native-frame sequences were inspected in two development clips: all six
complete approaches in `IMG_2015.MP4` and five in `IMG_2010.mov` produced landing
candidates. The latter's opening contact lacks a pre-contact baseline and is
omitted. Example detections (zero-based source frames):

| Clip | Frame | Detected landing | Previous pose proxy |
|---|---:|---:|---:|
| IMG_2015.MP4 | 322 | 1.342500 s | 1.380000 s |
| IMG_2015.MP4 | 705 | 2.938750 s | 2.930417 s |
| IMG_2010.mov | 352 | 1.467083 s | 1.542083 s |
| IMG_2010.mov | 1060 | 4.418333 s | 4.501667 s |

These clips informed development, not independent accuracy validation. Exact
first touch can remain ambiguous due to occlusion, blur, and the delay before
deformation becomes visible away from the foot.

## Running

Portal analysis reads the source video automatically. For the CLI, pass
`--video path/to/source.mp4` to `scripts/identify_skills.py`. Pose-only analysis
reports unavailable flight timing.

`python scripts/add-flight-times.py` upgrades completed local analyses without
rerunning tracking or changing identities. Old JSON/CSV files are backed up
under `.portal/flight-time-backups`. `--job ID` limits updates to one recording.
`--redo` reapplies cached measurements; removing a job's `bed-motion.json`
requests fresh video measurement.

JSON/CSV expose `landing_contact`, `time_of_flight_seconds`, and `time_of_flight`.
JSON also includes `bed_timing` method and source metadata.
