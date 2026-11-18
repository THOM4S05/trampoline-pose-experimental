# Experimental rotation recovery

The experimental copy combines torso orientation passages with endpoint
orientation to refine tentative somersault counts. It does not change tracking,
joint coordinates, contact boundaries, body shape, or supported rotation counts.
Feet and seat both use the upright contact rule. Front/back contacts use the
horizontal rule; unknown anatomical contact types remain unknown.

The phase counter requires sustained upright/inverted runs separated by
horizontal observations. Missing samples do not split one inversion into two.
An abrupt upright-to-inverted detector flip without a horizontal transition is
rejected. Long gaps, sustained unsupported transitions, reversal ambiguity,
partial flights, conflicting known contacts, or a phase/angle disagreement over
0.75 rotations cause abstention.

Vertical phases alternate in half-turn steps. A horizontal takeoff and/or landing
contributes the corresponding endpoint quarter. Nearby torso observations may
supply a contact-orientation proxy when the actual contact is obscured. Those
proxies, timestamps, rejected runs, and original angle estimate are exported.
They do not independently establish front versus back contact or 3D orientation.

The 40 rad/s gap bound follows the existing raw-angle veto; it is an algorithm
assumption, not a universal physical speed limit. Recovery assumes a fixed,
predominantly side-on camera and continued end-over-end rotation. All recovered
counts remain estimates needing review; supported count fields are not promoted.

The twist decoder retains its original angle-counter inputs. Phase recovery does
not change twist passages, timings, or twist counts as a side effect.

Validation includes synthetic upright/horizontal endpoint combinations at
24–240 fps, occlusions, noisy inversion duplicates, reversals and partial clips;
observed Liam torso-vector regression fixtures; and twist-regression fixtures.
`scripts/review-rotation-phases.py` replays saved clips without publishing them.
The replay report is `reports/rotation-phase-replay.json`. User annotations are
test expectations only, never inputs to rotation inference.
