# sim

Gazebo Harmonic assets for `twin-services`. Vendored from `twin-hello` —
the two repos simulate the same UR5, and the sim is intentionally shared
work, not duplicated work.

## Contents

- `scripts/sine_trajectory.py` — drives the arm through a sine trajectory
  for the demo GIF (vendored verbatim).
- `urdf/`, `worlds/`, `launch/` — **not committed yet.** These are
  `twin-hello` Phase 1 deliverables (see its roadmap); once written there,
  copy them here. The launch file must also spawn a
  `joint_trajectory_controller`, because this repo's command path publishes
  to `/joint_trajectory_controller/joint_trajectory` (see `bridge/`).

## First-time setup

```bash
# UR5 description
git clone --depth 1 https://github.com/UniversalRobots/Universal_Robots_ROS2_Description urdf/tmp
cp -r urdf/tmp/{meshes,urdf} urdf/
rm -rf urdf/tmp
```

## Until the sim exists

The full stack is testable without Gazebo: publish synthetic telemetry
straight to MQTT (any `mosquitto_pub` loop producing the contracts wire
format) and watch it flow through telemetry-svc, state-svc, Grafana, and the
viz. The integration tests do exactly this.
