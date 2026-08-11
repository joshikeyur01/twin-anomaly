"""The repo's demo, as a pass/fail script — not a screencast.

Drives telemetry through the real injector while the running anomaly-svc
scores it, then asserts the claim the whole repo exists to make: the anomaly
score crosses its threshold inside every injected fault window, and stays
under it during normal running. Exits non-zero if a fault goes undetected or
normal running raises too many false alarms — so `just demo` can gate a
build, and the README GIF is just this script with Grafana open.

No ROS on this machine, so the sine generator stands in for Gazebo (as in
collect.py); everything from the sensor onward — injector, broker,
anomaly-svc, threshold — is the production path.
"""

from __future__ import annotations

import asyncio
import math
import sys
import time
from dataclasses import dataclass

import aiomqtt

from contracts import (
    UR5_JOINT_NAMES,
    AnomalyScore,
    FaultCommand,
    FaultKind,
    JointField,
    JointTelemetry,
    anomaly_score_topic,
    fault_cmd_topic,
    telemetry_topic,
)
from fault_injector.config import InjectorConfig
from fault_injector.main import fault_worker
from fault_injector.session import FaultSession
from fault_injector.transforms import JointSnapshot
from features import WINDOW_LENGTH_NS

RATE_HZ = 50.0
LAG_S = WINDOW_LENGTH_NS / 1e9  # a window must fill with fault data before it can show it
NORMAL_FPR_TOLERANCE = 0.15  # a couple of false alarms over the normal stretches is allowed


@dataclass(frozen=True)
class Segment:
    kind: FaultKind
    duration_s: float
    joint: str | None = None
    severity: float = 1.0
    seed: int = 0


SCHEDULE: list[Segment] = [
    Segment(FaultKind.NONE, 7),
    Segment(FaultKind.FRICTION, 7, severity=2.0),
    Segment(FaultKind.NONE, 6),
    # Encoder is the served forest's weakest fault (ADR-0004: 0.20 recall at
    # low severity), so the demo injects it strongly — all joints, high
    # severity — to gate reliably. The honest per-severity recall lives in
    # EVALUATION.md; this segment shows the loop works, not that encoder is easy.
    Segment(FaultKind.ENCODER, 8, severity=6.0, seed=7),
    Segment(FaultKind.NONE, 6),
    Segment(FaultKind.STUCK, 7, joint="elbow_joint"),
    Segment(FaultKind.NONE, 6),
    Segment(FaultKind.DROPOUT, 6),
    Segment(FaultKind.NONE, 7),
]


@dataclass
class Window:
    kind: FaultKind
    start: float
    end: float


scores: list[tuple[float, bool]] = []  # (arrival_monotonic, verdict)
windows: list[Window] = []


async def sensor_loop(session: FaultSession, client: aiomqtt.Client, duration_s: float) -> None:
    t0 = time.monotonic()
    while (t := time.monotonic() - t0) < duration_s:
        snapshot = JointSnapshot(
            stamp_ns=time.time_ns(),
            names=UR5_JOINT_NAMES,
            positions=tuple(0.5 * math.sin(0.5 * t + i * 0.6) for i in range(6)),
            velocities=tuple(0.25 * math.cos(0.5 * t + i * 0.6) for i in range(6)),
            efforts=(0.0,) * 6,
        )
        result = session.apply(snapshot)
        if result is not None:
            for i, name in enumerate(result.names):
                for field, value in (
                    (JointField.POSITION, result.positions[i]),
                    (JointField.VELOCITY, result.velocities[i]),
                    (JointField.EFFORT, result.efforts[i]),
                ):
                    await client.publish(
                        telemetry_topic("ur5", name, field),
                        JointTelemetry(value=value, stamp_ns=result.stamp_ns).model_dump_json(),
                    )
        await asyncio.sleep(1.0 / RATE_HZ)


async def schedule_loop(config: InjectorConfig, client: aiomqtt.Client) -> None:
    topic = fault_cmd_topic(config.asset_name)
    for segment in SCHEDULE:
        start = time.monotonic()
        if segment.kind is not FaultKind.NONE:
            cmd = FaultCommand(
                kind=segment.kind,
                joint=segment.joint,
                severity=segment.severity,
                duration_s=segment.duration_s,
                seed=segment.seed,
            )
            await client.publish(topic, cmd.model_dump_json(), qos=1)
        await asyncio.sleep(segment.duration_s)
        windows.append(Window(segment.kind, start, time.monotonic()))


async def collect_scores(client: aiomqtt.Client) -> None:
    await client.subscribe(anomaly_score_topic("ur5"))
    async for message in client.messages:
        if isinstance(message.payload, bytes | str):
            score = AnomalyScore.model_validate_json(message.payload)
            scores.append((time.monotonic(), score.verdict))


def evaluate() -> int:
    print(f"\n{'segment':>10} | {'windows':>7} | {'flagged':>7} | result")
    print("-" * 44)
    ok = True
    for window in windows:
        if window.kind is FaultKind.NONE:
            # Skip the post-fault lag at the segment head, where the window
            # still holds the previous fault's data; that is not a false alarm.
            verdicts = [v for (t, v) in scores if window.start + LAG_S <= t <= window.end]
            flagged = sum(verdicts)
            n = len(verdicts)
            fpr = flagged / n if n else 0.0
            passed = fpr <= NORMAL_FPR_TOLERANCE
            verdict = f"FPR {fpr:.0%} {'ok' if passed else 'TOO HIGH'}"
        else:
            # A fault is detected if any window overlapping it flags — include
            # the lag tail, since a drop-out surfaces as the window empties.
            verdicts = [v for (t, v) in scores if window.start <= t <= window.end + LAG_S]
            flagged = sum(verdicts)
            n = len(verdicts)
            passed = flagged > 0
            verdict = "DETECTED" if passed else "MISSED"
        ok = ok and passed
        print(f"{window.kind.value:>10} | {n:>7} | {flagged:>7} | {verdict}")
    print("-" * 44)
    print("PASS — every fault detected, normal running quiet" if ok else "FAIL — see above")
    return 0 if ok else 1


async def main() -> int:
    config = InjectorConfig.from_env()
    session = FaultSession()
    total = sum(s.duration_s for s in SCHEDULE)
    print(f"demo: {total:.0f}s, {len(SCHEDULE)} segments, scoring against the live anomaly-svc")

    worker = asyncio.create_task(fault_worker(config, session))
    async with (
        aiomqtt.Client(config.mqtt_host, port=config.mqtt_port) as sensor_client,
        aiomqtt.Client(config.mqtt_host, port=config.mqtt_port) as schedule_client,
        aiomqtt.Client(config.mqtt_host, port=config.mqtt_port) as score_client,
    ):
        collector = asyncio.create_task(collect_scores(score_client))
        await asyncio.sleep(0.5)
        await asyncio.gather(
            sensor_loop(session, sensor_client, total + LAG_S),
            schedule_loop(config, schedule_client),
        )
        await asyncio.sleep(LAG_S + 0.5)  # let the last windows score
        collector.cancel()
    worker.cancel()
    return evaluate()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
