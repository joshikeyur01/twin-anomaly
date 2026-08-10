"""The HTTP surface: health/metrics plus POST /score.

POST /score is the offline entry point to the *same* scorer the live loop
uses — it exists so a notebook, a test, or a curl can get a score for an
explicit window without a broker. That shared path is the skew tripwire the
Phase 4 DoD checks: the number here must equal the number the live loop and
the evaluation notebook produce for the same samples.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, status

from anomaly_svc.health import ReadinessProbe, build_health_app
from anomaly_svc.scorer import Scorer
from contracts import AnomalyScore, WindowScoreRequest


def build_app(service: str, readiness: ReadinessProbe, scorer: Scorer | None) -> FastAPI:
    app = build_health_app(service, readiness)

    @app.post("/score")
    async def score(request: WindowScoreRequest) -> AnomalyScore:
        if scorer is None or not scorer.features_version_matches():
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "model not loaded or features version mismatch"
            )
        try:
            return scorer.score_request(request)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return app
