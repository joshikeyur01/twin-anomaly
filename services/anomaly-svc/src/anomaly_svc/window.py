"""Rolling telemetry window: MQTT message stream back into a sample matrix.

The bridge publishes one message per joint per field; this reassembles them
by ``stamp_ns`` into complete samples and hands out a ``features.Window``
identical in shape to what ``data-pipeline`` built from InfluxDB — so the
same ``features`` code produces the same vector at serving time as at
training time.

Pruning is by **wall-clock arrival**, not telemetry time — deliberately
unlike state-svc, which uses telemetry time so a paused sim doesn't decay
its RMS. Here the opposite is what we want: a comms drop-out *stops*
telemetry, and detecting that the stream went silent is a wall-clock event.
Telemetry-time pruning would freeze the window on the last pre-drop-out
second and score it forever as normal — the drop-out would be invisible.

Single-task use only: the consumer owns it. No locking by design.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

import numpy as np

from contracts import UR5_JOINT_NAMES, JointField, JointTelemetry
from features import Window

_FIELDS = (JointField.POSITION, JointField.VELOCITY, JointField.EFFORT)

# Score a window as long as it holds at least this many complete samples. Kept
# low on purpose: a comms drop-out starves the window as samples age out, and
# those last sparse windows are exactly what should score anomalous.
MIN_COMPLETE = 1


class AnomalyWindow:
    def __init__(
        self,
        length_ns: int,
        joints: Sequence[str] = UR5_JOINT_NAMES,
        clock: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._length_ns = length_ns
        self._joints = tuple(joints)
        self._clock = clock
        self._samples: dict[int, dict[tuple[str, JointField], float]] = {}
        self._recv_ns: dict[int, int] = {}  # stamp_ns -> wall-clock arrival
        self._last_stamp = 0

    def observe(self, joint: str, field: JointField, sample: JointTelemetry) -> None:
        if joint not in self._joints:
            return
        self._samples.setdefault(sample.stamp_ns, {})[(joint, field)] = sample.value
        self._recv_ns.setdefault(sample.stamp_ns, self._clock())
        self._last_stamp = max(self._last_stamp, sample.stamp_ns)
        self._prune()

    def _prune(self) -> None:
        cutoff = self._clock() - self._length_ns
        stale = [stamp for stamp, recv in self._recv_ns.items() if recv < cutoff]
        for stamp in stale:
            del self._samples[stamp]
            del self._recv_ns[stamp]

    def to_window(self) -> Window | None:
        """The current window as a features.Window, or None if too sparse.

        Prunes on read, so a silent stream ages the window toward empty even
        with no new messages — that is how a total drop-out surfaces.
        """
        self._prune()
        complete = [stamp for stamp in sorted(self._samples) if self._is_complete(stamp)]
        if len(complete) < MIN_COMPLETE:
            return None
        values = np.array(
            [[[self._samples[s][(j, f)] for f in _FIELDS] for j in self._joints] for s in complete],
            dtype=np.float64,
        )
        stamps = np.asarray(complete, dtype=np.int64)
        return Window(complete[0], self._last_stamp + 1, stamps, values)

    def _is_complete(self, stamp: int) -> bool:
        row = self._samples[stamp]
        return all((joint, field) in row for joint in self._joints for field in _FIELDS)
