"""POST /score: the offline entry to the same scorer, and the skew tripwire."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anomaly_svc.api import build_app
from anomaly_svc.scorer import Scorer
from contracts import WindowScoreRequest

REPO = Path(__file__).parents[3]
FIXTURE = json.loads((REPO / "data" / "fixtures" / "window.json").read_text())


def _ready() -> dict[str, bool]:
    return {"mqtt": True, "model": True, "features_version": True}


def test_score_returns_anomaly_score(scorer: Scorer) -> None:
    client = TestClient(build_app("anomaly-svc", _ready, scorer))
    response = client.post("/score", json=FIXTURE)
    assert response.status_code == 200
    body = response.json()
    assert body["artefact"] == "rule-v1"
    assert set(body) >= {"score", "threshold", "verdict", "features_version"}


def test_endpoint_matches_library(scorer: Scorer) -> None:
    # The DoD tripwire in miniature: the HTTP path returns exactly what the
    # scorer library computes for the same window.
    client = TestClient(build_app("anomaly-svc", _ready, scorer))
    body = client.post("/score", json=FIXTURE).json()
    library = scorer.score_request(WindowScoreRequest(**FIXTURE))
    assert body["score"] == pytest.approx(library.score)


def test_503_without_a_model() -> None:
    client = TestClient(build_app("anomaly-svc", _ready, None))
    assert client.post("/score", json=FIXTURE).status_code == 503


def test_422_on_missing_joint(scorer: Scorer) -> None:
    incomplete = {**FIXTURE, "joints": dict(list(FIXTURE["joints"].items())[:5])}
    client = TestClient(build_app("anomaly-svc", _ready, scorer))
    assert client.post("/score", json=incomplete).status_code == 422


@pytest.mark.model
def test_served_isoforest_flags_the_fixture() -> None:
    # Requires the real artefact (git-lfs). The fixture is a drop-out
    # signature the shipped model is expected to flag.
    scorer = Scorer.load(REPO / "models" / "isoforest-v1.joblib")
    score = scorer.score_request(WindowScoreRequest(**FIXTURE))
    assert score.artefact == "isoforest-v1"
    assert score.verdict is True
