"""The injector's single mutable cell: which fault is active right now.

The ROS callback thread reads (``apply``); the asyncio side swaps
(``activate`` / ``clear`` / ``expire_if_due``). Each mutation is one
reference assignment, atomic under the GIL — no lock, on purpose.

Label semantics (ADR-0002): ``activate`` returns the first ``FaultState``
so the caller can publish it at injection time, not at the next heartbeat
tick. Ending a fault — by duration, by clear, or by replacement — yields
exactly one ``active=False`` label carrying the ended command's id, so
every labelled interval in the dataset is closed and traceable.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from contracts import FaultCommand, FaultKind, FaultState
from fault_injector.transforms import JointSnapshot, Transform, from_command, passthrough


class FaultSession:
    def __init__(self, clock: Callable[[], int] = time.time_ns) -> None:
        self._clock = clock
        self._transform: Transform = passthrough
        self._command: FaultCommand | None = None
        self._started_ns = 0
        self._deadline_ns = 0

    @property
    def active(self) -> bool:
        return self._command is not None

    def apply(self, snapshot: JointSnapshot) -> JointSnapshot | None:
        """Called from the ROS thread for every sample."""
        return self._transform(snapshot)

    def activate(self, cmd: FaultCommand) -> FaultState:
        """Swap in a fault (kind != NONE) and return its injection-time label."""
        if cmd.kind is FaultKind.NONE:
            raise ValueError("activate needs a fault; use clear() for NONE")
        now = self._clock()
        self._transform = from_command(cmd)
        self._command = cmd
        self._started_ns = now
        self._deadline_ns = now + int(cmd.duration_s * 1_000_000_000)
        return FaultState(
            active=True,
            kind=cmd.kind,
            joint=cmd.joint,
            severity=cmd.severity,
            command_id=cmd.command_id,
            started_ns=now,
            stamp_ns=now,
        )

    def heartbeat(self) -> FaultState | None:
        """The 1 Hz label while a fault is active; None when idle."""
        if self._command is None:
            return None
        return FaultState(
            active=True,
            kind=self._command.kind,
            joint=self._command.joint,
            severity=self._command.severity,
            command_id=self._command.command_id,
            started_ns=self._started_ns,
            stamp_ns=self._clock(),
        )

    def clear(self) -> FaultState | None:
        """End the active fault; return its closing label, or None if idle."""
        if self._command is None:
            return None
        ended = self._command
        started = self._started_ns
        self._transform = passthrough
        self._command = None
        return FaultState(
            active=False,
            kind=FaultKind.NONE,
            command_id=ended.command_id,
            started_ns=started,
            stamp_ns=self._clock(),
        )

    def expire_if_due(self) -> FaultState | None:
        """Clear on deadline; the closing label, or None if idle/still running."""
        if self._command is None or self._clock() < self._deadline_ns:
            return None
        return self.clear()
