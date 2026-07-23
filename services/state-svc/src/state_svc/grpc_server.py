"""The gRPC face of state-svc: TwinState assembly, fan-out, and the servicer.

Stream semantics promised by state.proto: every subscriber holds a
latest-wins mailbox of size one — a lagging client silently loses
intermediate states instead of growing a queue (drop, don't buffer).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any

import grpc

from contracts import SCHEMA_VERSION
from contracts.gen import state_pb2, state_pb2_grpc
from state_svc.kinematics import forward
from state_svc.window import RollingWindow


class StateHub:
    """Latest-wins fan-out of TwinState to any number of stream subscribers."""

    def __init__(self, asset: str) -> None:
        self.asset = asset
        self._latest: state_pb2.TwinState | None = None
        self._subscribers: set[asyncio.Queue[state_pb2.TwinState]] = set()

    @property
    def latest(self) -> state_pb2.TwinState | None:
        return self._latest

    def publish(self, state: state_pb2.TwinState) -> None:
        self._latest = state
        for queue in self._subscribers:
            if queue.full():
                queue.get_nowait()  # evict the stale state; latest wins
            queue.put_nowait(state)

    @contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue[state_pb2.TwinState]]:
        queue: asyncio.Queue[state_pb2.TwinState] = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)


def build_state(
    asset: str, window: RollingWindow, rms_window_s: float
) -> state_pb2.TwinState | None:
    """Window snapshot + forward kinematics → one TwinState, or None if the
    window is not yet complete."""
    snapshots = window.snapshot()
    if snapshots is None:
        return None
    pose = forward([snap.position_rad for snap in snapshots])
    state = state_pb2.TwinState(
        schema_version=SCHEMA_VERSION,
        asset=asset,
        stamp_ns=window.stamp_ns,
        rms_window_s=rms_window_s,
    )
    state.end_effector.position_m.x = pose.x
    state.end_effector.position_m.y = pose.y
    state.end_effector.position_m.z = pose.z
    state.end_effector.orientation.x = pose.qx
    state.end_effector.orientation.y = pose.qy
    state.end_effector.orientation.z = pose.qz
    state.end_effector.orientation.w = pose.qw
    for snap in snapshots:
        state.joints.add(
            name=snap.name,
            position_rad=snap.position_rad,
            velocity_rad_s=snap.velocity_rad_s,
            effort_nm=snap.effort_nm,
            velocity_rms=snap.velocity_rms,
        )
    return state


class StateServicer(state_pb2_grpc.StateServiceServicer):
    def __init__(self, hub: StateHub) -> None:
        self._hub = hub

    async def GetState(  # noqa: N802  # gRPC method names come from the proto
        self,
        request: state_pb2.GetStateRequest,
        context: grpc.aio.ServicerContext[state_pb2.GetStateRequest, state_pb2.TwinState],
    ) -> state_pb2.TwinState:
        await self._check_asset(request.asset, context)
        state = self._hub.latest
        if state is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "no telemetry received yet")
        assert state is not None  # abort() raises; mypy can't see that
        return state

    async def StreamState(  # noqa: N802  # gRPC method names come from the proto
        self,
        request: state_pb2.StreamStateRequest,
        context: grpc.aio.ServicerContext[state_pb2.StreamStateRequest, state_pb2.TwinState],
    ) -> AsyncIterator[state_pb2.TwinState]:
        await self._check_asset(request.asset, context)
        # Decimation is skip-based: with a continuous ~50 Hz feed, the next
        # state is never more than one telemetry period away.
        min_interval = 1.0 / request.max_rate_hz if request.max_rate_hz > 0 else 0.0
        last_sent = float("-inf")
        with self._hub.subscribe() as queue:
            while True:
                state = await queue.get()
                now = time.monotonic()
                if now - last_sent < min_interval:
                    continue
                last_sent = now
                yield state

    async def _check_asset(
        self, requested: str, context: grpc.aio.ServicerContext[Any, Any]
    ) -> None:
        if requested and requested != self._hub.asset:
            await context.abort(
                grpc.StatusCode.NOT_FOUND,
                f"unknown asset {requested!r}; this twin is {self._hub.asset!r}",
            )


def build_server(hub: StateHub, port: int) -> grpc.aio.Server:
    server = grpc.aio.server()
    state_pb2_grpc.add_StateServiceServicer_to_server(StateServicer(hub), server)
    server.add_insecure_port(f"0.0.0.0:{port}")
    return server
