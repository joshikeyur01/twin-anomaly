"""Data pipeline for twin-anomaly: InfluxDB history -> labelled parquet.

One Flux query window at a time: align joint telemetry into fixed windows,
compute features via the shared ``features`` package, join the
``fault_state`` ground-truth labels by timestamp, write parquet to
``data/``. Batch, deterministic, run-to-completion — same input rows in,
byte-identical parquet out (there is a test for this from Phase 2 on).

Notebooks read this package's output and nothing else; they never touch
InfluxDB. Phase 0: CLI surface only — the pipeline lands in Phase 2.
"""
