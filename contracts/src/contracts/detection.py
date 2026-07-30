"""Pydantic contracts for twin-anomaly's fault and scoring payloads.

The vendored ``models`` module stays byte-identical to twin-services; this
module adds what detection needs: the fault command/label pair (ground
truth by construction, ADR-0002) and the anomaly score. Same evolution
rules — additive changes only, ``schema_version`` with a default, extra
fields ignored (upstream ADR-0003).

``AnomalyScore`` is deliberately both the MQTT payload on
``twin/<asset>/anomaly/score`` and the ``POST /score`` response: one
scorer, one output shape, two transports.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from contracts.models import SCHEMA_VERSION

# ─── topics ──────────────────────────────────────────────────────────────────


def fault_cmd_topic(asset: str) -> str:
    """Topic the inject CLI publishes ``FaultCommand`` to (QoS 1)."""
    return f"twin/{asset}/fault/cmd"


def fault_state_topic(asset: str) -> str:
    """Topic the injector heartbeats ``FaultState`` labels on (QoS 1).

    Deliberately out-of-band from the telemetry the fault corrupts: a comms
    drop-out cuts ``twin/<asset>/joint/...``, never this.
    """
    return f"twin/{asset}/fault/state"


def anomaly_score_topic(asset: str) -> str:
    """Topic anomaly-svc publishes ``AnomalyScore`` to (QoS 0)."""
    return f"twin/{asset}/anomaly/score"


# ─── faults ──────────────────────────────────────────────────────────────────


class FaultKind(StrEnum):
    """The four injectable faults, plus NONE.

    NONE does double duty by design: in a ``FaultCommand`` it means "clear
    the active fault"; in a ``FaultState`` or a dataset label it means "no
    fault active". One vocabulary end to end, so a parquet label and a wire
    payload can never disagree about what normal is called.
    """

    NONE = "none"
    FRICTION = "friction"  # velocity lag approximating a friction spike
    ENCODER = "encoder"  # additive noise on position (seeded)
    STUCK = "stuck"  # joint value frozen at its last sample
    DROPOUT = "dropout"  # whole samples dropped; inherently all-joint


class FaultCommand(BaseModel):
    """One fault request: CLI body on ``twin/<asset>/fault/cmd``.

    ``severity`` is a unitless multiplier on each transform's base effect;
    the transforms document their interpretation (ADR-0002). ``seed`` makes
    stochastic faults (encoder noise) reproducible — the corpus is an
    experiment, not weather.
    """

    schema_version: int = Field(default=SCHEMA_VERSION, ge=1)
    kind: FaultKind
    joint: str | None = Field(
        default=None, description="Target joint name; None applies to every joint."
    )
    severity: float = Field(default=1.0, gt=0, le=10)
    duration_s: float = Field(default=10.0, gt=0, le=300)
    seed: int = Field(default=0, ge=0)
    command_id: str = Field(default_factory=lambda: uuid4().hex)

    @model_validator(mode="after")
    def _joint_matches_kind(self) -> FaultCommand:
        if self.kind is FaultKind.NONE and self.joint is not None:
            raise ValueError("clear takes no joint")
        if self.kind is FaultKind.DROPOUT and self.joint is not None:
            raise ValueError("dropout drops whole samples; it cannot target a joint")
        return self


class FaultState(BaseModel):
    """The ground-truth label: heartbeated at 1 Hz while a fault is active,
    published once with ``active=False`` when it ends (by duration or clear).

    ``command_id`` ties every label back to the command that caused it, so
    a dataset window can always be traced to its experiment.
    """

    schema_version: int = Field(default=SCHEMA_VERSION, ge=1)
    active: bool
    kind: FaultKind
    joint: str | None = None
    severity: float = Field(default=0.0, ge=0)
    command_id: str
    started_ns: int = Field(..., ge=0)
    stamp_ns: int = Field(..., ge=0)

    @model_validator(mode="after")
    def _kind_matches_active(self) -> FaultState:
        if self.active and self.kind is FaultKind.NONE:
            raise ValueError("active fault cannot have kind none")
        if not self.active and self.kind is not FaultKind.NONE:
            raise ValueError("inactive state must have kind none")
        return self


# ─── scoring ─────────────────────────────────────────────────────────────────


class JointWindow(BaseModel):
    """One joint's samples across a window; the three channels stay aligned."""

    positions: list[float]
    velocities: list[float]
    efforts: list[float]

    @model_validator(mode="after")
    def _channels_align(self) -> JointWindow:
        n = len(self.positions)
        if n == 0:
            raise ValueError("empty window")
        if len(self.velocities) != n or len(self.efforts) != n:
            raise ValueError("position/velocity/effort lengths differ")
        return self


class WindowScoreRequest(BaseModel):
    """``POST /score`` body: one explicit, rectangular window of telemetry.

    Window length and hop are the ``features`` package's business; this
    payload just carries aligned samples. The service rejects windows whose
    sample count doesn't match the loaded model's expectation.
    """

    schema_version: int = Field(default=SCHEMA_VERSION, ge=1)
    window_start_ns: int = Field(..., ge=0)
    sample_period_ns: int = Field(..., gt=0)
    joints: dict[str, JointWindow]

    @model_validator(mode="after")
    def _rectangular(self) -> WindowScoreRequest:
        if not self.joints:
            raise ValueError("no joints in window")
        lengths = {len(w.positions) for w in self.joints.values()}
        if len(lengths) != 1:
            raise ValueError(f"joints disagree on window length: {sorted(lengths)}")
        return self


class AnomalyScore(BaseModel):
    """One scored window: MQTT payload and ``POST /score`` response alike.

    ``verdict`` is precomputed as score-versus-threshold so no consumer
    ever re-derives it differently; the threshold itself travels from the
    artefact's manifest (ADR-0004), never from service config. ``artefact``
    and ``features_version`` make every score traceable to exactly one
    model file and one feature implementation.
    """

    schema_version: int = Field(default=SCHEMA_VERSION, ge=1)
    score: float
    threshold: float
    verdict: bool = Field(..., description="True when the window is judged anomalous.")
    artefact: str = Field(..., description='Model artefact stem, e.g. "isoforest-v1".')
    features_version: str
    window_start_ns: int = Field(..., ge=0)
    window_end_ns: int = Field(..., ge=0)

    @model_validator(mode="after")
    def _window_ordered(self) -> AnomalyScore:
        if self.window_end_ns <= self.window_start_ns:
            raise ValueError("window_end_ns must be after window_start_ns")
        return self
