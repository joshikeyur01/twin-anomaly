"""The artefact manifest: everything about a model except the model itself.

Plain JSON (not the joblib blob) so ``git log -p models/`` diffs the metrics
of every retrain. Carries the threshold — the operating point travels with
the model, never in service config (ADR-0004) — and the ``features_version``
the model was trained against, which ``anomaly-svc`` checks against its own
before it will serve (ADR-0003).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True, slots=True)
class Manifest:
    stem: str  # "isoforest-v1"
    model_kind: str  # "forest" | "rule"
    features_version: str
    threshold: float
    seed: int
    trained_at: str  # ISO date
    dataset_fingerprint: str  # sha256 of the training parquet
    n_train: int
    metrics: dict[str, object] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, text: str) -> Manifest:
        return cls(**json.loads(text))
