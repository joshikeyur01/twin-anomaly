# 2. Faults are injected in the signal path, not the physics

Date: 2026-07-18
Status: Accepted

## Context

The detector needs labelled fault data, and labels are only trustworthy if
they are created with the fault rather than reconstructed afterwards. Two
places to break the arm:

1. **The physics.** Reach into Gazebo — a joint-friction plugin, modified
   dynamics parameters, forced joint efforts. Maximum realism for the
   mechanical faults.
2. **The signal path.** A passthrough ROS 2 node between Gazebo's
   `/joint_states` output (remapped to `/joint_states_raw`) and the
   unchanged twin-services bridge, perturbing the stream in flight.

Two observations pushed the decision. First, half of the fault catalogue —
encoder noise, comms drop-out — *is* a signal fault; physics injection
would still need a signal path for those, so option 1 means building both.
Second, a physics fault is hard to bound: a Gazebo plugin parameter change
takes effect on the solver's schedule, mid-run reversal is unreliable
without respawning the model, and "when exactly did the fault start" —
the thing the label must state — becomes an estimate instead of a fact.

## Decision

All four faults are stream transformations in one passthrough node
(`fault-injector/`), pure functions `JointSnapshot → JointSnapshot | None`:

- **encoder** — seeded gaussian noise on reported positions
  (σ = 0.02 rad × severity). This is what a failing encoder does.
- **stuck** — position frozen at its last sample, velocity zero. This is
  what a dead encoder does.
- **dropout** — samples return `None` and are never republished. This is
  what a broken link does.
- **friction** — position low-pass plus velocity attenuation with
  `lag = severity/(severity+1)`. This is an **approximation**: the
  kinematic *symptom* of a friction spike, not its physics.

Labels are emitted by the same node, on a separate MQTT topic
(`twin/<asset>/fault/state`, QoS 1, 1 Hz heartbeat, no retained
messages), at activation time — ground truth by construction. The
drop-out transform silences the sensor path and never the label path:
you cannot label an outage with the channel you just cut. Replacement
and clear close the running labelled interval before opening another;
no interval is ever left open.

## Consequences

**What we gain.** Faults are parameterised, seeded, instantly reversible,
and start on a timestamp the label states as fact. One node covers all
four; the vendored bridge stays untouched; every transform is unit-tested
without ROS, deterministically.

**What the friction approximation cannot show — do not claim it.** A real
friction spike raises motor effort/current at reduced velocity, couples
into neighbouring joints through the controller, and drifts with
temperature. Our transform touches position and velocity only; effort
passes through unchanged. Consequences downstream:

- A detector trained here learns the *kinematic* signature (velocity RMS
  down, tracking error up). No claim may be made about detecting friction
  from effort/current signatures — the dataset cannot contain them.
- If the evaluation table (ADR-0004) shows friction as the easiest fault,
  suspect the approximation before crediting the model: a first-order lag
  may be more detectable than real tribology.

**Expected signatures** (falsifiable — Phase 2's exploration notebook
must confirm or this ADR gets a correction):

| Fault    | Position          | Velocity              | Sample stream |
| -------- | ----------------- | --------------------- | ------------- |
| encoder  | variance up       | unchanged             | intact        |
| stuck    | frozen vs command | zero on target joint  | intact        |
| friction | lags command      | RMS attenuated        | intact        |
| dropout  | —                 | —                     | gaps          |

**Revisit when:** a thesis claim needs effort-signature realism, or
`twin-fleet` wants fault campaigns across N robots. The upgrade path is a
Gazebo friction plugin *behind the same FaultCommand contract* — the
labels, topics, and dataset schema all survive that swap; only the
transform moves.
