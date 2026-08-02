# 3. Feature engineering as a shared, versioned contract

Date: 2026-07-18
Status: Accepted

## Context

Two consumers need "the same features": `data-pipeline` computes them over
InfluxDB history to build the training set, and `anomaly-svc` computes them
over live telemetry to score. If those two computations ever disagree — a
different window length, a different normalisation, an off-by-one in an
edge case — the model scores inputs unlike anything it trained on, and the
failure is silent: no error, just quietly wrong scores. This is
training/serving skew, the classic way ML systems rot.

Feature engineering is also a pile of small decisions (window length, hop,
which statistics, boundary handling) that tend to hide in notebook cells
where they can't be reviewed or reproduced.

## Decision

**One implementation, imported twice.** Windowing, feature computation, and
the labelling boundary policy live in the `features/` package. Both
`data-pipeline` and `anomaly-svc` import it; neither reimplements any part.
`features/` is numpy-only with no I/O — a purity test (`test_purity.py`)
fails the build if a forbidden import or an `open()` appears — so it is
cheap to import in a scorer and impossible to couple to a data source.

**`features.__version__` is the compatibility token.** Every model manifest
records the version it was trained against; `anomaly-svc` refuses readiness
if its `features/` version doesn't match the loaded artefact. Any change to
windowing, a feature definition, normalisation, or the boundary policy
bumps the version and thereby invalidates every existing artefact — on
purpose. There is no silent feature fix.

The specific choices, each defended:

- **Time-based windows, 1.0 s long, 0.5 s hop.** Time-based (not
  sample-count) so a comms drop-out reads as a *sparse* window rather than
  one that silently reaches further back in time; `n_samples` then carries
  the drop-out signal directly. 1.0 s is long enough for a velocity-RMS
  estimate to mean something at 50 Hz (~50 samples); 0.5 s (50% overlap)
  keeps detection from being hostage to where a fault falls relative to a
  window boundary.
- **Five per-joint features:** position std and peak-to-peak; velocity RMS,
  std, and mean-abs. Small and legible because ADR-0004 has to defend each
  against a three-line rule. Mapped to the ADR-0002 signature predictions:
  encoder → position std up; stuck → position ptp and velocity RMS toward
  zero; friction → velocity RMS attenuated. `n_samples` covers drop-out.
- **Effort carried but not featurised.** Our fault transforms don't touch
  effort (ADR-0002), so an effort feature would be constant on this
  dataset. It stays in the `(T, J, 3)` sample layout for the day a fault
  reaches it.
- **No normalisation inside `features/`.** Raw physical units out; any
  scaling belongs to the model pipeline and is saved *in the artefact*, so
  serving applies exactly the training scaler. `features/` must be a pure
  function of the samples, identical everywhere.
- **Labelling: overlap-any, greatest-overlap-wins.** A window touching any
  part of a fault is labelled with that fault; ties at experiment hand-offs
  go to the greatest overlap, then to the earlier fault. Boundaries are
  half-open, so a fault starting exactly at a window's end does not bleed
  in. This lives in `features/label_window`, decided once, versioned with
  the features it labels — never in a notebook.

**Determinism is tested.** `data-pipeline`'s `build_table` is a pure
function of its arrays; `test_build.py` asserts byte-identical parquet
across two runs. Same telemetry in, same dataset out.

## Consequences

- The scorer's readiness check turns skew from a silent wrong number into a
  visible outage: bump `features/`, and every unretrained service goes
  not-ready until its artefact is rebuilt. That is the intended cost.
- Adding a feature is a breaking change to every artefact. Correct, but it
  means feature work batches — you don't add one stat casually mid-project.
- `PER_JOINT_FEATURES` order is the vector layout. It is append-only;
  reordering silently corrupts every trained model, exactly like renumbering
  a protobuf field (upstream ADR-0003), and is forbidden for the same reason.
- The window parameters are not runtime config. Changing them is a code
  change with a version bump, reviewed like any other — not a knob an
  operator can turn and quietly change what "anomalous" means.

**Revisit when:** a fault needs effort or cross-joint features (add them,
bump the version, retrain); or `anomaly-svc` needs sub-window latency that
1.0 s windows can't give (shorten the window, same process).
