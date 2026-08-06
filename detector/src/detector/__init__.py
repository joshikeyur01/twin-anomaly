"""Detectors, manifests, and evaluation for twin-anomaly.

The scoring half of the skew defence: notebooks fit and evaluate with this
code, ``anomaly-svc`` loads and serves with it, and the artefact is a
pickled instance of a class defined here — so the evaluation table and
production score the same way, or not at all.
"""

from __future__ import annotations

from detector.artefact import dataset_fingerprint, load_detector, save_detector
from detector.base import Scorer, choose_threshold, verdicts
from detector.baseline import RuleDetector, fit_rule
from detector.evaluate import Evaluation, evaluate, markdown_table
from detector.forest import ForestDetector, fit_forest
from detector.manifest import Manifest

__all__ = [
    "Evaluation",
    "ForestDetector",
    "Manifest",
    "RuleDetector",
    "Scorer",
    "choose_threshold",
    "dataset_fingerprint",
    "evaluate",
    "fit_forest",
    "fit_rule",
    "load_detector",
    "markdown_table",
    "save_detector",
    "verdicts",
]
