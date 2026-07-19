# Style

Inherits everything from `twin-services` — workspace discipline, contracts
rules, async/structlog conventions, MQTT scheme, metrics and health shapes,
commit format. Only the deltas this repo introduces are documented here.

## Workspace

- Members: inherited (`contracts`, `bridge`, four services) plus
  `features/`, `data-pipeline/`, `services/anomaly-svc/`. Notebooks are
  not a member; they run from the dev dependency group.
- Dependency lists are still architecture statements:
  - `features/` is **numpy-only**. No pandas, no pydantic, no I/O of any
    kind. If a feature needs a dataframe, it isn't a feature yet.
  - Only `data-pipeline` may depend on pyarrow and the Influx client's
    read side.
  - `anomaly-svc` depends on `features/` and the model runtime
    (scikit-learn; torch only if the LSTM-AE survives Phase 3) — never on
    pyarrow, pandas, or the Influx client.
  - `fault-injector` follows `bridge` conventions: ROS imports are lazy so
    lint and tests pass without a ROS 2 env; fault transforms are pure
    functions unit-testable without ROS.

## Reproducibility

- Every stochastic step takes an explicit seed — fault noise, dataset
  splits, model init. A bare `np.random` call fails review.
- `features.__version__` is recorded in every model manifest;
  `anomaly-svc` refuses readiness if its `features/` version doesn't match
  the loaded manifest. Changing any feature bumps the version and
  invalidates every artefact, on purpose.
- `data-pipeline` output is deterministic: same input rows, byte-identical
  parquet. There is a test for this; keep it passing.

## Data

- Parquet only; no CSV anywhere. `data/` is gitignored except small test
  fixtures under `data/fixtures/`.
- Timestamps are UTC nanoseconds end to end. Windows carry
  `window_start`, `window_end`, `label` (bool), `fault_kind`
  (enum from `contracts`, `none` for normal), `severity`.
- A window overlapping any part of a fault is labelled faulty — boundary
  policy lives in `features/` and ADR-0003, not in notebook cells.

## Notebooks

- Re-runnable top to bottom from `data/*.parquet` and a seed cell — no
  InfluxDB access, no network, no hidden state between runs.
- Outputs are stripped on commit (nbstripout via pre-commit). Anything
  worth keeping graduates: tables to `docs/EVALUATION.md`, logic used
  twice to a package. A notebook is a lab bench, not a library.

## Models

- Artefacts named `<model>-v<N>.<ext>` beside `<model>-v<N>.json`
  manifests: metrics per fault type, `features/` version, dataset
  fingerprint, seed, training date. Artefacts ride git-lfs; manifests
  stay plain git so `git log -p models/` diffs the metrics.
- `anomaly-svc` config pins an exact artefact filename. The strings
  "latest", symlinks, and globs do not appear in model loading code.
- The threshold is part of the artefact's manifest, not service config —
  a model and its operating point are chosen together (ADR-0004).

## MQTT deltas

- New topics use the inherited scheme: `twin/ur5/fault/cmd`,
  `twin/ur5/fault/state`, `twin/ur5/anomaly/score`, built by `contracts`
  helpers as always.
- QoS: `fault/cmd` and `fault/state` are QoS 1 (a lost fault command is a
  missing experiment; a lost label poisons the dataset). `anomaly/score`
  is QoS 0 like telemetry. Nothing is retained — an active fault
  heartbeats `FaultState` at 1 Hz instead, so late subscribers converge
  without stale ghosts.

## Metrics and health deltas

- `anomaly-svc` exports `twin_anomaly_score`, `twin_anomaly_verdict`
  (0/1), and `twin_anomaly_windows_scored_total`, all labelled with
  `model_version`.
- Its readiness lists three dependencies by name: broker connection,
  model artefact loaded, `features/` version match.

## Commits

- Inherited Conventional Commits; new scopes: `feat(injector)`,
  `feat(features)`, `feat(pipeline)`, `feat(anomaly-svc)`,
  `chore(models)`, `docs(notebooks)`.
- Model artefacts land in their own `chore(models)` commit with the
  manifest — never mixed with code changes, so `git log models/` reads as
  a release history.
