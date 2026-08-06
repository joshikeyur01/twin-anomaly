"""Detection metrics: per-fault recall, plus one precision and one FPR.

Recall is reported per fault kind because that is what ADR-0004 compares —
some faults are easy, some aren't, and an average hides exactly the finding
the thesis wants. Precision and the normal false-positive rate are single
numbers (a false alarm isn't attributable to a fault kind). ``score`` is
higher-is-more-anomalous; ``threshold`` comes from the manifest.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

NORMAL = "none"


@dataclass(frozen=True, slots=True)
class Evaluation:
    threshold: float
    precision: float  # of flagged windows, fraction truly faulty
    normal_fpr: float  # of normal windows, fraction flagged
    recall_by_kind: dict[str, float]
    support_by_kind: dict[str, int]

    def as_metrics(self) -> dict[str, object]:
        """Flatten for the manifest's metrics field."""
        return {
            "precision": round(self.precision, 4),
            "normal_fpr": round(self.normal_fpr, 4),
            "recall_by_kind": {k: round(v, 4) for k, v in self.recall_by_kind.items()},
            "support_by_kind": self.support_by_kind,
        }


def evaluate(
    scores: npt.NDArray[np.float64],
    kinds: list[str],
    threshold: float,
) -> Evaluation:
    """Score array + per-window true fault kind -> detection metrics."""
    flagged = scores >= threshold
    kind_array = np.asarray(kinds)
    is_fault = kind_array != NORMAL

    n_flagged = int(flagged.sum())
    precision = float((flagged & is_fault).sum() / n_flagged) if n_flagged else float("nan")

    normal_mask = ~is_fault
    n_normal = int(normal_mask.sum())
    normal_fpr = float(flagged[normal_mask].sum() / n_normal) if n_normal else float("nan")

    recall_by_kind: dict[str, float] = {}
    support_by_kind: dict[str, int] = {}
    for kind in sorted(set(kinds)):
        if kind == NORMAL:
            continue
        mask = kind_array == kind
        support_by_kind[kind] = int(mask.sum())
        recall_by_kind[kind] = float(flagged[mask].sum() / mask.sum())

    return Evaluation(threshold, precision, normal_fpr, recall_by_kind, support_by_kind)


def markdown_table(results: dict[str, Evaluation]) -> str:
    """One comparison table: detectors as columns, fault kinds as rows."""
    names = list(results)
    kinds = sorted({k for ev in results.values() for k in ev.recall_by_kind})
    lines = ["| metric | " + " | ".join(names) + " |"]
    lines.append("| --- | " + " | ".join("---" for _ in names) + " |")
    for kind in kinds:
        cells = [f"{results[n].recall_by_kind.get(kind, float('nan')):.2f}" for n in names]
        lines.append(f"| recall · {kind} | " + " | ".join(cells) + " |")
    lines.append(
        "| **precision** | " + " | ".join(f"{results[n].precision:.2f}" for n in names) + " |"
    )
    lines.append(
        "| **normal FPR** | " + " | ".join(f"{results[n].normal_fpr:.2f}" for n in names) + " |"
    )
    return "\n".join(lines)
