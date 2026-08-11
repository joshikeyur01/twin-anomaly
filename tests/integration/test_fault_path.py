"""The fault label path, end to end against the running stack (`just up`).

Two seams, tested separately so a failure names its culprit:
- label persistence: a FaultState published on the wire must land in the
  fault_state measurement (telemetry-svc's new subscription).
- the injector's MQTT loop: a FaultCommand on fault/cmd must produce an
  injection-time opening label on fault/state. Runs the real fault_worker
  in-process — no ROS required; the sensor path is not under test here.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request

import aiomqtt
import pytest

from contracts import (
    FaultCommand,
    FaultKind,
    FaultState,
    fault_cmd_topic,
    fault_state_topic,
)
from fault_injector.config import InjectorConfig
from fault_injector.main import fault_worker
from fault_injector.session import FaultSession

pytestmark = pytest.mark.slow

INFLUX = {
    "url": "http://localhost:8086",
    "token": "dev-token-change-me",
    "org": "twin",
    "bucket": "telemetry",
}


def _up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return bool(response.status == 200)
    except (urllib.error.URLError, OSError):
        return False


@pytest.fixture(autouse=True, scope="module")
def require_stack() -> None:
    if not (_up("http://localhost:8001/healthz/live") and _up(f"{INFLUX['url']}/health")):
        pytest.skip("compose stack not running — `just up` first")


def _flux_rows(query: str) -> str:
    request = urllib.request.Request(
        f"{INFLUX['url']}/api/v2/query?org={INFLUX['org']}",
        data=json.dumps({"query": query, "type": "flux"}).encode(),
        headers={
            "Authorization": f"Token {INFLUX['token']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode()


async def test_fault_label_is_persisted() -> None:
    state = FaultState(
        active=True,
        kind=FaultKind.ENCODER,
        severity=3.0,
        command_id=f"itest{time.time_ns()}",
        started_ns=time.time_ns(),
        stamp_ns=time.time_ns(),
    )
    async with aiomqtt.Client("localhost") as publisher:
        await publisher.publish(fault_state_topic("ur5"), state.model_dump_json(), qos=1)

    query = (
        f'from(bucket: "{INFLUX["bucket"]}") |> range(start: -2m)'
        ' |> filter(fn: (r) => r._measurement == "fault_state")'
        ' |> filter(fn: (r) => r._field == "command_id")'
    )
    for _ in range(20):  # telemetry-svc write latency
        if state.command_id in _flux_rows(query):
            break
        await asyncio.sleep(0.25)
    else:
        pytest.fail("fault_state row never appeared in InfluxDB")


async def test_command_produces_injection_time_label() -> None:
    session = FaultSession()
    worker = asyncio.create_task(fault_worker(InjectorConfig.from_env(), session))
    try:
        async with aiomqtt.Client("localhost") as subscriber:
            await subscriber.subscribe(fault_state_topic("ur5"), qos=1)
            await asyncio.sleep(0.3)  # let the worker subscribe too

            cmd = FaultCommand(kind=FaultKind.STUCK, joint="elbow_joint", duration_s=3)
            async with aiomqtt.Client("localhost") as publisher:
                await publisher.publish(fault_cmd_topic("ur5"), cmd.model_dump_json(), qos=1)

            async with asyncio.timeout(5):
                async for message in subscriber.messages:
                    assert isinstance(message.payload, bytes)
                    label = FaultState.model_validate_json(message.payload)
                    if label.command_id != cmd.command_id:
                        continue  # someone else's label; keep waiting
                    assert label.active and label.kind is FaultKind.STUCK
                    assert label.joint == "elbow_joint"
                    assert label.started_ns == label.stamp_ns  # injection time
                    break
    finally:
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
