"""Publish a sine-shaped position command for each UR5 joint.

Standalone rclpy publisher — run alongside Gazebo to make the arm move for
the demo GIF. Requires ROS 2 Jazzy sourced.
"""

from __future__ import annotations

import math
import time

# Imports are inside main() so `ruff check` and `pytest` do not require a
# ROS 2 environment to succeed.


def main() -> None:
    import rclpy
    from rclpy.node import Node
    from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

    JOINT_NAMES = [
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint",
    ]

    rclpy.init()
    node: Node = rclpy.create_node("sine_trajectory")
    pub = node.create_publisher(
        JointTrajectory,
        "/joint_trajectory_controller/joint_trajectory",
        10,
    )

    t0 = time.monotonic()
    try:
        while rclpy.ok():
            t = time.monotonic() - t0
            positions = [0.5 * math.sin(0.5 * t + i * 0.6) for i, _ in enumerate(JOINT_NAMES)]

            msg = JointTrajectory()
            msg.joint_names = JOINT_NAMES
            point = JointTrajectoryPoint()
            point.positions = positions
            point.time_from_start.sec = 0
            point.time_from_start.nanosec = 100_000_000
            msg.points = [point]

            pub.publish(msg)
            time.sleep(0.02)  # 50 Hz
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
