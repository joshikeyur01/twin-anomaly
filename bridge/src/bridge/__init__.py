"""DDS<->MQTT bridge, vendored from twin-hello and extended.

Telemetry out: mirrors ROS 2 /joint_states into MQTT so non-ROS consumers
never touch DDS. Commands in: forwards twin/<asset>/cmd/joints setpoints to
the ROS 2 trajectory controller — the path twin-hello deliberately left open.

Dumb L2 plumbing by decree (AGENTS.md): validation and republishing only,
no business rules, no derived state."""
