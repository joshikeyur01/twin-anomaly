"""End-to-end tests against the running compose stack (`just up`).

Marked slow: they need Docker and a real network. They skip themselves when
the stack is not running, so `just test` stays green on a laptop without
Docker up.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request

import aiomqtt
import grpc
import pytest

from contracts import (
    UR5_JOINT_NAMES,
    CommandKind,
    JointCommand,
    JointField,
    JointTelemetry,
    command_topic,
    telemetry_topic,
)
from contracts.gen import state_pb2, state_pb2_grpc

pytestmark = pytest.mark.slow

PORTS = {"telemetry-svc": 8001, "state-svc": 8002, "command-svc": 8003, "viz-svc": 8004}
ZERO_POSE_X = -0.81725


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _stack_is_up() -> bool:
    try:
        return all(_get(f"http://localhost:{p}/healthz/live")[0] == 200 for p in PORTS.values())
    except (urllib.error.URLError, OSError):
        return False


@pytest.fixture(autouse=True, scope="module")
def require_stack() -> None:
    if not _stack_is_up():
        pytest.skip("compose stack not running — `just up` first")


def test_all_services_ready() -> None:
    for name, port in PORTS.items():
        status, body = _get(f"http://localhost:{port}/healthz/ready")
        assert status == 200, f"{name} not ready: {body!r}"


async def test_command_arrives_on_the_wire() -> None:
    async with aiomqtt.Client("localhost") as subscriber:
        await subscriber.subscribe(command_topic("ur5"), qos=1)

        def _post() -> tuple[int, bytes]:
            request = urllib.request.Request(
                "http://localhost:8003/command",
                data=json.dumps(
                    {"kind": "move_joints", "positions": {"elbow_joint": 1.0}}
                ).encode(),
                headers={"content-type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, response.read()

        status, body = await asyncio.to_thread(_post)
        assert status == 202
        receipt = json.loads(body)
        assert receipt["topic"] == command_topic("ur5")

        message = await asyncio.wait_for(anext(subscriber.messages), timeout=5)
        assert isinstance(message.payload, bytes)
        command = JointCommand.model_validate_json(message.payload)
        assert command.kind is CommandKind.MOVE_JOINTS
        assert command.positions == {"elbow_joint": 1.0}


async def test_telemetry_becomes_derived_state() -> None:
    stamp = time.time_ns()
    async with aiomqtt.Client("localhost") as publisher:
        for joint in UR5_JOINT_NAMES:
            for field in JointField:
                await publisher.publish(
                    telemetry_topic("ur5", joint, field),
                    payload=JointTelemetry(value=0.0, stamp_ns=stamp).model_dump_json(),
                )
    await asyncio.sleep(0.5)  # one state-svc broadcast tick plus slack

    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = state_pb2_grpc.StateServiceStub(channel)
        state = await stub.GetState(state_pb2.GetStateRequest(asset="ur5"), timeout=5)

    assert state.stamp_ns >= stamp, "state does not include our telemetry yet"
    assert [j.name for j in state.joints] == list(UR5_JOINT_NAMES)
    # We set every position to zero, so FK must land on the closed-form zero pose.
    assert state.end_effector.position_m.x == pytest.approx(ZERO_POSE_X, abs=1e-6)
