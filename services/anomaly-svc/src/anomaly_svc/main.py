"""Entrypoint: load the pinned model, then run the scorer and HTTP server.

Readiness is honest about the model: if the artefact is missing (a fresh
clone without `just lfs`), or its features version doesn't match ours, the
service stays alive but not ready — it never serves silently-wrong scores.
Crash policy inherited from twin-services: fail fast, let the restart policy
revive us.
"""

from __future__ import annotations

import asyncio
import logging

import structlog
import uvicorn

from anomaly_svc.api import build_app
from anomaly_svc.config import AnomalyConfig
from anomaly_svc.consumer import Consumer
from anomaly_svc.scorer import Scorer
from anomaly_svc.window import AnomalyWindow
from features import WINDOW_LENGTH_NS

log = structlog.get_logger()


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )


def load_scorer(config: AnomalyConfig) -> Scorer | None:
    """Load the pinned artefact; None (not a crash) if it can't be served."""
    try:
        scorer = Scorer.load(config.model_path)
    except (FileNotFoundError, OSError, KeyError) as exc:
        log.error("model_load_failed", path=str(config.model_path), error=str(exc))
        return None
    if not scorer.features_version_matches():
        log.error("features_version_mismatch", artefact=scorer.model_version)
    else:
        log.info("model_loaded", artefact=scorer.model_version)
    return scorer


async def main() -> None:
    configure_logging()
    config = AnomalyConfig.from_env()
    scorer = load_scorer(config)
    window = AnomalyWindow(WINDOW_LENGTH_NS)
    consumer = Consumer(config, window, scorer)
    app = build_app("anomaly-svc", consumer.readiness, scorer)
    server = uvicorn.Server(
        uvicorn.Config(app, host="0.0.0.0", port=config.http_port, log_level="warning")
    )
    log.info("starting", http_port=config.http_port, model_path=str(config.model_path))

    async with asyncio.TaskGroup() as tg:
        tg.create_task(consumer.run(), name="consume")
        tg.create_task(server.serve(), name="http")


if __name__ == "__main__":
    asyncio.run(main())
