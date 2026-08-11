"""The scoring path end to end against the running stack (`just up`).

Two seams:
- POST /score is the live skew tripwire: the number the service returns for
  the fixture window must equal the number the local `detector` library
  computes for it (Phase 4 DoD).
- the live loop: synthetic telemetry published to the broker must produce an
  anomaly_score row in InfluxDB (anomaly-svc scores, telemetry-svc persists).
"""

from __future__ import annotations

import asyncio
import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

import aiomqtt
import numpy as np
import pytest

from contracts import (
    UR5_JOINT_NAMES,
    JointField,
    JointTelemetry,
    telemetry_topic,
)
from detector import load_detector
from features import Window, compute_features

pytestmark = pytest.mark.slow

REPO = Path(__file__).parents[2]
FIXTURE = json.loads((REPO / "data" / "fixtures" / "window.json").read_text())
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
    if not (_up("http://localhost:8005/healthz/ready") and _up(f"{INFLUX['url']}/health")):
        pytest.skip("stack not running or anomaly-svc not ready — `just up` (+ real model) first")


def test_post_score_matches_the_library() -> None:
    request = urllib.request.Request(
        "http://localhost:8005/score",
        data=json.dumps(FIXTURE).encode(),
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        served = json.loads(response.read())

    detector, _manifest = load_detector("isoforest-v1", REPO / "models")
    n = len(next(iter(FIXTURE["joints"].values()))["positions"])
    values = np.zeros((n, len(UR5_JOINT_NAMES), 3), dtype=np.float64)
    for j, name in enumerate(UR5_JOINT_NAMES):
        channel = FIXTURE["joints"][name]
        values[:, j, 0] = channel["positions"]
        values[:, j, 1] = channel["velocities"]
        values[:, j, 2] = channel["efforts"]
    window = Window(0, n, np.arange(n, dtype=np.int64), values)
    expected = float(
        detector.score(compute_features(window, list(UR5_JOINT_NAMES)).reshape(1, -1))[0]
    )

    assert served["artefact"] == "isoforest-v1"
    assert served["score"] == pytest.approx(expected, abs=1e-9)
    assert served["verdict"] is True


def _flux(query: str) -> str:
    request = urllib.request.Request(
        f"{INFLUX['url']}/api/v2/query?org={INFLUX['org']}",
        data=json.dumps({"query": query, "type": "flux"}).encode(),
        headers={"Authorization": f"Token {INFLUX['token']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode()


async def test_live_scoring_reaches_influx() -> None:
    async with aiomqtt.Client("localhost") as client:
        t0 = time.monotonic()
        while time.monotonic() - t0 < 3.0:  # a few hops of telemetry
            stamp = time.time_ns()
            for j, joint in enumerate(UR5_JOINT_NAMES):
                phase = 0.5 * (time.monotonic() - t0) + j * 0.6
                for field, value in (
                    (JointField.POSITION, 0.5 * math.sin(phase)),
                    (JointField.VELOCITY, 0.25 * math.cos(phase)),
                    (JointField.EFFORT, 0.0),
                ):
                    await client.publish(
                        telemetry_topic("ur5", joint, field),
                        JointTelemetry(value=value, stamp_ns=stamp).model_dump_json(),
                    )
            await asyncio.sleep(0.02)

    query = (
        f'from(bucket: "{INFLUX["bucket"]}") |> range(start: -2m)'
        ' |> filter(fn: (r) => r._measurement == "anomaly_score" and r._field == "score")'
    )
    for _ in range(20):
        if "isoforest-v1" in _flux(query):
            break
        await asyncio.sleep(0.25)
    else:
        pytest.fail("no anomaly_score row appeared in InfluxDB")
