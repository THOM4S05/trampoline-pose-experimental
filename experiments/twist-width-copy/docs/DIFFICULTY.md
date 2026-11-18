# Estimated flight difficulty

The flight card calculates difficulty from its best available rotation, body
shape and twist estimates. Positive detected twist passages can supply the
twist total even when the decoder marks the count as uncertain. Explicit
candidate totals are also usable. Missing twist evidence is not assumed zero.

Shape uses the displayed execution position, falling back to body position.
Rotation uses the measured total, falling back to the candidate total.
Partial flights and contact conflicts retain an estimated score when these
descriptors are available; their warnings remain in the result.

Values appear as a single score, such as `1.3`, under Difficulty. No explanation
or component breakdown is shown. Takeoff/landing metadata, clipping and contact
checks do not gate the estimate. A nonrotating flight uses its shape alone.
The somersault direction is part of the rotation estimate. These are element
values under FIG TRA 2025–2028, before routine credit and eligibility checks.
The source and inputs are recorded in the difficulty JSON. Existing saved
flights are scored when the analysis response is loaded; rerunning tracking
is unnecessary. Restart the experimental server to load Python changes.
