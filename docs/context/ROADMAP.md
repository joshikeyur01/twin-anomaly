# Roadmap

Six phases, two weeks total. Same rule as every `twin-*` repo: if a phase
slips more than two days, cut scope inside the phase — do not push the next
phase. The fault-to-alert demo GIF is the deliverable; everything else is
negotiable. The LSTM autoencoder is explicitly the first thing to cut.

## Phase 0 · Scaffold + inherited stack (days 1–2)

- [ ] Repo skeleton, licence, `.gitignore`, `.gitattributes` (git-lfs for
      `models/`), pre-commit, CI (lint + mypy + tests).
- [ ] Vendor the `twin-services` stack unchanged: `contracts/`, `bridge/`,
      `services/{telemetry,state,command,viz}-svc`, `deploy/`, `sim/`,
      compose infra. Inherited fixes come along: no `container_name`,
      `.python-version` pinned, capped gRPC backoff, `chflags` guard.
- [ ] `pyproject.toml` as a `uv` workspace: inherited members plus
      `features/`, `data-pipeline/`, `services/anomaly-svc/`.
- [ ] `anomaly-svc` and `fault-injector` exist as stubs: the service builds
      and answers `/healthz` hardcoded; the injector node passes through
      `/joint_states_raw` → `/joint_states` with no faults yet.
- [ ] `justfile`: inherited recipes plus stubs for `inject`, `dataset`,
      `demo`.

**DoD:** fresh clone → `just up && just healthz` shows the inherited stack
plus `anomaly-svc` green; with the sim running, joint traces appear in
Grafana *through the passthrough injector*.

## Phase 1 · Contracts + fault injection (days 3–4)

- [ ] `contracts`: `FaultCommand`, `FaultState`, `AnomalyScore`,
      `WindowScoreRequest` — schema lands here before any consumer, with
      round-trip tests, per the inherited rule.
- [ ] `fault-injector`: the four parameterised faults — friction spike
      (velocity lag), encoder noise, stuck joint, comms drop-out — applied
      on `twin/ur5/fault/cmd`, ended by duration or explicit clear.
- [ ] Labels out-of-band: `FaultState` published on `twin/ur5/fault/state`
      for the fault's duration; drop-out cuts telemetry, never labels.
- [ ] `telemetry-svc` extended (schema-first) to persist `fault_state`.
- [ ] `just inject <fault>` CLI; unit tests for each fault transform
      (deterministic seeds), integration test for cmd → state → InfluxDB.
- [ ] ADR-0002 (signal-path injection, not physics) written — including
      what the friction approximation *cannot* show.

**DoD:** `just inject stuck --joint elbow --duration 10` freezes the elbow
trace in Grafana while the `fault_state` measurement records exactly that
window; clearing recovers with no restart.

## Phase 2 · Dataset (days 5–6)

- [ ] `features/`: windowing + per-joint features, numpy-only, versioned;
      property tests (window count arithmetic, NaN policy, dtype).
- [ ] `scripts/collect.py`: scripted fault schedule against the live sim —
      normal running interleaved with all four faults at varied severities
      — to build the training corpus in InfluxDB.
- [ ] `data-pipeline`: batch CLI — Flux query → windows → features → label
      join → labelled parquet in `data/` (gitignored; small fixture
      checked in for tests).
- [ ] Determinism test: same InfluxDB export in, byte-identical parquet
      out, twice.
- [ ] ADR-0003 (feature engineering + shared `features/` contract) written.

**DoD:** `just collect && just dataset` yields parquet with all five
classes (normal + four faults) and a label balance printed at the end;
rerunning `just dataset` reproduces it exactly.

## Phase 3 · Models (days 7–9)

- [ ] `notebooks/01-explore.ipynb`: class balance, feature distributions
      per fault type — the plots that justify ADR-0003's choices.
- [ ] Threshold-rule baseline (velocity-RMS over a constant) implemented
      first and frozen before any model trains.
- [ ] `notebooks/02-train-isoforest.ipynb`: trained on normal windows only,
      evaluated on held-out windows per fault type.
- [ ] `notebooks/03-train-lstm-ae.ipynb`: CPU-sized autoencoder, same
      split, same eval. **First thing cut if the phase slips.**
- [ ] `notebooks/04-evaluate.ipynb`: one table — rule vs isoforest vs
      LSTM-AE, precision/recall per fault type — exported to
      `docs/EVALUATION.md`.
- [ ] Artefacts + manifests (metrics, feature version, dataset
      fingerprint) in `models/` via git-lfs.
- [ ] ADR-0004 (model vs rule) written, conclusions citing the table.

**DoD:** every notebook re-runs top to bottom from parquet alone;
`models/` holds `isoforest-v1` (and `lstm-ae-v1` if it survived) with
manifests; the evaluation table exists and ADR-0004 quotes it.

## Phase 4 · Serving (days 10–11)

- [ ] `anomaly-svc`: loads the pinned artefact at startup (fails readiness
      if missing/mismatched feature version), rolling window over MQTT
      telemetry, scores each hop via `features/`.
- [ ] Scores published as `AnomalyScore` on `twin/ur5/anomaly/score`;
      `telemetry-svc` persists `anomaly_score` (schema-first, again).
- [ ] `POST /score`: explicit window in, score + verdict + model version
      out; same scorer as the live loop.
- [ ] Real `/healthz` (readiness = broker connected *and* model loaded)
      and `/metrics` including score and verdict gauges.
- [ ] Unit tests against golden windows from the eval set; integration
      test: synthetic telemetry in → score row in InfluxDB out.

**DoD:** with the stack live, `curl -X POST :8005/score` with a fixture
window returns the same score the notebook computed for it (to float
tolerance) — the skew tripwire, live.

## Phase 5 · Overlay + demo (days 12–13)

- [ ] Grafana: one panel overlaying joint traces, anomaly score with
      threshold line, and the ground-truth fault band — all from InfluxDB.
- [ ] `just demo`: inject each fault type in sequence; assert the score
      crosses the threshold inside the labelled window, and stays under it
      during normal running (script exits non-zero otherwise).
- [ ] README GIF: the overlay panel during `just demo`.
- [ ] `WHAT_I_LEARNED.md` filled in.

**DoD:** fresh clone → `just up && just sim && just demo` passes: four
faults, four detections, zero false alarms in the normal stretches — or
the failures are documented in `WHAT_I_LEARNED.md` with numbers.

## Explicit non-goals for this repo

- MLOps platform, registry, experiment tracker. git-lfs + manifests.
- Online learning, drift detection, retraining automation.
- Closed-loop reaction to detections. Scoring ends at the alert.
- Physics-level fault realism. ADR-0002 owns the approximation.
- More than one robot. `twin-fleet`.
- GPU anything.
