"""Bridge entrypoint, vendored from twin-hello and extended.

Telemetry out: subscribes to /joint_states via rclpy, validates, republishes
one MQTT message per joint per field using the contracts wire format.
Commands in: subscribes to twin/<asset>/cmd/joints, validates JointCommand,
forwards it to the ROS 2 trajectory controller. Also serves /healthz.

Kept deliberately small so the whole pipeline is legible in one sitting.
ROS imports stay lazy so unit tests run without a ROS 2 environment.
"""

from __future__ import annotations

import asyncio
import signal
import threading
from contextlib import suppress
from typing import Any

import aiomqtt
import structlog
import uvicorn
from fastapi import FastAPI
from pydantic import ValidationError

from bridge.config import BridgeConfig
from bridge.models import JointStateMessage
from contracts import (
    UR5_JOINT_NAMES,
    CommandKind,
    JointCommand,
    JointField,
    JointTelemetry,
    command_topic,
    telemetry_topic,
)

log = structlog.get_logger()


def build_health_app() -> FastAPI:
    app = FastAPI(title="twin-services bridge")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


async def publish_joint_states(client: aiomqtt.Client, msg: JointStateMessage, asset: str) -> None:
    """One JointState becomes one contracts.JointTelemetry per joint per field."""
    if not msg.field_lengths_match():
        log.warning("bridge.length_mismatch", names=len(msg.names))
        return
    for i, name in enumerate(msg.names):
        for fld, value in (
            (JointField.POSITION, msg.positions[i]),
            (JointField.VELOCITY, msg.velocities[i]),
            (JointField.EFFORT, msg.efforts[i]),
        ):
            await client.publish(
                telemetry_topic(asset, name, fld),
                payload=JointTelemetry(value=value, stamp_ns=msg.stamp_ns).model_dump_json(),
                qos=0,
            )


async def telemetry_worker(config: BridgeConfig, queue: asyncio.Queue[JointStateMessage]) -> None:
    """Consume validated joint states and publish them. Reconnect on failure."""
    while True:
        try:
            async with aiomqtt.Client(config.mqtt_host, port=config.mqtt_port) as client:
                log.info("mqtt.connected", host=config.mqtt_host, port=config.mqtt_port)
                while True:
                    msg = await queue.get()
                    await publish_joint_states(client, msg, config.asset_name)
        except aiomqtt.MqttError as exc:
            log.warning("mqtt.reconnect", error=str(exc))
            await asyncio.sleep(2.0)


async def command_worker(config: BridgeConfig, node: Any) -> None:
    """Forward validated MQTT setpoints to the ROS 2 trajectory controller."""
    topic = command_topic(config.asset_name)
    while True:
        try:
            async with aiomqtt.Client(config.mqtt_host, port=config.mqtt_port) as client:
                await client.subscribe(topic, qos=1)
                log.info("cmd.listening", topic=topic)
                async for message in client.messages:
                    raw = message.payload
                    if not isinstance(raw, bytes | str):
                        continue
                    try:
                        cmd = JointCommand.model_validate_json(raw)
                    except ValidationError as exc:
                        log.warning("cmd.invalid", error=str(exc))
                        continue
                    node.publish_command(cmd)
                    log.info("cmd.forwarded", kind=cmd.kind.value)
        except aiomqtt.MqttError as exc:
            log.warning("cmd.reconnect", error=str(exc))
            await asyncio.sleep(2.0)


def start_ros_node(queue: asyncio.Queue[JointStateMessage], config: BridgeConfig) -> Any:
    """Start rclpy on a background thread; return the node.

    The node forwards /joint_states into the queue and exposes
    publish_command() for the command worker. Imported lazily so unit tests
    run without ROS 2.
    """
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import JointState
    from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

    loop = asyncio.get_event_loop()

    class BridgeNode(Node):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__("twin_services_bridge")
            self.create_subscription(JointState, config.ros_topic, self._on_msg, 10)
            self._cmd_pub = self.create_publisher(JointTrajectory, config.ros_cmd_topic, 10)

        def _on_msg(self, msg: JointState) -> None:
            try:
                validated = JointStateMessage(
                    stamp_ns=msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec,
                    names=list(msg.name),
                    positions=list(msg.position),
                    velocities=list(msg.velocity),
                    efforts=list(msg.effort),
                )
            except Exception as exc:  # the bridge must not die on bad msgs
                log.warning("bridge.validation_failed", error=str(exc))
                return
            asyncio.run_coroutine_threadsafe(queue.put(validated), loop)

        def publish_command(self, cmd: JointCommand) -> None:
            """Build a JointTrajectory from a contract command and publish it.

            Called from the asyncio thread; rclpy publishers are safe to call
            across threads.
            """
            if cmd.kind is CommandKind.HOME:
                names = list(UR5_JOINT_NAMES)
                positions = [0.0] * len(names)
            else:
                assert cmd.positions is not None  # the contract validator guarantees it
                names = list(cmd.positions)
                positions = [cmd.positions[n] for n in names]
            msg = JointTrajectory()
            msg.joint_names = names
            point = JointTrajectoryPoint()
            point.positions = positions
            point.time_from_start.sec = int(cmd.duration_s)
            point.time_from_start.nanosec = int((cmd.duration_s % 1.0) * 1e9)
            msg.points = [point]
            self._cmd_pub.publish(msg)

    node_box: list[Any] = []
    ready = threading.Event()

    def _spin() -> None:
        rclpy.init()
        node = BridgeNode()
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
    config = BridgeConfig.from_env()
    queue: asyncio.Queue[JointStateMessage] = asyncio.Queue(maxsize=1000)

    node = start_ros_node(queue, config)

    health_task = asyncio.create_task(
        uvicorn.Server(
            uvicorn.Config(
                build_health_app(),
                host="0.0.0.0",
                port=config.health_port,
                log_level="warning",
            )
        ).serve()
    )
    telemetry_task = asyncio.create_task(telemetry_worker(config, queue))
    command_task = asyncio.create_task(command_worker(config, node))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await stop.wait()
    log.info("bridge.shutdown")
    for task in (health_task, telemetry_task, command_task):
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def main() -> None:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
