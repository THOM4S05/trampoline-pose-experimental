# Bed-contact recovery for Random Insta Video

Experimental analysis version 13 / bed measurement version 4, 8 November 2026.
Job `82ca1f7b2df443ffb10eeb3fad06f6cc` keeps its existing source, pose tracking
and review video. The main portal is unchanged.

The old bed search band was y=995–1081, across the red seating, because it used
ankles from a fast approach as the bed height. The corrected routine-wide lower
ankle envelope and robust torso scale place the band at y=1126–1238. Bed motion,
rather than those ankle positions, supplies the contact timing.

The detector now searches paired motion in both visible bed strips across the
processed clip, excluding the athlete dynamically. Candidate motion must have
near-bed pose support and agreeing deformation onsets. Single-sided movement,
linear camera drift and scene-cut lockouts cannot create independent contacts.
Fresh nearby unloaded-bed references recover registration during the late pan.
Existing pose proposals can retain one-sided timing evidence; independent new
contacts require both strips. A low stopping jump can use visibly clear feet
to select its reference even when the hips never rise far above the bed.

Video-discovered contacts rebuild the flight spans and recompute their shape
and rotation evidence. They do not create or interpolate missing joint points.
Cached video measurements are invalidated by algorithm version, source hash,
pose hash or seed-contact changes.

The refreshed clip has **14 estimated bed contacts**, up from zero, including
seven contacts absent from the pose proposal list. These produce 15 displayed
spans including the opening/trailing partial fragments. Every landing was
reviewed against its preceding, selected and following native frames in:

- `results/instagram-tracking/bed-v4-review-1.jpg`
- `results/instagram-tracking/bed-v4-review-2.jpg`

The final stopping contact is estimated at 24.267 s with a wider review interval
of 24.233–24.384 s. Its two bed strips agree, but the wider interval is retained
explicitly rather than presented as precise first-touch truth. All timings
remain source-video estimates requiring review; some release timings remain
unresolved, so not every time-of-flight value is available.

Original skill results, bed cache, job metadata and preview images are backed
up under `results/instagram-tracking/before-bed-v4/`. Updated JSON, CSV and all
15 preview records are saved in the experimental job. Its running authenticated
API returns analysis version 13 and all 14 landing records.

Verification: all 265 Python tests pass. New regressions cover the misplaced
approach band, independently discovered bed contacts, rejection of one-sided
motion/camera drift, flight-span rebuilding and explicit stopping-contact
uncertainty. Read-only reanalysis of the half/full/1½ straight-jump examples
retains their existing counts.
