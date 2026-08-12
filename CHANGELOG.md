# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

Model artefacts have their own release history: `git log models/` — each
`chore(models)` commit is one artefact + manifest pair.

## [Unreleased]

### Added
- Context docs (vision, architecture, roadmap, style), AGENTS.md rules of
  engagement, ADR-0001.
- twin-services stack vendored: contracts, bridge, four services, deploy,
  sim, chaos script, integration tests. Dockerfile manifest layers updated
  for the ten-member workspace (also fixes the inherited bridge omission).
- New workspace members as Phase 0 stubs: `features/` (version token +
  numpy-only/no-I/O purity tripwires), `fault-injector/` (passthrough node,
  pure-transform seam, pinned `just inject` CLI surface), `data-pipeline/`
  (pinned `just dataset` CLI surface), `services/anomaly-svc/` (health/
  metrics stub on :8005, artefact-free image with models/ bind-mount).
- Toolchain: uv workspace pyproject, justfile (inject/collect/dataset/lab/
  demo/lfs recipes), compose stack with anomaly-svc, pre-commit with
  nbstripout, git-lfs attributes (manifests stay plain git), CI with
  contracts/notebooks/models/compose gates.
- `just check`: 58 tests green, 3 stack-dependent skips.
- `contracts.detection` (schema-first, before any consumer): `FaultKind`
  (one vocabulary for commands, labels, and dataset classes — `none` is
  what normal is called everywhere), `FaultCommand` (clear/dropout cannot
  target a joint), `FaultState` (1 Hz label heartbeat, `command_id`
  traceability, active/kind coherence enforced), `JointWindow` +
  `WindowScoreRequest` (rectangular windows only), `AnomalyScore` (shared
  MQTT payload and POST /score response; threshold travels with the
  score), and the three fault/anomaly topic helpers.
- fault-injector goes live: the four transforms (friction lag, seeded
  encoder noise, stuck, dropout), `FaultSession`'s label algebra (opened
  at injection time, closed exactly once, ended command's id on the
  closing label), the MQTT worker (cmd listener + 1 Hz heartbeat, QoS 1),
  and the `just inject` CLI publishing real `FaultCommand`s.
- telemetry-svc persists `fault_state`: second subscription at QoS 1,
  `kind`/`joint` as tags (`joint=all` for untargeted), `command_id` as a
  field. Integration tests split the label path at its two seams: wire →
  InfluxDB, and cmd → injection-time label (real fault_worker in-process,
  no ROS).
- ADR-0002 (signal-path injection, not physics) with the friction
  approximation's limits stated and per-fault signatures pre-registered.
- `features/` real implementation: time-based windowing (1 s / 0.5 s),
  five per-joint stats plus `n_samples`, overlap-any labelling — all
  numpy-only, all versioned by `features.__version__`.
- `data-pipeline`: pure `build_table` (byte-deterministic parquet) behind
  a Flux `query` boundary; `just dataset` writes
  `data/<name>-<features version>.parquet` with a label-balance summary.
- `scripts/collect.py`: scripted fault schedule (all four faults at varied
  severities, normal between) driving the real session + worker over MQTT.
- ADR-0003 (feature engineering as a shared, versioned contract).
- `detector/`: shared scoring library (rule baseline, IsolationForest,
  manifest, evaluation) — the serving-logic twin of `features/`, so the
  evaluation table and `anomaly-svc` score with identical code.
- `data-pipeline` coverage floor: non-fault windows below half a full
  window's samples are dropped as absence-of-operation, so idle gaps and
  run boundaries stay out of the "normal" class; drop-out windows (empty
  but fault-labelled) are kept.
- Notebooks 01 (explore, confirms ADR-0002 signatures) · 02 (train rule +
  IsolationForest) · 03 (LSTM-AE, deferred per ROADMAP) · 04 (evaluate →
  `docs/EVALUATION.md`).
- First artefacts (git-lfs): `rule-v1`, `isoforest-v1` with manifests.
- ADR-0004 (model vs rule): the forest ships for friction/stuck (0.61 /
  0.41 recall vs the rule's 0.00), the rule *wins* on encoder (0.47 vs
  0.20), they tie on dropout — reported honestly, per fault.
- anomaly-svc serves `isoforest-v1`: loads the pinned artefact at startup,
  readiness that fails on a missing model or a features-version mismatch,
  a rolling MQTT window reassembled into the same `(n, J, 3)` matrix the
  pipeline built, `AnomalyScore` published each hop, and `POST /score`
  sharing the one scorer. Metrics: `twin_anomaly_score`, `_verdict`,
  `_windows_scored_total`. Depends on `detector` (added to every service
  Dockerfile's manifest layer).
- telemetry-svc persists `anomaly_score` (third subscription): `artefact`
  as a tag, score/threshold/verdict as fields, timestamped at window end.
- `data/fixtures/window.json`: a drop-out-signature window the shipped
  model flags; DoD verified live — `POST /score` returns 0.6685169832…,
  byte-for-byte the score the `detector` library computes locally.
- `just demo` (`scripts/demo.py`): assertable, not a screencast — injects
  each fault while the live anomaly-svc scores, asserts the score crosses
  its threshold inside every fault window and stays under it during normal
  running, non-zero exit otherwise. Passes: friction/encoder/stuck/dropout
  all detected, normal FPR ≤ 10%.
- anomaly-svc's live window prunes by **wall clock**, not telemetry time
  (unlike state-svc): a total drop-out stops telemetry, so telemetry-time
  pruning would freeze the window on the last normal second and miss it.
- Grafana overlay: `anomaly score` (score + dashed threshold) and
  `injected fault (ground truth)` state-timeline panels, both from
  InfluxDB, beneath the joint traces on one time axis.
- `WHAT_I_LEARNED.md` and the README result table filled in.
