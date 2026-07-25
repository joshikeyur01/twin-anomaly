import { Canvas } from "@react-three/fiber";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Scene } from "./Scene";
import { useTwinState, type ConnectionStatus } from "./useTwinState";

const STATUS_COLORS: Record<ConnectionStatus, string> = {
  connecting: "#e5c07b",
  live: "#98c379",
  reconnecting: "#e06c75",
};

// Degradation must be visible: the pill is the frontend's /healthz.
function StatusPill({ status }: { status: ConnectionStatus }) {
  return (
    <div
      style={{
        position: "fixed",
        top: 12,
        left: 12,
        padding: "4px 10px",
        borderRadius: 999,
        fontFamily: "ui-monospace, monospace",
        fontSize: 12,
        color: "#0b0e14",
        background: STATUS_COLORS[status],
        userSelect: "none",
      }}
    >
      {status}
    </div>
  );
}

function App() {
  const { frame, status } = useTwinState();
  return (
    <>
      <Canvas camera={{ position: [1.2, 0.9, 1.2], fov: 45 }}>
        <color attach="background" args={["#0b0e14"]} />
        <Scene frame={frame} />
      </Canvas>
      <StatusPill status={status} />
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
