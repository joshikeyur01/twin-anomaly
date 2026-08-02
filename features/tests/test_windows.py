"""Windowing arithmetic and edge cases — the dataset's meaning rests here."""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import numpy.typing as npt

from features import WindowSpec, make_windows
from features.windows import DEFAULT_SPEC

MS20 = 20_000_000  # 50 Hz
SEC = 1_000_000_000


def _regular(
    n: int, joints: int = 6, t0: int = 1_700_000_000 * SEC
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64]]:
    stamps = np.array([t0 + i * MS20 for i in range(n)], dtype=np.int64)
    values = np.zeros((n, joints, 3), dtype=np.float64)
    return stamps, values


def test_empty_stream_yields_no_windows() -> None:
    stamps = np.array([], dtype=np.int64)
    values = np.zeros((0, 6, 3), dtype=np.float64)
    assert make_windows(stamps, values) == []


def test_window_count_matches_formula() -> None:
    # 4 s of 50 Hz data, 1 s window, 0.5 s hop.
    stamps, values = _regular(200)
    windows = make_windows(stamps, values, DEFAULT_SPEC)
    span = int(stamps[-1] - stamps[0])
    expected = (span - DEFAULT_SPEC.length_ns) // DEFAULT_SPEC.hop_ns + 1
    assert len(windows) == expected == 6


def test_full_window_has_expected_samples() -> None:
    stamps, values = _regular(200)
    first = make_windows(stamps, values, DEFAULT_SPEC)[0]
    assert first.n_samples == 50  # 1 s at 50 Hz
    assert first.end_ns - first.start_ns == SEC


def test_windows_are_contiguous_by_hop() -> None:
    stamps, values = _regular(200)
    windows = make_windows(stamps, values, DEFAULT_SPEC)
    for earlier, later in pairwise(windows):
        assert later.start_ns - earlier.start_ns == DEFAULT_SPEC.hop_ns


def test_dropout_span_yields_sparse_window() -> None:
    # Drop every sample in [t0+2.0s, t0+2.5s): the window starting at 2.0 s
    # exists on the clock but is empty; n_samples carries the signal.
    stamps, values = _regular(200)
    t0 = int(stamps[0])
    keep = (stamps < t0 + 2 * SEC) | (stamps >= t0 + 2 * SEC + SEC // 2)
    stamps, values = stamps[keep], values[keep]
    windows = make_windows(stamps, values, WindowSpec(length_ns=SEC // 2, hop_ns=SEC // 2))
    empty = [w for w in windows if w.n_samples == 0]
    assert len(empty) == 1
    assert empty[0].start_ns == t0 + 2 * SEC


def test_partial_tail_is_dropped() -> None:
    # 1.4 s of data, 1 s window, 0.5 s hop → starts at 0 only (0.5+1=1.5>1.4).
    stamps, values = _regular(70)
    windows = make_windows(stamps, values, DEFAULT_SPEC)
    assert len(windows) == 1
