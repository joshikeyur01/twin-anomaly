"""Fault injector for twin-anomaly.

A passthrough ROS 2 node in the sensor path: Gazebo's joint states arrive
remapped as ``/joint_states_raw`` and leave as ``/joint_states`` for the
unchanged twin-services bridge. Idle, it forwards untouched; under a fault
(commanded via ``twin/<asset>/fault/cmd``) it perturbs the stream — velocity
lag, additive noise, frozen joint, or paused forwarding — and heartbeats
``FaultState`` labels on ``twin/<asset>/fault/state``, a channel the comms
drop-out fault never cuts.

Phase 0: passthrough and the transform seam only. The four faults, the MQTT
command loop, and the label heartbeat land in Phase 1 (see ROADMAP).
"""
