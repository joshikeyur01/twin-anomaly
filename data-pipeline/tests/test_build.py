"""The pure build path: determinism and labelling, no InfluxDB."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from data_pipeline.build import build_table, label_balance, to_parquet_bytes
from features import FaultInterval

MS20 = 20_000_000
SEC = 1_000_000_000
T0 = 1_700_000_000 * SEC
JOINTS = ["shoulder_pan_joint", "elbow_joint"]


def _stream(n: int = 200) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64]]:
    stamps = np.array([T0 + i * MS20 for i in range(n)], dtype=np.int64)
    rng = np.random.default_rng(0)  # deterministic content
    values = rng.standard_normal((n, len(JOINTS), 3))
    return stamps, values


def test_build_is_byte_deterministic() -> None:
    stamps, values = _stream()
    intervals = [FaultInterval(T0 + 2 * SEC, T0 + 3 * SEC, "stuck", 1.0, "c1")]
    first = build_table(stamps, values, JOINTS, intervals)
    second = build_table(stamps, values, JOINTS, intervals)
    assert first.equals(second)
    assert to_parquet_bytes(first) == to_parquet_bytes(second)


def test_schema_is_metadata_then_features() -> None:
    stamps, values = _stream()
    table = build_table(stamps, values, JOINTS, [])
    head = table.schema.names[:6]
    assert head == [
        "window_start_ns",
        "window_end_ns",
        "label",
        "fault_kind",
        "severity",
        "command_id",
    ]
    assert table.schema.names[6] == "shoulder_pan_joint__pos_std"
    assert table.schema.names[-1] == "n_samples"


def test_overlap_any_labelling() -> None:
    stamps, values = _stream()
    intervals = [FaultInterval(T0 + 2 * SEC, T0 + 3 * SEC, "stuck", 2.0, "c1")]
    table = build_table(stamps, values, JOINTS, intervals)
    starts = table.column("window_start_ns").to_pylist()
    kinds = table.column("fault_kind").to_pylist()
    labelled = {s: k for s, k in zip(starts, kinds, strict=True)}
    # Windows 1.5/2.0/2.5 s overlap the fault; the 1.0 s window only touches
    # the boundary at 2.0 s, which is not overlap.
    assert labelled[T0 + 1 * SEC] == "none"
    assert labelled[T0 + 1 * SEC + SEC // 2] == "stuck"  # 1.5 s window
    assert labelled[T0 + 2 * SEC] == "stuck"
    assert labelled[T0 + 2 * SEC + SEC // 2] == "stuck"  # 2.5 s window


def test_empty_idle_windows_are_dropped_but_dropout_kept() -> None:
    # 4 s of data with a 1.5 s telemetry gap in the middle [1.5, 3.0); the
    # gap's first half is idle (dropped), the second half is a dropout fault
    # (kept, labelled). Windows: 1 s length, 0.5 s hop.
    stamps = np.array(
        [T0 + i * MS20 for i in range(75)]  # 0 .. 1.48 s
        + [T0 + 3 * SEC + i * MS20 for i in range(50)],  # 3.0 .. 3.98 s
        dtype=np.int64,
    )
    values = np.zeros((len(stamps), len(JOINTS), 3), dtype=np.float64)
    intervals = [FaultInterval(T0 + 2 * SEC + SEC // 4, T0 + 3 * SEC, "dropout", 1.0, "c1")]
    table = build_table(stamps, values, JOINTS, intervals)
    kinds = table.column("fault_kind").to_pylist()
    n_samples = table.column("n_samples").to_pylist()
    # No row is both empty and normal (that is the idle case we drop).
    assert not any(n == 0 and k == "none" for n, k in zip(n_samples, kinds, strict=True))
    # The dropout window (empty, but within the fault) survives.
    assert any(n == 0 and k == "dropout" for n, k in zip(n_samples, kinds, strict=True))


def test_label_balance_counts() -> None:
    stamps, values = _stream()
    intervals = [FaultInterval(T0 + 2 * SEC, T0 + 3 * SEC, "stuck", 1.0, "c1")]
    balance = label_balance(build_table(stamps, values, JOINTS, intervals))
    assert balance["stuck"] == 3
    assert balance["none"] == 3
    assert sum(balance.values()) == 6
