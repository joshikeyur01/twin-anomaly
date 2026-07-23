"""MQTT → RollingWindow → StateHub.

Telemetry folds into the window as it arrives; a fixed-rate broadcast task
rebuilds TwinState and publishes it to the hub. Decoupling the two means
forward kinematics runs at the publish rate (~50 Hz), not the message rate
(6 joints * 3 fields * 50 Hz = 900 msg/s).

Broker loss flips readiness and retries forever — same policy as
telemetry-svc, same reason: recovery must need no manual step.
"""

from __future__ import annotations

import asyncio

import aiomqtt
import structlog
from prometheus_client import Counter
from pydantic import ValidationError

from contracts import (
    UR5_JOINT_NAMES,
    JointTelemetry,
    parse_telemetry_topic,
    telemetry_wildcard,
)
from state_svc.config import StateConfig
from state_svc.grpc_server import StateHub, build_state
from state_svc.window import RollingWindow

log = structlog.get_logger()

MESSAGES = Counter("twin_state_messages_total", "Telemetry messages received from MQTT.")
REJECTED = Counter(
    "twin_state_rejected_total",
    "Messages dropped for failing the contract.",
    ["reason"],  # "topic" | "joint" | "payload"
)
PUBLISHED = Counter("twin_state_published_total", "TwinStates published to the hub.")

RECONNECT_DELAY_S = 2.0


class Consumer:
    """Owns the MQTT→window→hub pipeline and reports its readiness."""

    def __init__(self, config: StateConfig, window: RollingWindow, hub: StateHub) -> None:
        self._config = config
        self._window = window
        self._hub = hub
        self._mqtt_connected = False
        self._dirty = False

    def readiness(self) -> dict[str, bool]:
        return {"mqtt": self._mqtt_connected}

    async def run(self) -> None:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._consume_forever(), name="consume")
            tg.create_task(self._broadcast_forever(), name="broadcast")

    async def _consume_forever(self) -> None:
        while True:
            try:
                await self._consume()
            except aiomqtt.MqttError as exc:
                self._mqtt_connected = False
                log.warning("mqtt_disconnected", error=str(exc), retry_in_s=RECONNECT_DELAY_S)
                await asyncio.sleep(RECONNECT_DELAY_S)

    async def _consume(self) -> None:
        cfg = self._config
        async with aiomqtt.Client(cfg.mqtt_host, cfg.mqtt_port) as mqtt:
            self._mqtt_connected = True
            topic_filter = telemetry_wildcard(cfg.asset_name)
            await mqtt.subscribe(topic_filter)
            log.info("consuming", topic=topic_filter)
            async for message in mqtt.messages:
                MESSAGES.inc()
                self._observe(str(message.topic), message.payload)

    def _observe(self, topic: str, payload: object) -> None:
        try:
            _asset, joint, field = parse_telemetry_topic(topic)
        except ValueError:
            REJECTED.labels(reason="topic").inc()
            return
        if joint not in UR5_JOINT_NAMES:
            REJECTED.labels(reason="joint").inc()
            return
        if not isinstance(payload, bytes | str):
            REJECTED.labels(reason="payload").inc()
            return
        try:
            sample = JointTelemetry.model_validate_json(payload)
        except ValidationError:
            REJECTED.labels(reason="payload").inc()
            return
        self._window.observe(joint, field, sample)
        self._dirty = True

    async def _broadcast_forever(self) -> None:
        interval = 1.0 / self._config.state_rate_hz
        while True:
            await asyncio.sleep(interval)
            if not self._dirty:
                continue
            self._dirty = False
            state = build_state(self._config.asset_name, self._window, self._config.rms_window_s)
            if state is not None:
                self._hub.publish(state)
                PUBLISHED.inc()
