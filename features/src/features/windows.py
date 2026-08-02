"""Time-based windowing over aligned joint telemetry. numpy-only, no I/O.

A window is a fixed wall-clock span, not a fixed sample count — chosen so
that a comms drop-out (missing samples) shows up as a *sparse* window
rather than a window that reaches further back in time. ``n_samples`` then
becomes the drop-out feature (ADR-0003).

Sample layout is fixed by contract: ``values`` has shape ``(T, J, 3)`` with
the last axis ordered ``[position, velocity, effort]``, aligned row-for-row
with ``stamps_ns``. The pipeline builds that array; features never reads a
file to get it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

# The two knobs ADR-0003 argues. Changing either changes every feature
# vector, so both live here (versioned) and nowhere else.
WINDOW_LENGTH_NS = 1_000_000_000  # 1.0 s — long enough for velocity RMS to mean something
WINDOW_HOP_NS = 500_000_000  # 0.5 s — 50% overlap, so detection isn't hostage to phase


@dataclass(frozen=True, slots=True)
class WindowSpec:
    length_ns: int
    hop_ns: int


DEFAULT_SPEC = WindowSpec(length_ns=WINDOW_LENGTH_NS, hop_ns=WINDOW_HOP_NS)


@dataclass(frozen=True, slots=True)
class Window:
    """One window's samples. May be empty (a fully dropped-out span)."""

    start_ns: int
    end_ns: int
    stamps_ns: npt.NDArray[np.int64]  # (n,)
    values: npt.NDArray[np.float64]  # (n, J, 3): [position, velocity, effort]

    @property
    def n_samples(self) -> int:
        return int(self.stamps_ns.shape[0])


def make_windows(
    stamps_ns: npt.NDArray[np.int64],
    values: npt.NDArray[np.float64],
    spec: WindowSpec = DEFAULT_SPEC,
) -> list[Window]:
    """Slice a time-sorted stream into full, overlapping windows.

    Only windows whose whole span is covered by data are emitted; the final
    partial tail (< one length after the last full window) is dropped.
    Deterministic: integer time arithmetic, no floats.
    """
    if stamps_ns.shape[0] == 0:
        return []
    t0 = int(stamps_ns[0])
    t_last = int(stamps_ns[-1])
    windows: list[Window] = []
    start = t0
    while start + spec.length_ns <= t_last:
        end = start + spec.length_ns
        lo = int(np.searchsorted(stamps_ns, start, side="left"))
        hi = int(np.searchsorted(stamps_ns, end, side="left"))
        windows.append(Window(start, end, stamps_ns[lo:hi], values[lo:hi]))
        start += spec.hop_ns
    return windows
