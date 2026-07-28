"""Fault transforms: pure functions on joint snapshots, testable without ROS.

The node converts each incoming ROS message to a ``JointSnapshot``, applies
the active transform, and republishes the result — or drops the sample when
the transform returns ``None`` (that is the comms drop-out). Every fault in
this repo is one such function; anything a transform can't express doesn't
belong in the injector (ADR-0002).

Faults are built by factories from a validated ``FaultCommand``. Some carry
internal state (friction's smoothed positions, stuck's frozen values) — but
they stay pure in the sense that matters: no I/O, and deterministic for a
given command and input sequence. Encoder noise uses ``random.Random(seed)``
so the corpus is an experiment, not weather.

Severity interpretations (the unitless multiplier from the contract):
- friction: lag factor ``severity / (severity + 1)`` — 1.0 halves velocity
  and smooths position; 10 nearly freezes motion. Approximates a friction
  spike as its symptom, not its physics — ADR-0002 owns this.
- encoder: gaussian position noise, sigma = 0.02 rad x severity.
- stuck / dropout: severity is ignored; the faults are binary.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import assert_never

from contracts import FaultCommand, FaultKind

BASE_ENCODER_STD_RAD = 0.02


@dataclass(frozen=True, slots=True)
class JointSnapshot:
    """One /joint_states sample, decoupled from the ROS message type."""

    stamp_ns: int
    names: tuple[str, ...]
    positions: tuple[float, ...]
    velocities: tuple[float, ...]
    efforts: tuple[float, ...]


# None means "drop this sample" — the comms drop-out in one return value.
Transform = Callable[[JointSnapshot], JointSnapshot | None]


def passthrough(snapshot: JointSnapshot) -> JointSnapshot:
    """The idle transform: forward untouched. Also the no-fault baseline."""
    return snapshot


def make_friction(severity: float, joint: str | None) -> Transform:
    """Velocity lag: positions low-pass filtered, velocities attenuated."""
    lag = severity / (severity + 1.0)
    smoothed: dict[str, float] = {}

    def transform(snapshot: JointSnapshot) -> JointSnapshot:
        positions = list(snapshot.positions)
        velocities = list(snapshot.velocities)
        for i, name in enumerate(snapshot.names):
            if joint is not None and name != joint:
                continue
            previous = smoothed.get(name, positions[i])
            positions[i] = lag * previous + (1.0 - lag) * positions[i]
            smoothed[name] = positions[i]
            velocities[i] = velocities[i] * (1.0 - lag)
        return replace(snapshot, positions=tuple(positions), velocities=tuple(velocities))

    return transform


def make_encoder(severity: float, seed: int, joint: str | None) -> Transform:
    """Additive gaussian noise on reported positions, seeded and replayable."""
    rng = random.Random(seed)
    sigma = BASE_ENCODER_STD_RAD * severity

    def transform(snapshot: JointSnapshot) -> JointSnapshot:
        positions = tuple(
            p + rng.gauss(0.0, sigma) if joint is None or name == joint else p
            for name, p in zip(snapshot.names, snapshot.positions, strict=True)
        )
        return replace(snapshot, positions=positions)

    return transform


def make_stuck(joint: str | None) -> Transform:
    """Encoder freeze: position pinned at the first value seen, velocity zero."""
    frozen: dict[str, float] = {}

    def transform(snapshot: JointSnapshot) -> JointSnapshot:
        positions = list(snapshot.positions)
        velocities = list(snapshot.velocities)
        for i, name in enumerate(snapshot.names):
            if joint is not None and name != joint:
                continue
            positions[i] = frozen.setdefault(name, positions[i])
            velocities[i] = 0.0
        return replace(snapshot, positions=tuple(positions), velocities=tuple(velocities))

    return transform


def make_dropout() -> Transform:
    """Comms drop-out: every sample vanishes for the fault's duration."""

    def transform(snapshot: JointSnapshot) -> None:
        return None

    return transform


def from_command(cmd: FaultCommand) -> Transform:
    """Build the active transform for a validated command. NONE clears."""
    match cmd.kind:
        case FaultKind.NONE:
            return passthrough
        case FaultKind.FRICTION:
            return make_friction(cmd.severity, cmd.joint)
        case FaultKind.ENCODER:
            return make_encoder(cmd.severity, cmd.seed, cmd.joint)
        case FaultKind.STUCK:
            return make_stuck(cmd.joint)
        case FaultKind.DROPOUT:
            return make_dropout()
        case _:
            assert_never(cmd.kind)
