"""The labelling boundary policy: which fault, if any, owns a window.

The rule (ADR-0003): a window overlapping *any part* of a fault interval is
labelled with that fault. If several faults overlap the same window — only
possible at a hand-off between experiments — the one with the greatest
overlap wins, ties broken toward the earlier fault. ``None`` means normal;
the pipeline, which owns the fault-kind vocabulary, maps that to its label.

Kept here rather than in a notebook cell so the boundary is decided once,
versioned with the features it labels, and identical for every dataset.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FaultInterval:
    start_ns: int
    end_ns: int
    kind: str
    severity: float
    command_id: str


def label_window(
    start_ns: int, end_ns: int, intervals: list[FaultInterval]
) -> FaultInterval | None:
    """Return the fault owning ``[start_ns, end_ns)``, or None for normal."""
    best: FaultInterval | None = None
    best_overlap = 0
    for interval in intervals:
        overlap = min(end_ns, interval.end_ns) - max(start_ns, interval.start_ns)
        if overlap > best_overlap:
            best_overlap = overlap
            best = interval
    return best
