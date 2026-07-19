# Architecture

## The 5-layer stack

Same vocabulary as every `twin-*` repo. This repo's contribution is the
first *value-adding* L4 service — one that consumes the twin's state rather
than constituting it — plus the offline machinery (dataset, training) that
such a service drags in whether you admit it or not.

```
┌──────────────────────────────────────────────────────────────────────┐
│ L5  Application         Grafana (traces + score + fault band) ·      │
│                         notebooks (offline training & evaluation)    │
├──────────────────────────────────────────────────────────────────────┤
│ L4  Services            telemetry-svc · state-svc · command-svc ·    │
│                         viz-svc · anomaly-svc · data-pipeline (batch)│
├──────────────────────────────────────────────────────────────────────┤
│ L3  Information model   (none — raw topics; twin-aas priced this)    │
├──────────────────────────────────────────────────────────────────────┤
│ L2  Transport           ROS 2 DDS ─bridge─▶ MQTT · gRPC (svc↔svc)    │
├──────────────────────────────────────────────────────────────────────┤
│ L1  Physical asset      UR5 in Gazebo Harmonic, signal perturbed by  │
│                         fault-injector (the "physics" we can break)  │
└──────────────────────────────────────────────────────────────────────┘
```

The four inherited services keep their exclusive responsibilities from
`twin-services` — nothing in this repo relaxes them.

## Service topology

Online path (live scoring) — inherited components compressed:

```
            ┌─────────┐    Flux     ┌──────────┐
            │ Grafana │◀────────────│ InfluxDB │
            └─────────┘             └────▲─────┘
   joint traces · anomaly score          │ writes (sole writer)
   · fault ground-truth band      ┌──────┴────────┐
                                  │ telemetry-svc │
                                  └──────▲────────┘
                                         │ subscribes joint/+/+ · fault/state · anomaly/score
    ┌────────────────────────────────────┴───────────────────────┐
    │                        Mosquitto                           │
    └─▲──────────────▲─────────────▲──────────────┬──────────────┘
      │ joint/…      │ anomaly/    │ fault/state  │ fault/cmd
      │ (telemetry)  │ score       │ (labels)     ▼
      │        ┌─────┴───────┐   ┌─┴──────────────────┐
      │        │ anomaly-svc │   │   fault-injector   │  ROS 2 node,
      │        └─────────────┘   │  (passthrough by   │  runs on host
      │                          │      default)      │  beside bridge
      │                          └─▲───────────────┬──┘
      │            /joint_states_raw│              │ /joint_states
      │                          ┌──┴──────────────▼──┐
      └──────── bridge ◀─────────│  UR5 in Gazebo     │
               (from twin-       └────────────────────┘
                services, unchanged)
```

Offline path (dataset → training → artefact → serving):

```
  InfluxDB ──Flux──▶ data-pipeline ──▶ data/*.parquet ──▶ notebooks/
                     (batch CLI)       (labelled windows)     │ train
                                                              ▼
  anomaly-svc ◀──loads pinned version at startup──── models/ (git-lfs)
```

## Data flows

**Fault injection (the new ground-truth path):**

1. `just inject <fault>` publishes a typed `FaultCommand` to
   `twin/ur5/fault/cmd` (fault kind, severity, duration, target joint).
2. `fault-injector` — a ROS 2 node that also speaks MQTT, like the bridge —
   sits in the sensor path: Gazebo's joint states arrive remapped as
   `/joint_states_raw`, the injector republishes them as `/joint_states`
   for the unchanged `twin-services` bridge to consume. Passthrough when
   idle; under a fault it perturbs the stream — velocity lag (friction
   spike), additive noise (encoder), frozen value (stuck joint), or paused
   forwarding (comms drop-out).
3. For the duration of the fault the injector publishes `FaultState` to
   `twin/ur5/fault/state`. This label channel is deliberately out-of-band
   from the telemetry it corrupts: a comms drop-out cuts the joint stream,
   never the label stream — you cannot label an outage using the channel
   you just cut.
4. `telemetry-svc` subscribes `twin/ur5/fault/state` (QoS 1) alongside its
   telemetry wildcard; it validates `FaultState` against `contracts` and
   persists it to the `fault_state` measurement. Ground truth is in
   InfluxDB the moment the fault starts.

**Dataset (the streaming→ML boundary):**

5. `data-pipeline` is a batch CLI, not a service: one Flux query window at
   a time, it aligns joint telemetry into fixed windows (length and hop are
   config, argued in ADR-0003), computes features via the shared
   `features/` package, joins the `fault_state` labels by timestamp, and
   writes labelled parquet to `data/`. Deterministic: same raw data in,
   same windows out. Notebooks read parquet only — never InfluxDB.

**Training (offline, reproducible):**

6. Notebooks train the Isolation Forest and the LSTM autoencoder from
   parquet, evaluate against the held-out fault windows and the
   threshold-rule baseline, and write artefacts to `models/` (git-lfs):
   the serialized model plus a manifest recording metrics, feature
   version, and training-data provenance.

**Serving (the point of the repo):**

7. `anomaly-svc` loads one pinned model artefact at startup — never
   "latest". It subscribes to the same MQTT telemetry as `state-svc`,
   maintains a rolling window, computes features with the *same*
   `features/` package the pipeline used, and scores each hop.
8. Scores go out as typed `AnomalyScore` messages on
   `twin/ur5/anomaly/score`; `telemetry-svc` persists them like any other
   telemetry. Single InfluxDB writer stays single.
9. `POST /score` accepts an explicit window and returns score, verdict,
   and model version. Same scorer as the MQTT loop, second entry point —
   it exists so the evaluation notebook and CI can exercise serving
   without a broker.

**Observability (the demo):**

10. Grafana overlays three things on one time axis, all from InfluxDB:
    the joint traces, the anomaly score with its threshold, and the
    ground-truth fault band. The README GIF is this panel: fault starts,
    band appears, score crosses the line.

## Contracts, features, models

Three skew-prevention packages, one rule each:

- **`contracts/`** (inherited pattern) — every payload crossing MQTT or
  REST imports from here. New models: `FaultCommand`, `FaultState`,
  `AnomalyScore`, `WindowScoreRequest`. A service declaring a payload
  shape locally is a bug, exactly as in `twin-services`.
- **`features/`** — the feature contract. One numpy-only implementation of
  windowing and feature computation, imported by both `data-pipeline`
  (training time) and `anomaly-svc` (serving time). Training/serving skew
  is the classic silent ML failure; this package is the tripwire.
  ADR-0003 argues it.
- **`models/`** — git-lfs artefacts, named `<model>-v<N>.<ext>`, each with
  a manifest (`<model>-v<N>.json`): metrics, feature package version,
  dataset fingerprint. `anomaly-svc` config pins an exact artefact.

## Ports

Inherited unchanged from `twin-services`, plus one:

| Component     | Port         | Protocol                      |
| ------------- | ------------ | ----------------------------- |
| Mosquitto     | 1883         | MQTT                          |
| InfluxDB      | 8086         | HTTP                          |
| Grafana       | 3000         | HTTP                          |
| Prometheus    | 9090         | HTTP                          |
| telemetry-svc | 8001         | HTTP (healthz/metrics)        |
| state-svc     | 8002 / 50051 | HTTP / gRPC                   |
| command-svc   | 8003         | HTTP (REST + healthz/metrics) |
| viz-svc       | 8004         | HTTP + WebSocket              |
| anomaly-svc   | 8005         | HTTP (REST + healthz/metrics) |

New MQTT topics: `twin/ur5/fault/cmd`, `twin/ur5/fault/state`,
`twin/ur5/anomaly/score`. New InfluxDB measurements: `fault_state`,
`anomaly_score`.

## Design decisions (summaries — the ADRs argue them)

### Faults injected in the signal path, not the physics — ADR-0002

The injector perturbs the sensor stream between Gazebo and the bridge
rather than reaching into Gazebo's physics. Encoder noise, stuck joint,
and comms drop-out *are* signal faults; the friction spike is approximated
as velocity lag, and the ADR owns that approximation honestly. What we
buy: all four faults in one passthrough node, parameterised and instantly
reversible, with labels emitted at the injection point — ground truth by
construction.

### Feature engineering as a shared contract — ADR-0003

Window length, hop, per-joint features, normalisation — each choice
recorded with the alternative it beat. The structural decision: one
`features/` package imported at both training and serving time, because
two implementations of "the same" features is how skew ships to
production.

### Model vs rule — ADR-0004

A deliberately naive threshold rule (e.g. velocity RMS over a constant) is
evaluated on the identical held-out windows as both models, per fault
type, precision and recall in one table. The ADR's conclusion must cite
the table, and if the rule wins on a fault type, it says so in the first
paragraph. Detection quality claims without a baseline are marketing.

## What this repo intentionally omits

- **An MLOps platform.** No MLflow, feature store, registry service, or
  experiment tracker. git-lfs plus manifests carries two models for one
  robot; the ADRs note where a registry would attach.
- **Online / continual learning and drift detection.** Train offline,
  serve frozen. Retraining-as-a-service is a different thesis.
- **Closed-loop reaction.** The service scores and alerts; it never
  commands the arm. The command path stays exclusively `command-svc`'s.
- **Physics-level fault realism.** ADR-0002's approximation is the scope
  fence; a Gazebo friction plugin is future work, not this repo.
- **A GPU.** Both models train on a laptop CPU in minutes or they shrink
  until they do.
- **More than one robot.** Fleet-level anomaly aggregation is `twin-fleet`.
