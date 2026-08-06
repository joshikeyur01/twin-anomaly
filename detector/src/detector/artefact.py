"""Save and load a detector as a versioned artefact pair.

``<stem>.joblib`` is the pickled fitted Scorer (model + scaler + bands);
``<stem>.json`` is its Manifest. The pickle is loadable only because the
detector classes live in this package, imported at both train and serve
time — the coupling that guarantees anomaly-svc scores with the same code
the evaluation table was built from.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import joblib

from detector.base import Scorer
from detector.manifest import Manifest


def dataset_fingerprint(parquet_path: Path) -> str:
    """sha256 of the training parquet — pins each model to its exact data."""
    return hashlib.sha256(parquet_path.read_bytes()).hexdigest()


def save_detector(detector: Scorer, manifest: Manifest, models_dir: Path) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(detector, models_dir / f"{manifest.stem}.joblib")
    (models_dir / f"{manifest.stem}.json").write_text(manifest.to_json())
    return models_dir / f"{manifest.stem}.joblib"


def load_detector(stem: str, models_dir: Path) -> tuple[Scorer, Manifest]:
    detector: Scorer = joblib.load(models_dir / f"{stem}.joblib")
    manifest = Manifest.from_json((models_dir / f"{stem}.json").read_text())
    return detector, manifest
