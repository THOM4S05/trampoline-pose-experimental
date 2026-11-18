# CSV twist-width copy

Skill analysis v12 fixes clustered inversion occlusions: direction context is
drawn from plausible continuous observations within 300 ms on each side, never
from neighbouring outages. The existing maximum 350 ms gap, unique angular arc
under the 20 rad/s bound, inversion, direction/reversal and raw-jump checks are
retained. Apparent torso-length ratios above two are rejected. Estimated arcs
are reported separately; no missing joint coordinates are reconstructed.

Body shape is selected from sustained central, elevated flight evidence for
rotating and upright skills alike. A classified held tuck/pike takes priority;
otherwise a sustained straight position takes priority over unclassified open
transition poses. This prevents landing flexion overriding a straight flight.

This folder contains a separate copy of the current source, scripts, configs,
tests and docs. Original source files are unchanged. Videos, model weights,
tracking outputs, Git metadata and virtual environments were not duplicated.
It uses the original project's Python environment; no dependencies were added.

From the original project folder, run:

```powershell
.\.venv\Scripts\python.exe experiments\twist-width-copy\scripts\analyze_twist_width.py outputs\20250405_102511\joints.csv --output-dir experiments\twist-width-copy\results\20250405_102511
```

Open `review.html` in that output folder. `skills.csv` lists candidate total
twists, `evidence.csv` contains raw and filtered shoulder/hip widths and states,
and `analysis.json` includes normal skill analysis plus the complete experiment.
The analysis uses existing contact-to-contact proposals, not verified airborne
boundaries. Those boundaries may cause abstention or include contact motion.

The copied portal also runs twist analysis when you select Run skill analysis.
Launch the isolated upload site from the original project folder with:

```powershell
.\.venv\Scripts\python.exe experiments\twist-width-copy\scripts\serve_twist.py
```

Open http://localhost:8766. Its access key is in this copy's
`.portal/access-key.txt`. Upload, choose the gymnast, start tracking, then run
skill analysis. Cards show candidate half-twist counts, reasons for unknowns,
and buttons to review each detected passage. CSV downloads include candidate
turns and half-twist counts. Candidates do not change supported skill names.
The site uses the existing model assets and environment, and stores new jobs
in this copy's `.portal` folder. No additional pose model is used for twists.

Both widths must pass from narrow to broad and back to narrow. A completed
passage contributes a candidate half twist. Each segment uses its own fixed
recording-wide 95th-percentile pixel-width reference, never instantaneous torso
length. The initial narrow/broad thresholds are .35/.65 of that reference;
states must persist for at least 15 ms and two observations. A 25 ms median
radius reduces noise without filtering through missing or long-gap observations.
These are inspectable initial heuristics, not calibrated thresholds.

Decoder v3 adds one restricted finish rule at an estimated bed touch. After
a supported broad phase, both final widths must remain below .50 of their
recording references for at least 15 ms and two observations. Each must have
fallen by at least .45 from its broad-phase peak and must not rise across that
final interval. This can complete the last pending half-turn when residual
projection prevents a strict .35 narrow state. It does not relax internal
passage boundaries, admit missing data or extend counting beyond bed touch.
Completion method and width drops are recorded for review. These thresholds
were informed by user-labelled development examples, not held-out validation.

Missing torso observations, gaps over 80 ms, sustained shoulder/hip conflict,
unestablished side-on boundaries, incomplete passages, clipped flights and
small reference widths suppress the candidate count. This deliberately strict
first version may abstain frequently. Clear non-twisting examples cannot be
assigned zero if the recording supplies no adequate width reference.

All counts remain tentative. Observed broad widths are not calibrated physical
breadths. Width does not identify front versus back, continued rotation versus
reversal, or all foreshortening/association errors. No automatic endpoint-facing
check is implemented: somersault rotation must be accounted for before screen
facing can be used as twist parity evidence. No final skill names are assigned
from twist candidates. No distribution across somersaults is estimated.

Synthetic tests check event counting, frame rates, non-twisting image-plane
somersaults, anatomical side swaps, shoulder/hip conflict, missing data and
partial windows. Where existing bed-contact evidence is available, twist
analysis ends at the estimated bed touch, excluding later compression motion.
The timestamp remains an estimate requiring review; CSV-only runs without bed
evidence retain the pose contact proxy. The start boundary is unchanged.
Real-video accuracy requires the athlete's review; merely
running the existing CSV is a smoke check, not validation.
