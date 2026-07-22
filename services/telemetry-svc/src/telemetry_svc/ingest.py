"""MQTT → contract validation → InfluxDB.

The loop is the service: subscribe to the telemetry wildcard and the fault
label topic, validate every payload against contracts, write points. Invalid
input is counted and dropped — never written, never fatal. Broker loss flips
readiness and retries forever; recovery needs no manual step (the chaos demo
depends on this).

twin-anomaly delta: this service is the sole InfluxDB writer, so the
injector's ``FaultState`` labels reach storage here — as MQTT messages it
persists to the ``fault_state`` measurement — never as direct writes.
"""

from __future__ import annotations

import asyncio

import aiomqtt
import structlog
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from influxdb_client.client.write.point import Point
from influxdb_client.domain.write_precision import WritePrecision
from prometheus_client import Counter
from pydantic import ValidationError

from contracts import (
    AnomalyScore,
    FaultState,
    JointTelemetry,
    anomaly_score_topic,
    fault_state_topic,
    parse_telemetry_topic,
    telemetry_wildcard,
)
from telemetry_svc.config import TelemetryConfig

log = structlog.get_logger()

MESSAGES = Counter("twin_telemetry_messages_total", "Telemetry messages received from MQTT.")
REJECTED = Counter(
    "twin_telemetry_rejected_total",
    "Messages dropped for failing the contract.",
    ["reason"],  # "topic" | "payload"
)
WRITE_FAILURES = Counter("twin_influx_write_failures_total", "InfluxDB writes that raised.")
FAULT_LABELS = Counter(
    "twin_telemetry_fault_labels_total", "FaultState labels persisted to fault_state."
)
ANOMALY_SCORES = Counter(
    "twin_telemetry_anomaly_scores_total", "AnomalyScores persisted to anomaly_score."
)

RECONNECT_DELAY_S = 2.0


class Ingestor:
    """Owns the MQTT→InfluxDB loop and reports its readiness."""

    def __init__(self, config: TelemetryConfig) -> None:
        self._config = config
        self._mqtt_connected = False
        self._influx_ok = False

    def readiness(self) -> dict[str, bool]:
        return {"mqtt": self._mqtt_connected, "influxdb": self._influx_ok}

    async def run(self) -> None:
        """Consume telemetry forever; reconnect with a fixed delay on broker loss."""
        while True:
            try:
                await self._consume()
            except aiomqtt.MqttError as exc:
                self._mqtt_connected = False
                log.warning("mqtt_disconnected", error=str(exc), retry_in_s=RECONNECT_DELAY_S)
                await asyncio.sleep(RECONNECT_DELAY_S)

    async def _consume(self) -> None:
        cfg = self._config
        async with (
            InfluxDBClientAsync(
                url=cfg.influx_url, token=cfg.influx_token, org=cfg.influx_org
            ) as influx,
            aiomqtt.Client(cfg.mqtt_host, cfg.mqtt_port) as mqtt,
        ):
            self._mqtt_connected = True
            self._influx_ok = await influx.ping()
            write_api = influx.write_api()
            topic_filter = telemetry_wildcard(cfg.asset_name)
            label_topic = fault_state_topic(cfg.asset_name)
            score_topic = anomaly_score_topic(cfg.asset_name)
            await mqtt.subscribe(topic_filter)
            await mqtt.subscribe(label_topic, qos=1)  # a lost label poisons the dataset
            await mqtt.subscribe(score_topic)  # QoS 0, like telemetry
            log.info(
                "consuming",
                topics=[topic_filter, label_topic, score_topic],
                influx=cfg.influx_url,
            )

            async for message in mqtt.messages:
                MESSAGES.inc()
                raw = message.payload
                if not isinstance(raw, bytes | str):
                    REJECTED.labels(reason="payload").inc()
                    continue
                topic = str(message.topic)
                if topic == label_topic:
                    point = _fault_point(cfg.asset_name, raw)
                elif topic == score_topic:
                    point = _score_point(cfg.asset_name, raw)
                else:
                    point = _to_point(topic, raw)
                if point is None:
                    continue
                try:
                    await write_api.write(bucket=cfg.influx_bucket, record=point)
                    self._influx_ok = True
                # The influx client raises many types; a write must never kill ingest.
                except Exception as exc:
                    WRITE_FAILURES.inc()
                    self._influx_ok = False
                    log.warning("influx_write_failed", error=str(exc))


def _to_point(topic: str, payload: bytes | str) -> Point | None:
    """One validated telemetry message becomes one point; anything else, None."""
    try:
        asset, joint, field = parse_telemetry_topic(topic)
    except ValueError:
        REJECTED.labels(reason="topic").inc()
        return None
    try:
        sample = JointTelemetry.model_validate_json(payload)
    except ValidationError:
        REJECTED.labels(reason="payload").inc()
        return None
    point: Point = (
        Point("joint_telemetry")
        .tag("asset", asset)
        .tag("joint", joint)
        .tag("metric", field.value)
        .field("value", sample.value)
        .time(sample.stamp_ns, WritePrecision.NS)
    )
    return point


def _fault_point(asset: str, payload: bytes | str) -> Point | None:
    """One validated FaultState label becomes one ``fault_state`` point.

    ``kind`` and ``joint`` are tags (the pipeline groups by them);
    ``command_id`` is a field — one value per experiment would explode tag
    cardinality for no query benefit. ``joint=all`` keeps the series key
    stable when a fault is untargeted.
    """
    try:
        state = FaultState.model_validate_json(payload)
    except ValidationError:
        REJECTED.labels(reason="payload").inc()
        return None
    FAULT_LABELS.inc()
    point: Point = (
        Point("fault_state")
        .tag("asset", asset)
        .tag("kind", state.kind.value)
        .tag("joint", state.joint or "all")
        .field("active", state.active)
        .field("severity", state.severity)
        .field("command_id", state.command_id)
        .field("started_ns", state.started_ns)
        .time(state.stamp_ns, WritePrecision.NS)
    )
    return point


def _score_point(asset: str, payload: bytes | str) -> Point | None:
    """One validated AnomalyScore becomes one ``anomaly_score`` point.

    Timestamped at the window's end so the score lines up on Grafana with the
    telemetry it scored. ``artefact`` (the model version) is a tag so panels
    can group by model; score/threshold/verdict are the fields.
    """
    try:
        score = AnomalyScore.model_validate_json(payload)
    except ValidationError:
        REJECTED.labels(reason="payload").inc()
        return None
    ANOMALY_SCORES.inc()
    point: Point = (
        Point("anomaly_score")
        .tag("asset", asset)
        .tag("artefact", score.artefact)
        .field("score", score.score)
        .field("threshold", score.threshold)
        .field("verdict", int(score.verdict))
        .time(score.window_end_ns, WritePrecision.NS)
    )
    return point
