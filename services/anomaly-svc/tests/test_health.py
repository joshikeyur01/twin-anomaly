"""Health surface tests — the same contract every twin service honours."""

from fastapi.testclient import TestClient

from anomaly_svc.health import build_health_app


def test_live_always_ok() -> None:
    client = TestClient(build_health_app("anomaly-svc", lambda: {"model": False}))
    assert client.get("/healthz/live").status_code == 200


def test_all_deps_up_is_ready() -> None:
    ready = {"mqtt": True, "model": True, "features_version": True}
    client = TestClient(build_health_app("anomaly-svc", lambda: ready))
    body = client.get("/healthz/ready")
    assert body.status_code == 200
    assert body.json()["status"] == "ready"


def test_features_mismatch_degrades() -> None:
    # A loaded model whose features version doesn't match ours must not serve.
    checks = {"mqtt": True, "model": True, "features_version": False}
    client = TestClient(build_health_app("anomaly-svc", lambda: checks))
    body = client.get("/healthz/ready")
    assert body.status_code == 503
    assert body.json()["checks"]["features_version"] is False


def test_metrics_exports_ready_gauge() -> None:
    client = TestClient(build_health_app("anomaly-svc", lambda: {"mqtt": True}))
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "twin_service_ready" in response.text
