"""Injector entrypoint: the passthrough node plus its MQTT fault loop.

Sensor path: subscribes ``/joint_states_raw``, applies the session's
active transform in the ROS callback (synchronously — transforms are
cheap, and a dropped sample is a ``None`` return, not a queue), and
republishes ``/joint_states`` for the unchanged twin-services bridge.

Fault path: an aiomqtt worker listens on ``twin/<asset>/fault/cmd``
(QoS 1) and heartbeats ``FaultState`` labels on ``twin/<asset>/fault/state``
(QoS 1, 1 Hz). Labels are out-of-band from telemetry by construction: the
drop-out transform silences the sensor path, never this loop.

ROS imports stay lazy so unit tests run without a ROS 2 environment
(bridge convention).
"""

from __future__ import annotations

import asyncio
import signal
import threading
from contextlib import suppress
from typing import Any

import aiomqtt
import structlog
from pydantic import ValidationError

from contracts import FaultCommand, FaultKind, FaultState, fault_cmd_topic, fault_state_topic
from fault_injector.config import InjectorConfig
from fault_injector.session import FaultSession
from fault_injector.transforms import JointSnapshot

log = structlog.get_logger()

HEARTBEAT_S = 1.0


async def _publish_state(client: aiomqtt.Client, asset: str, state: FaultState) -> None:
    await client.publish(fault_state_topic(asset), state.model_dump_json(), qos=1)


async def command_listener(client: aiomqtt.Client, session: FaultSession, asset: str) -> None:
    """Apply each valid FaultCommand; publish labels at injection time."""
    async for message in client.messages:
        raw = message.payload
        if not isinstance(raw, bytes | str):
            continue
        try:
            cmd = FaultCommand.model_validate_json(raw)
        except ValidationError as exc:
            log.warning("fault.invalid", error=str(exc))
            continue
        # Ending first: replacement and clear both close the running
        # interval, so no labelled window is ever left open.
        closing = session.clear()
        if closing is not None:
            await _publish_state(client, asset, closing)
            log.info("fault.ended", command_id=closing.command_id, reason="superseded")
        if cmd.kind is FaultKind.NONE:
            continue
        opening = session.activate(cmd)
        await _publish_state(client, asset, opening)
        log.info(
            "fault.started",
            kind=cmd.kind.value,
            joint=cmd.joint,
            severity=cmd.severity,
            duration_s=cmd.duration_s,
            command_id=cmd.command_id,
        )


async def heartbeat_loop(client: aiomqtt.Client, session: FaultSession, asset: str) -> None:
    """1 Hz labels while active; the closing label when the duration lapses."""
    while True:
        await asyncio.sleep(HEARTBEAT_S)
        closing = session.expire_if_due()
        if closing is not None:
            await _publish_state(client, asset, closing)
            log.info("fault.ended", command_id=closing.command_id, reason="expired")
            continue
        beat = session.heartbeat()
        if beat is not None:
            await _publish_state(client, asset, beat)


async def fault_worker(config: InjectorConfig, session: FaultSession) -> None:
    """Own the MQTT connection; reconnect forever, like the bridge."""
    topic = fault_cmd_topic(config.asset_name)
    while True:
        try:
            async with aiomqtt.Client(config.mqtt_host, port=config.mqtt_port) as client:
                await client.subscribe(topic, qos=1)
                log.info("fault.listening", topic=topic)
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(command_listener(client, session, config.asset_name))
                    tg.create_task(heartbeat_loop(client, session, config.asset_name))
        except* aiomqtt.MqttError as exc:
            log.warning("mqtt.reconnect", error=str(exc.exceptions[0]))
            await asyncio.sleep(2.0)


def start_ros_node(config: InjectorConfig, session: FaultSession) -> Any:
    """Spin the sensor-path node on a daemon thread. Imports ROS lazily."""
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import JointState

    class InjectorNode(Node):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__("twin_anomaly_fault_injector")
            self.create_subscription(JointState, config.ros_in_topic, self._on_msg, 10)
            self._pub = self.create_publisher(JointState, config.ros_out_topic, 10)

        def _on_msg(self, msg: JointState) -> None:
            snapshot = JointSnapshot(
                stamp_ns=msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec,
                names=tuple(msg.name),
                positions=tuple(msg.position),
                velocities=tuple(msg.velocity),
                efforts=tuple(msg.effort),
            )
            result = session.apply(snapshot)
            if result is None:  # comms drop-out: the sample never happened
                return
            out = JointState()
            out.header = msg.header
            out.name = list(result.names)
            out.position = list(result.positions)
            out.velocity = list(result.velocities)
            out.effort = list(result.efforts)
            self._pub.publish(out)

    node_box: list[Any] = []
    ready = threading.Event()

    def _spin() -> None:
        rclpy.init()
        node = InjectorNode()
        node_box.append(node)
        ready.set()
        try:
            rclpy.spin(node)
        finally:
            node.destroy_node()
            rclpy.shutdown()

    thread = threading.Thread(target=_spin, name="rclpy-spin", daemon=True)
    thread.start()
    ready.wait(timeout=10)
    return node_box[0]


async def main_async() -> None:
    config = InjectorConfig.from_env()
    session = FaultSession()
    start_ros_node(config, session)
    log.info("injector.started", ros_in=config.ros_in_topic, ros_out=config.ros_out_topic)

    worker = asyncio.create_task(fault_worker(config, session))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await stop.wait()
    log.info("injector.shutdown")
    worker.cancel()
    with suppress(asyncio.CancelledError):
        await worker


def main() -> None:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
