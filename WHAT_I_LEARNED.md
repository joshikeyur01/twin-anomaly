# What I learned

Genuine lessons from building and breaking this repo, in the order the
stack taught them to me. Most of them are about data, not models — which
is itself the first lesson.

## Idle windows poison "normal", and that is 80% of the work

The first evaluation table was garbage, and finding out why took longer
than writing every model. Building a dataset over a wide time window swept
in the gaps *between* collection runs — minutes of no telemetry — as
thousands of empty windows, all labelled "normal" because no fault was
active. The models dutifully learned that normal operation includes empty
windows: the normal velocity band now stretched down to zero, so a *stuck*
joint (velocity ≈ 0) sat comfortably inside it, and drop-out was invisible.
Normal windows averaged **1.9 samples** instead of ~37. The fix is two
lines of principle — a dataset covers one continuous *operating* span, and
a non-fault window below half a full window's samples is absence of
operation, not normal operation (dropped by the pipeline) — but the lesson
is that in a detection system the model is the easy part. Data hygiene is
the system.

## When a baseline scores exactly 0.00, suspect the baseline

With the corpus cleaned, the rule baseline flagged *nothing* — 0.00 recall
and precision on every fault. It looked like a damning result for a naive
rule. It was a bug: the rule normalised each feature's deviation by its
band width, and a near-constant feature has a band width near zero, so a
hair of normal noise divided by ~0 became an enormous score, inflating the
1%-FPR threshold until nothing — not even drop-out — could clear it.
Scaling by robust standard deviation with a floor fixed it, and the rule
became a real baseline. A result that makes your baseline look broken
usually means it is.

## You cannot featurise data you do not have

Drop-out is the absence of telemetry, and absence fought back twice. In the
offline pipeline, windowing only spans present data, so a total drop-out
produced almost no windows to label. Live, it was worse: the scorer's
rolling window pruned by *telemetry* time (the sensible default, borrowed
from state-svc, so a paused sim doesn't decay its RMS) — but when telemetry
stops, telemetry time stops, so the window froze on the last pre-drop-out
second and scored it forever as normal. The demo missed drop-out entirely.
The fix was to prune the *live* window by wall clock instead: detecting
that a stream went silent is inherently a wall-clock event, the one place
anomaly-svc must disagree with state-svc about what "now" means.

## The model does not dominate the rule — that is the finding

At a matched 1% false-positive budget: the Isolation Forest wins friction
(0.61 vs 0.00) and stuck (0.41 vs 0.00), the rule *wins* encoder (0.47 vs
0.20), and they tie on drop-out. Neither is universally better, and the
shape is legible: the rule catches faults that shove one feature decisively
out of its band (encoder → position variance; drop-out → sample count); the
forest catches faults that keep every feature in-band but violate the joint
distribution (a quiet joint while the others move). The honest report is
"use the rule for the loud faults, the model for the subtle ones" — not
"the model won". This is the same lesson `twin-services` learned from a
latency benchmark that justified nothing: the measured non-result *is* the
result.

## Skew dies only where code is shared, not where intentions are

"Same features at training and serving" is a platitude until one package
computes them and both sides import it. `features/` and `detector/` exist
for exactly this, and the proof is the live tripwire: `POST /score` returns
`0.6685169832273326`, byte-for-byte the number the offline library computes
for the same window. Had the service re-implemented feature extraction or
thresholding "the same way", that equality would have drifted silently and
every score would have been quietly wrong.

## The threshold is where the honesty lives

Recall is only a fair axis of comparison because both detectors take their
threshold from held-out normal at the same false-positive budget. With too
few normal windows the 99th-percentile threshold is unstable — estimated
from 27 points, it sat at the near-maximum and only the loudest fault
cleared it, which read as "the models are bad" when it was "the corpus is
small". Model quality and corpus size are not separable claims.

## The demo is a test, not a screencast

Writing `just demo` to *assert* — the score must cross the threshold inside
every fault window and stay under it during normal running, non-zero exit
otherwise — turned "it looks like it's working" into "it passes or the
build breaks". It also forced an honest choice: encoder's 0.20 recall makes
it flaky to detect at low severity, so the demo injects it strongly to gate
reliably, and the real per-severity recall lives in `EVALUATION.md` rather
than being hidden behind a cherry-picked run.

## The environment is still part of the system

Every `twin-services` environment lesson recurred, plus new ones. git-lfs
wasn't installed (`brew install git-lfs`); `jupyter nbconvert` silently
runs the wrong Python unless you register the venv as a kernel and name it;
`.gitignore` must say `data/*` not `data/`, because git cannot re-include a
path inside a fully-excluded directory, and the test fixtures under
`data/fixtures/` have to ship; and the iCloud hidden-`.venv` gotcha struck
every `uv run` recipe that lacked the `_unhide` guard. "Nondeterministic"
still means "asynchronous cause".
