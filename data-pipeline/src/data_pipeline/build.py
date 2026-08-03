"""The pure core: aligned arrays + fault intervals -> a labelled table.

No I/O, no InfluxDB — everything here is deterministic in its inputs, which
is what makes ``test_build.py`` able to assert byte-identical parquet
without a database. The Flux side lives in ``query.py``; this module only
ever sees numpy arrays and ``FaultInterval``s.

Column order is the parquet schema and must stay stable: metadata columns
first, then the feature columns in ``feature_names`` order.
"""

from __future__ import annotations

import io

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.parquet as pq

from features import (
    DEFAULT_SPEC,
    FaultInterval,
    WindowSpec,
    compute_features,
    feature_names,
    label_window,
    make_windows,
)

NORMAL_KIND = "none"

# A non-fault window must observe at least this fraction of a full window's
# worth of samples to count as a normal observation. Below it the window is
# an idle gap or a partial run-boundary — absence of clean operation, not
# normal operation. Fault windows are exempt: a drop-out is empty on purpose.
MIN_COVERAGE = 0.5


def _coverage_floor(stamps_ns: npt.NDArray[np.int64], length_ns: int) -> int:
    """Half the samples a full window would hold at the median sample rate.

    The median is robust to the big gaps (between runs, during drop-outs), so
    it recovers the true sample period regardless of how wide the query was.
    """
    diffs = np.diff(stamps_ns)
    if diffs.size == 0:
        return 0
    median_dt = int(np.median(diffs))
    expected = length_ns / max(median_dt, 1)
    return int(MIN_COVERAGE * expected)


def build_table(
    stamps_ns: npt.NDArray[np.int64],
    values: npt.NDArray[np.float64],
    joint_names: list[str],
    intervals: list[FaultInterval],
    spec: WindowSpec = DEFAULT_SPEC,
) -> pa.Table:
    """Window, featurise, and label a telemetry span into one Arrow table."""
    windows = make_windows(stamps_ns, values, spec)
    names = feature_names(joint_names)
    floor = _coverage_floor(stamps_ns, spec.length_ns)

    starts: list[int] = []
    ends: list[int] = []
    labels: list[bool] = []
    kinds: list[str] = []
    severities: list[float] = []
    command_ids: list[str] = []
    feature_columns: list[list[float]] = [[] for _ in names]

    for window in windows:
        owner = label_window(window.start_ns, window.end_ns, intervals)
        # A sparse non-fault window is absence of clean operation — an idle
        # gap between runs, or a partial window at a run boundary — not a
        # normal observation, so it stays out of the "normal" class. A sparse
        # window *during* a fault is a comms drop-out and is kept, labelled,
        # because its sparseness is the signal.
        if window.n_samples < floor and owner is None:
            continue
        vector = compute_features(window, joint_names)
        starts.append(window.start_ns)
        ends.append(window.end_ns)
        labels.append(owner is not None)
        kinds.append(owner.kind if owner else NORMAL_KIND)
        severities.append(owner.severity if owner else 0.0)
        command_ids.append(owner.command_id if owner else "")
        for i, value in enumerate(vector):
            feature_columns[i].append(float(value))

    columns: dict[str, pa.Array] = {
        "window_start_ns": pa.array(starts, pa.int64()),
        "window_end_ns": pa.array(ends, pa.int64()),
        "label": pa.array(labels, pa.bool_()),
        "fault_kind": pa.array(kinds, pa.string()),
        "severity": pa.array(severities, pa.float64()),
        "command_id": pa.array(command_ids, pa.string()),
    }
    for name, column in zip(names, feature_columns, strict=True):
        columns[name] = pa.array(column, pa.float64())
    return pa.table(columns)


def to_parquet_bytes(table: pa.Table) -> bytes:
    """Serialise deterministically — the determinism test compares these."""
    sink = io.BytesIO()
    pq.write_table(table, sink, compression="zstd")
    return sink.getvalue()


def write_table(table: pa.Table, path: str) -> None:
    pq.write_table(table, path, compression="zstd")


def label_balance(table: pa.Table) -> dict[str, int]:
    """Rows per fault_kind, for the CLI's end-of-run summary."""
    kinds = table.column("fault_kind").to_pylist()
    counts: dict[str, int] = {}
    for kind in kinds:
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))
