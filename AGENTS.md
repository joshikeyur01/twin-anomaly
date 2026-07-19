# Project context & conventions

Read this before touching code. It sets the architecture, conventions, and
guardrails for any work in this repository.

## Mission

The detecting digital twin: the `twin-services` stack extended with
parameterised fault injection (`fault-injector/`), a labelled dataset
pipeline (`features/` + `data-pipeline/`), and a serving detector
(`services/anomaly-svc/`) that scores live telemetry against a trained,
pinned model.

Success criterion: `just demo` injects each of the four faults in turn;
the anomaly score crosses its threshold inside every labelled window and
stays under it during normal stretches; the Grafana overlay (joint traces
+ score + ground-truth fault band) shows all of it. Captured as the README
GIF.

## Stack

Inherited from `twin-services`: Python 3.12 · ROS 2 Jazzy · Gazebo
Harmonic · Mosquitto (MQTT) · InfluxDB 2 · Grafana · Prometheus ·
gRPC/protobuf · Docker Compose · `uv` (workspace) · `just`.
Added here: scikit-learn · pyarrow/parquet · git-lfs (model artefacts) ·
torch **only if** the LSTM-AE survives Phase 3.

## Non-negotiable conventions

All of `twin-services`' conventions apply unchanged (contracts-first,
mypy --strict, per-service Dockerfile with `/healthz` + `/metrics`, ruff,
colocated tests, Conventional Commits, ADR per dependency). Added here:

- **One feature implementation.** Windowing and features live in
  `features/` (numpy-only, no I/O) and are imported by both
  `data-pipeline` and `anomaly-svc`. A second implementation of any
  feature, however small, is a bug — that's how skew ships.
- **Explicit seeds** on every stochastic step. A bare `np.random` call
  fails review.
- **Pinned artefacts.** `anomaly-svc` loads an exact `models/` filename
  with a manifest; the threshold comes from the manifest. "latest",
  symlinks, and globs never appear in model-loading code.
- **Notebooks read parquet only** — no InfluxDB, no network — and re-run
  top to bottom. Outputs are stripped on commit.
- **Determinism is tested.** `data-pipeline` produces byte-identical
  output for identical input; keep that test passing.

## Architecture rules

Follow the 5-layer stack in [`docs/context/ARCHITECTURE.md`](docs/context/ARCHITECTURE.md).
The four inherited services keep their `twin-services` responsibilities,
unchanged. New responsibilities are exclusive — do **not** cross them:

- `fault-injector` perturbs the sensor stream and emits labels. Four
  transforms, passthrough otherwise. It does not persist, score, or
  contain any logic a fault model wouldn't recognise.
- `telemetry-svc` remains the **sole InfluxDB writer**. Labels and scores
  reach storage as MQTT messages it persists — never as direct writes.
- `data-pipeline` turns InfluxDB history into labelled parquet. Batch,
  run-to-completion; it never daemonises, trains, or serves.
- `features/` computes windows and features. No I/O of any kind.
- `anomaly-svc` scores and alerts. It never writes InfluxDB, never
  publishes to `twin/ur5/cmd/*`, never retrains, never touches parquet.
- Notebooks consume `data/`, produce `models/`. Nothing imports from a
  notebook.

If a change would blur these boundaries, propose an ADR instead of
writing the code.

## When you touch code

1. Read the ADRs — especially 0002 (signal-path injection), 0003 (feature
   contract), 0004 (model vs rule).
2. Schema changes land in `contracts/` first, feature changes bump
   `features.__version__` (and thereby invalidate every artefact) —
   never silently.
3. Update tests in the same commit; the scorer has golden-window tests
   pinning notebook-computed scores.
4. Model artefacts land in their own `chore(models)` commit with their
   manifest, never mixed with code.
5. New public interface (topic, route, config key, parquet column,
   manifest field) → document it in `docs/`.
6. Prefer editing existing files; functions under ~40 lines, modules
   under ~200.

## What to refuse

- **MLOps platforms.** MLflow, W&B, feature stores, model registries,
  experiment trackers. git-lfs plus manifests is the registry.
- **Online / continual learning, drift detection, auto-retraining.**
  Train offline, serve frozen.
- **Closed-loop reaction.** Nothing in this repo publishes a command in
  response to a score. If asked for it, point at the thesis, not the code.
- **A third model family.** Rule, Isolation Forest, LSTM-AE — the
  comparison is the point, not a leaderboard. No transformers, no
  ensembles, no GPU dependencies.
- **Physics-level fault injection.** Gazebo plugins are out of scope;
  ADR-0002 owns the approximation.
- **Fleet features, AAS/OPC-UA, Kubernetes.** Other repos.
- **Brokers other than Mosquitto, databases other than InfluxDB.**
- **Committing datasets.** `data/` stays out of git except fixtures;
  parquet is regenerable by construction.

This repo demonstrates where detection sits in a service-oriented twin.
Keep it one detector, four faults, one honest table.
