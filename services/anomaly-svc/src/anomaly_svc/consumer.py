"""MQTT telemetry → rolling window → AnomalyScore, published every hop.

Telemetry folds into the window as it arrives; a fixed-rate task scores the
current window and publishes an ``AnomalyScore`` on the anomaly topic
(QoS 0, like telemetry) — telemetry-svc persists it. Scoring runs at the hop
rate, not the message rate, so features are computed twice a second, not
900 times.

Broker loss flips readiness and retries forever — the inherited policy.
"""

from __future__ import annotations

import asyncio

import aiomqtt
import structlog
from prometheus_client import Counter, Gauge
from pydantic import ValidationError

from anomaly_svc.config import AnomalyConfig
from anomaly_svc.scorer import Scorer
from anomaly_svc.window import AnomalyWindow
from contracts import (
    UR5_JOINT_NAMES,
    JointTelemetry,
    anomaly_score_topic,
    parse_telemetry_topic,
    telemetry_wildcard,
)
from features import WINDOW_HOP_NS

log = structlog.get_logger()

SCORE = Gauge("twin_anomaly_score", "Most recent anomaly score.", ["model_version"])
VERDICT = Gauge(
    "twin_anomaly_verdict", "1 if the latest window is anomalous, else 0.", ["model_version"]
)
SCORED = Counter("twin_anomaly_windows_scored_total", "Windows scored and published.")
REJECTED = Counter("twin_anomaly_rejected_total", "Telemetry dropped for failing the contract.")

RECONNECT_DELAY_S = 2.0


class Consumer:
    """Owns the MQTT→window→score→publish loop and reports its readiness."""

    def __init__(self, config: AnomalyConfig, window: AnomalyWindow, scorer: Scorer | None) -> None:
        self._config = config
        self._window = window
        self._scorer = scorer
        self._mqtt_connected = False

    def readiness(self) -> dict[str, bool]:
        # The three dependencies STYLE.md names: broker, artefact, and that
        # the artefact's features version matches ours (else scores are skew).
        return {
            "mqtt": self._mqtt_connected,
            "model": self._scorer is not None,
            "features_version": self._scorer is not None
            and self._scorer.features_version_matches(),
        }

    async def run(self) -> None:
        while True:
            try:
                await self._consume()
            except* aiomqtt.MqttError as exc:
                self._mqtt_connected = False
                log.warning("mqtt_disconnected", error=str(exc.exceptions[0]))
                await asyncio.sleep(RECONNECT_DELAY_S)

    async def _consume(self) -> None:
        cfg = self._config
        async with aiomqtt.Client(cfg.mqtt_host, cfg.mqtt_port) as client:
            self._mqtt_connected = True
            await client.subscribe(telemetry_wildcard(cfg.asset_name))
            log.info("consuming", topic=telemetry_wildcard(cfg.asset_name))
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._read(client))
                tg.create_task(self._score_loop(client))

    async def _read(self, client: aiomqtt.Client) -> None:
        async for message in client.messages:
            self._observe(str(message.topic), message.payload)

    def _observe(self, topic: str, payload: object) -> None:
        try:
            _asset, joint, field = parse_telemetry_topic(topic)
        except ValueError:
            REJECTED.inc()
            return
        if joint not in UR5_JOINT_NAMES or not isinstance(payload, bytes | str):
            REJECTED.inc()
            return
        try:
            sample = JointTelemetry.model_validate_json(payload)
        except ValidationError:
            REJECTED.inc()
            return
        self._window.observe(joint, field, sample)

    async def _score_loop(self, client: aiomqtt.Client) -> None:
        hop_s = WINDOW_HOP_NS / 1e9
        while True:
            await asyncio.sleep(hop_s)
            if self._scorer is None:
                continue
            window = self._window.to_window()
            if window is None:
                continue
            score = self._scorer.score_window(window)
            await client.publish(
                anomaly_score_topic(self._config.asset_name), score.model_dump_json(), qos=0
            )
            SCORE.labels(model_version=score.artefact).set(score.score)
            VERDICT.labels(model_version=score.artefact).set(int(score.verdict))
            SCORED.inc()
