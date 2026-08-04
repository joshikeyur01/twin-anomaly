"""Build the training corpus: a scripted fault schedule against the stack.

Drives 50 Hz sine telemetry through the *real* FaultSession while the *real*
fault_worker applies a timed schedule of FaultCommands over MQTT — the same
path `just inject` uses. telemetry-svc persists both the joint telemetry and
the fault labels, so afterwards `just dataset` turns the run into labelled
parquet. Normal stretches are interleaved with all four faults at varied
severities and targets, so every class appears in the corpus.

Where the real robot would be: the ~30-line rclpy adapter in
`fault_injector.main.start_ros_node`. This machine has no ROS, so the sine
generator stands in for Gazebo; everything downstream of the sensor is the
production code path.
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import aiomqtt

from contracts import (
    UR5_JOINT_NAMES,
    FaultCommand,
    FaultKind,
    JointField,
    JointTelemetry,
    fault_cmd_topic,
    telemetry_topic,
)
from fault_injector.config import InjectorConfig
from fault_injector.main import fault_worker
from fault_injector.session import FaultSession
from fault_injector.transforms import JointSnapshot

RATE_HZ = 50.0


@dataclass(frozen=True)
class Segment:
    kind: FaultKind
    duration_s: float
    joint: str | None = None
    severity: float = 1.0
    seed: int = 0


# One continuous run — no idle gaps, so the only empty windows are the
# labelled drop-outs. Build the dataset over exactly this run's span (main()
# prints the command); a dataset spanning the gaps between runs would fill
# the "normal" class with empty idle windows and poison training. Normal
# stretches sit between faults so each class is cleanly separable, and each
# fault appears twice at different severities/targets for a bit of variety.
SCHEDULE: list[Segment] = [
    Segment(FaultKind.NONE, 8),
    Segment(FaultKind.FRICTION, 8, severity=1.0),
    Segment(FaultKind.NONE, 5),
    Segment(FaultKind.ENCODER, 8, joint="elbow_joint", severity=2.0, seed=7),
    Segment(FaultKind.NONE, 5),
    Segment(FaultKind.STUCK, 8, joint="elbow_joint"),
    Segment(FaultKind.NONE, 5),
    Segment(FaultKind.DROPOUT, 6),
    Segment(FaultKind.NONE, 6),
    Segment(FaultKind.FRICTION, 7, joint="elbow_joint", severity=4.0),
    Segment(FaultKind.NONE, 5),
    Segment(FaultKind.ENCODER, 7, severity=3.0, seed=11),
    Segment(FaultKind.NONE, 5),
    Segment(FaultKind.STUCK, 7, joint="wrist_1_joint"),
    Segment(FaultKind.NONE, 5),
    Segment(FaultKind.DROPOUT, 5, severity=1.0),
    Segment(FaultKind.NONE, 8),
]


async def sensor_loop(session: FaultSession, client: aiomqtt.Client, duration_s: float) -> None:
    """Publish transformed 50 Hz sine telemetry until the schedule is done."""
    t0 = time.monotonic()
    published = dropped = 0
    while (t := time.monotonic() - t0) < duration_s:
        snapshot = JointSnapshot(
            stamp_ns=time.time_ns(),
            names=UR5_JOINT_NAMES,
            positions=tuple(0.5 * math.sin(0.5 * t + i * 0.6) for i in range(6)),
            velocities=tuple(0.25 * math.cos(0.5 * t + i * 0.6) for i in range(6)),
            efforts=(0.0,) * 6,
        )
        result = session.apply(snapshot)
        if result is None:
            dropped += 1
        else:
            published += 1
            for i, name in enumerate(result.names):
                for field, value in (
                    (JointField.POSITION, result.positions[i]),
                    (JointField.VELOCITY, result.velocities[i]),
                    (JointField.EFFORT, result.efforts[i]),
                ):
                    await client.publish(
                        telemetry_topic("ur5", name, field),
                        JointTelemetry(value=value, stamp_ns=result.stamp_ns).model_dump_json(),
                        qos=0,
                    )
        await asyncio.sleep(1.0 / RATE_HZ)
    print(f"sensor: {published} samples published, {dropped} dropped")


async def schedule_loop(config: InjectorConfig, client: aiomqtt.Client) -> None:
    """Publish each fault command at its segment start; normal segments wait."""
    topic = fault_cmd_topic(config.asset_name)
    for segment in SCHEDULE:
        if segment.kind is not FaultKind.NONE:
            cmd = FaultCommand(
                kind=segment.kind,
                joint=segment.joint,
                severity=segment.severity,
                duration_s=segment.duration_s,
                seed=segment.seed,
            )
            await client.publish(topic, cmd.model_dump_json(), qos=1)
            print(
                f"  inject {segment.kind.value} "
                f"joint={segment.joint} sev={segment.severity} for {segment.duration_s}s"
            )
        await asyncio.sleep(segment.duration_s)


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


async def main() -> None:
    config = InjectorConfig.from_env()
    session = FaultSession()
    total = sum(s.duration_s for s in SCHEDULE)
    print(f"collecting {total:.0f}s corpus across {len(SCHEDULE)} segments")

    start = _utc_now()
    worker = asyncio.create_task(fault_worker(config, session))
    async with (
        aiomqtt.Client(config.mqtt_host, port=config.mqtt_port) as sensor_client,
        aiomqtt.Client(config.mqtt_host, port=config.mqtt_port) as schedule_client,
    ):
        await asyncio.sleep(0.5)  # let the worker subscribe before the first command
        await asyncio.gather(
            sensor_loop(session, sensor_client, total + 1.0),
            schedule_loop(config, schedule_client),
        )
    worker.cancel()
    end = _utc_now()
    # Build the dataset over exactly this run's span — never a wider window,
    # which would sweep in empty idle windows between runs and poison normal.
    print("collection complete. Build the dataset over this run's span:")
    print(f"  just dataset --since={start} --until={end} --name=train")


if __name__ == "__main__":
    asyncio.run(main())
