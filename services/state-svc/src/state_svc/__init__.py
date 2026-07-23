"""state-svc: computes derived state (end-effector pose via UR5 forward
kinematics, per-joint velocity RMS) from MQTT telemetry and serves it over
gRPC. The first real L4 inhabitant: values in, meaning-free derived values
out — semantics stay in twin-aas."""
