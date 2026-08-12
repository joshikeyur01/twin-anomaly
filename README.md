# twin-anomaly

> The detecting digital twin: the `twin-services` stack taught to notice
> when its robot misbehaves — parameterised fault injection, a labelled
> dataset pipeline, and a served detector scored against an honest rule
> baseline. Fourth rung of the
> [`twin-*`](https://github.com/joshikeyur01?tab=repositories&q=twin-)
> portfolio.

![demo](docs/demo/twin-anomaly.gif)

## What this is

`twin-services` knows what the arm is doing; this repo knows when that's
wrong. A **fault-injector** (ROS 2 passthrough node) corrupts the sensor
stream on command — friction spike, encoder noise, stuck joint, comms
drop-out — and publishes ground-truth labels out-of-band while it does.
A **data-pipeline** batches the resulting InfluxDB history into labelled
parquet windows; notebooks train an Isolation Forest and an LSTM
autoencoder from them; **anomaly-svc** serves a pinned artefact, scoring
live telemetry and publishing the score back through the same MQTT →
InfluxDB path as everything else. One Grafana panel overlays joint
traces, anomaly score, and the ground-truth fault band — `just demo`
asserts the detections instead of eyeballing them.

Deliberately does **not** include: MLOps platforms (git-lfs + manifests
is the registry), online learning or drift detection, closed-loop
reaction to detections, physics-level fault realism, more than one robot
(`twin-fleet`), or a third model family — rule vs forest vs autoencoder
*is* the experiment.

## Architecture (5-layer stack)

| Layer | Component |
|-------|-----------|
| L5 Application | Grafana overlay (traces + score + fault band) · notebooks |
| L4 Services | inherited four · anomaly-svc · data-pipeline (batch) |
| L3 Information model | *(none — raw topics; priced in `twin-aas`)* |
| L2 Transport | ROS 2 DDS ↔ MQTT bridge · gRPC (svc↔svc) |
| L1 Physical / simulated | UR5 in Gazebo Harmonic, signal perturbed by fault-injector |

See [`docs/context/ARCHITECTURE.md`](docs/context/ARCHITECTURE.md) and
the ADRs in [`docs/adr/`](docs/adr/) — especially 0002 (signal-path
injection, and what the friction approximation cannot show), 0003 (the
shared feature contract), 0004 (model vs rule, argued from a table).

## Quick start

Prerequisites: Docker, Docker Compose, [`just`](https://github.com/casey/just),
[`uv`](https://docs.astral.sh/uv/), git-lfs. ROS 2 Jazzy + Gazebo only
for the real sim.

```bash
just up          # inherited stack + anomaly-svc
just healthz     # 9 green checks
just inject stuck --joint elbow --duration 10
                 # elbow trace freezes; fault_state records exactly that window
just demo        # inject all four faults; assert score crosses threshold
                 # inside every labelled window, stays under it otherwise
```

Rebuild the dataset and models from scratch:

```bash
just collect     # scripted fault schedule against the live sim
just dataset     # InfluxDB → labelled parquet windows (deterministic)
# then run notebooks/01..04 top to bottom; artefacts land in models/
```

Score a window without the stack (the skew tripwire):

```bash
curl -X POST localhost:8005/score -H 'content-type: application/json' \
     -d @data/fixtures/window.json    # score + verdict + model version
```

Then open <http://localhost:3000> — the overlay panel is the repo's
argument in one screen.

## Repo layout

```
contracts/            # payload source of truth (+ Fault*, AnomalyScore)
features/             # THE feature implementation — numpy-only, shared by
                      #   training and serving; skew dies here
bridge/               # DDS↔MQTT plumbing (vendored from twin-services)
fault-injector/       # passthrough ROS 2 node: four faults, labels out-of-band
data-pipeline/        # InfluxDB → labelled parquet windows (batch CLI)
services/
  telemetry-svc/      # sole InfluxDB writer (now also labels + scores)
  state-svc/          # unchanged from twin-services
  command-svc/        # unchanged from twin-services
  viz-svc/            # unchanged from twin-services
  anomaly-svc/        # pinned model, rolling window, MQTT scores, POST /score
notebooks/            # 01 explore · 02 isoforest · 03 lstm-ae · 04 evaluate
models/               # git-lfs artefacts + manifests (metrics, versions, seed)
data/                 # gitignored; fixtures/ checked in for tests
scripts/collect.py    # scripted fault schedule → training corpus
scripts/demo.py       # the assertable four-fault demo
docs/context/         # vision, architecture, style, roadmap
docs/adr/             # decisions with evidence, not vibes
docs/EVALUATION.md    # rule vs forest vs autoencoder, per fault type
```

## The result

At a matched 1% false-positive budget, per fault
([`docs/EVALUATION.md`](docs/EVALUATION.md), argued in
[ADR-0004](docs/adr/0004-model-vs-rule.md)):

| recall     | rule | isoforest |
| ---------- | ---- | --------- |
| drop-out   | 0.88 | 0.93      |
| encoder    | 0.47 | 0.20      |
| friction   | 0.00 | 0.61      |
| stuck      | 0.00 | 0.41      |

Neither dominates: the forest ships because it catches the mechanically
meaningful velocity faults (friction, stuck) the rule can't, but the rule
*beats* it on encoder. `anomaly-svc` serves `isoforest-v1`; the rule stays
as the honest baseline. `just demo` asserts the whole loop live — every
fault detected, normal running quiet, non-zero exit otherwise.

## What I learned

The honest list is in [`WHAT_I_LEARNED.md`](WHAT_I_LEARNED.md) — why idle
windows poison the "normal" class, why a baseline scoring 0.00 is a bug not
a finding, why you can't featurise data you don't have, and why the model
doesn't dominate the rule. Most of it is about data, not models.

## Licence

Apache-2.0 — see [`LICENSE`](LICENSE).
