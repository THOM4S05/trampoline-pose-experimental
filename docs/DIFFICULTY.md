# Flight difficulty

Uses [FIG TRA Code of Points 2025–2028](https://www.gymnastics.sport/publicdir/rules/files/en_1.1%20-%20TRA%20Code%20of%20Points%202025-2028.pdf), §17.1.1–17.1.6, published July 2025. Applies to trampoline, including synchronised trampoline.

| Component | Rule |
| --- | --- |
| Somersault | Complete totals: single 0.5, double 1.0, triple 1.6, quadruple 2.2. Add 0.1 per remaining quarter. |
| Twist | 0.1 per half twist. |
| Position | Pike/straight: +0.1 for untwisted 360–630°; +0.1 per complete somersault from 720°. |
| Backward bonus | +0.1 at 720–990°, +0.2 at 1080–1350°, +0.3 at 1440°. |
| Twist bonus | Doubles: +0.1 per half twist beyond two twists. Triples: +0.2 per half twist beyond one twist. Quadruples: +0.2 per half twist. |
| No rotation | Tuck/pike/straddle jump or seat drop: 0.1. Straight bounce: 0.0. |

The calculator sums components in integer tenths. Inputs are quarter somersaults and half twists, not raw angles. It supports up to four somersaults; missing inputs block a result when they affect its value.

Detected flights always receive provisional values. Candidate inputs are recorded explicitly. Partial flights receive no value. Unknown twist never becomes zero. Reference annotations never supply scoring inputs.

Body position currently comes from the existing projected shape detector. Its selected window does not establish the least difficult recognised position across an entire multiple somersault; review mixed shapes before accepting the estimate.

These are individual element values. Routine credit requires separate checks for repetitions, interruptions, counting elements, age restrictions/caps and exercise bonuses. Twist phase is needed to distinguish repeated skills. A sum of all detected flights is not an official routine D score.

Implementation: `src/trampoline_pose/difficulty.py`, mirrored in the twist experiment. Analysis responses calculate values for existing saved flights without changing their detections. New analysis JSON and portal CSV exports include difficulty. Restart a running portal to load the updated Python code.
