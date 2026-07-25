// One scene, one robot, camera orbit (AGENTS.md). The arm is a stylized
// primitive chain, not a mesh model: each nesting level applies one DH row
// (Rot_z(θ) · Trans_z(d) · Trans_x(a) · Rot_x(α)), driven by streamed joint
// angles.
//
// The orange marker is NOT attached to the arm: it renders the end-effector
// pose streamed from state-svc's forward kinematics. If the marker ever
// detaches from the arm tip, the client chain and the server FK disagree —
// the display audits itself.

import { OrbitControls } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";
import type { TwinFrame } from "./useTwinState";

// Mirrors state_svc/kinematics.py — the published UR5 DH parameters.
const DH = [
  { a: 0, d: 0.089159, alpha: Math.PI / 2 },
  { a: -0.425, d: 0, alpha: 0 },
  { a: -0.39225, d: 0, alpha: 0 },
  { a: 0, d: 0.10915, alpha: Math.PI / 2 },
  { a: 0, d: 0.09465, alpha: -Math.PI / 2 },
  { a: 0, d: 0.0823, alpha: 0 },
] as const;

const HOME_ANGLES = [0, 0, 0, 0, 0, 0];

const UP = new THREE.Vector3(0, 1, 0);

function Limb({ to }: { to: readonly [number, number, number] }) {
  const { quat, length, mid } = useMemo(() => {
    const v = new THREE.Vector3(to[0], to[1], to[2]);
    const length = v.length();
    const quat =
      length > 1e-6
        ? new THREE.Quaternion().setFromUnitVectors(UP, v.clone().normalize())
        : new THREE.Quaternion();
    return { quat, length, mid: v.multiplyScalar(0.5) };
  }, [to]);
  if (length < 1e-6) return null;
  return (
    <mesh position={mid} quaternion={quat}>
      <cylinderGeometry args={[0.028, 0.028, length, 16]} />
      <meshStandardMaterial color="#8fa3bf" />
    </mesh>
  );
}

function JointBall() {
  return (
    <mesh>
      <sphereGeometry args={[0.045, 24, 24]} />
      <meshStandardMaterial color="#4a6fa5" />
    </mesh>
  );
}

function ArmChain({ angles, index = 0 }: { angles: number[]; index?: number }) {
  if (index === DH.length) {
    return (
      <mesh>
        <boxGeometry args={[0.05, 0.05, 0.05]} />
        <meshStandardMaterial color="#d8dee9" />
      </mesh>
    );
  }
  const row = DH[index];
  const link = [row.a, 0, row.d] as const;
  return (
    <group rotation={[0, 0, angles[index] ?? 0]}>
      <JointBall />
      <Limb to={link} />
      <group position={[row.a, 0, row.d]} rotation={[row.alpha, 0, 0]}>
        <ArmChain angles={angles} index={index + 1} />
      </group>
    </group>
  );
}

function EEMarker({ pos }: { pos: [number, number, number] }) {
  return (
    <mesh position={pos}>
      <sphereGeometry args={[0.022, 24, 24]} />
      <meshStandardMaterial color="#ff6b35" emissive="#ff6b35" emissiveIntensity={0.6} />
    </mesh>
  );
}

export function Scene({ frame }: { frame: TwinFrame | null }) {
  const angles = frame ? frame.joints.map((j) => j.position_rad) : HOME_ANGLES;
  return (
    <>
      <ambientLight intensity={0.5} />
      <directionalLight position={[3, 5, 2]} intensity={1.2} />
      <gridHelper args={[2, 20, "#2c3242", "#1a1f2b"]} />
      {/* Robot frames are Z-up; the display is Y-up. One rotation fixes all. */}
      <group rotation={[-Math.PI / 2, 0, 0]}>
        <ArmChain angles={angles} />
        {frame && <EEMarker pos={frame.ee.pos} />}
      </group>
      <OrbitControls makeDefault target={[0, 0.3, 0]} />
    </>
  );
}
