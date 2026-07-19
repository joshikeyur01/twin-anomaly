# Vision

## Why this repo exists

`twin-services` decomposed the UR5 twin into contracted services and proved
the stack degrades gracefully. `twin-aas` measured what information models
cost. Both answer the same question — *how do I represent and move the
asset's state?* Neither touches the question that makes twins worth their
hosting bill: **is the asset behaving as it should?**

The thesis's service taxonomy puts anomaly detection in the first tier of
*value-adding* twin services — services that consume the twin rather than
constitute it. I can't rank that tier credibly until I've paid its costs
myself: labelled data is scarce until you make it, feature engineering is a
long series of small unglamorous decisions, models have a lifecycle that
outlives any notebook, and there is always the embarrassing possibility that
a three-line threshold rule matches your autoencoder.

This repo extends the `twin-services` stack with three new components:

- **`fault-injector/`** — a ROS 2 node that applies parameterised faults to
  the simulated arm on command: joint-friction spike, encoder noise, stuck
  joint, comms drop-out. Ground truth by construction — every fault window
  is labelled at the moment it is created, not reconstructed afterwards.
- **`data-pipeline/`** — batches InfluxDB telemetry into labelled parquet
  windows: the explicit boundary where the streaming world ends and the ML
  world begins.
- **`services/anomaly-svc/`** — loads a trained, versioned model artefact
  (Isolation Forest first, then an LSTM autoencoder) and exposes
  `POST /score`. The first L4 service that *consumes* the twin instead of
  constituting it.

The one-sentence version: **`twin-services` knows what the arm is doing;
this repo knows when that's wrong.**

## What "done" looks like

- `just up` brings up the inherited stack plus `anomaly-svc`, which answers
  `/healthz` (liveness and readiness, distinctly) and `/metrics` like every
  service before it.
- `just inject <fault>` applies a parameterised fault to the running sim and
  writes the label to InfluxDB alongside the telemetry it corrupts. Ground
  truth is recorded at injection time — never inferred later.
- `just dataset` reproducibly turns InfluxDB telemetry into labelled parquet
  windows. Same raw data in, same windows out; the notebook never queries
  InfluxDB directly.
- Notebooks in `notebooks/` train both models end-to-end from those parquet
  files and are re-runnable top to bottom. Artefacts land in `models/`,
  versioned with git-lfs; `anomaly-svc` loads a *pinned* version, never
  "latest".
- Grafana overlays the anomaly score and alert state on the joint traces.
  The README GIF: arm running normally, fault injected, score crosses the
  threshold, the panel flags it — within seconds, on one screen.
- Both models and a deliberately naive threshold-rule baseline are evaluated
  on the same held-out fault windows, per fault type, with precision and
  recall in a table. If the rule wins on a fault type, the table says so.
- Two ADRs that say something falsifiable: (a) feature-engineering choices —
  window length, features vs raw samples, normalisation; (b) model-vs-rule
  trade-offs, argued from the measured table above, not from sentiment.

## What "done" does not look like

- **No MLOps platform.** No MLflow, no feature store, no model registry
  service, no experiment tracker. Model versioning is git-lfs plus a naming
  convention; that is enough for one robot and two models.
- **No online or continual learning, no drift detection.** Train offline,
  serve frozen. The moment retraining becomes a service, this repo has
  quietly become a different thesis.
- **No new detection science.** Standard models, honest evaluation. The
  contribution is architectural — *where detection sits* in a
  service-oriented twin — not a better detector.
- **No GPU requirement.** If the LSTM autoencoder can't train on a laptop
  CPU in minutes, it is too big for this repo.
- **One robot.** Fleet-level anomaly aggregation belongs in `twin-fleet`.
- **No closed loop.** The service scores and alerts; it does not stop the
  arm. Acting on detections is a thesis chapter, not this repo.

## Audience

Same three people, in order:

1. **Me, six months from now**, writing the chapter that ranks twin services
   by value delivered — this repo is the existence proof for the detection
   tier, and `twin-fleet` forks this stack next.
2. **A thesis examiner** who wants evidence that "the twin detects
   anomalies" maps to a running service with measured detection quality,
   not a notebook with one cherry-picked plot.
3. **A recruiter or PI** who watches the GIF — fault injected, score spikes,
   panel goes red — and understands the closed observability loop in
   fifteen seconds.

If a change doesn't help at least one of those three, it doesn't ship.
