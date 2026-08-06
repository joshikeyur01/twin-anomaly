"""Artefact round-trip and evaluation metrics."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from detector import (
    Manifest,
    evaluate,
    fit_rule,
    load_detector,
    markdown_table,
    save_detector,
)
from detector.artefact import dataset_fingerprint

NAMES = ["j__vel_rms", "j__pos_std"]


def test_artefact_roundtrip_preserves_scores(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    normal = rng.normal(1.0, 0.02, (200, 2)).astype(np.float64)
    rule = fit_rule(normal, NAMES)
    probe = np.array([[0.0, 0.5], [1.0, 0.01]], dtype=np.float64)
    manifest = Manifest(
        stem="rule-v1",
        model_kind="rule",
        features_version="0.1.0",
        threshold=0.5,
        seed=0,
        trained_at="2026-07-18",
        dataset_fingerprint="abc",
        n_train=200,
    )
    save_detector(rule, manifest, tmp_path)
    assert (tmp_path / "rule-v1.joblib").exists()
    assert (tmp_path / "rule-v1.json").exists()

    loaded, loaded_manifest = load_detector("rule-v1", tmp_path)
    assert np.array_equal(loaded.score(probe), rule.score(probe))
    assert loaded_manifest.threshold == 0.5
    assert loaded_manifest.features_version == "0.1.0"


def test_manifest_json_roundtrip() -> None:
    manifest = Manifest(
        stem="isoforest-v1",
        model_kind="forest",
        features_version="0.1.0",
        threshold=1.23,
        seed=42,
        trained_at="2026-07-18",
        dataset_fingerprint="deadbeef",
        n_train=296,
        metrics={"precision": 0.9},
    )
    assert Manifest.from_json(manifest.to_json()) == manifest


def test_fingerprint_changes_with_bytes(tmp_path: Path) -> None:
    a = tmp_path / "a.parquet"
    b = tmp_path / "b.parquet"
    a.write_bytes(b"one")
    b.write_bytes(b"two")
    assert dataset_fingerprint(a) != dataset_fingerprint(b)


def test_evaluate_metrics() -> None:
    # 4 windows: 2 normal (one wrongly flagged), 1 stuck (caught), 1 encoder (missed).
    scores = np.array([0.1, 0.9, 0.8, 0.2], dtype=np.float64)
    kinds = ["none", "none", "stuck", "encoder"]
    ev = evaluate(scores, kinds, threshold=0.5)
    assert ev.recall_by_kind == {"encoder": 0.0, "stuck": 1.0}
    assert ev.support_by_kind == {"encoder": 1, "stuck": 1}
    assert ev.normal_fpr == 0.5  # one of two normals flagged
    assert ev.precision == 0.5  # of two flagged, one truly faulty


def test_markdown_table_shape() -> None:
    scores = np.array([0.1, 0.9, 0.8], dtype=np.float64)
    kinds = ["none", "stuck", "encoder"]
    ev = evaluate(scores, kinds, threshold=0.5)
    table = markdown_table({"rule": ev, "isoforest": ev})
    assert "recall · stuck" in table
    assert "normal FPR" in table
    assert table.count("|") > 10
