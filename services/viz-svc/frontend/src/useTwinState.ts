// The WebSocket half of the viewer. Frame shape mirrors viz_svc/stream.py
// to_frame() — that Python function is the source of truth.

import { useEffect, useRef, useState } from "react";

export interface JointFrame {
  name: string;
  position_rad: number;
  velocity_rms: number;
}

export interface TwinFrame {
  stamp_ms: number;
  ee: { pos: [number, number, number]; quat: [number, number, number, number] };
  joints: JointFrame[];
}

export type ConnectionStatus = "connecting" | "live" | "reconnecting";

const RECONNECT_DELAY_MS = 1500;

function wsUrl(): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/ws/state`;
}

// Auto-reconnects forever: viz-svc closing the socket (state-svc outage,
// code 1011) and viz-svc itself dying both land in onclose, so one retry
// timer covers every failure mode. The UI shows `status` instead of a
// silently frozen arm.
export function useTwinState(): { frame: TwinFrame | null; status: ConnectionStatus } {
  const [frame, setFrame] = useState<TwinFrame | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const latest = useRef<TwinFrame | null>(null);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: number | undefined;
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      socket = new WebSocket(wsUrl());
      socket.onopen = () => setStatus("live");
      socket.onmessage = (event) => {
        latest.current = JSON.parse(event.data as string) as TwinFrame;
        setFrame(latest.current);
      };
      socket.onclose = () => {
        if (disposed) return;
        setStatus("reconnecting");
        timer = window.setTimeout(connect, RECONNECT_DELAY_MS);
      };
    };

    connect();
    return () => {
      disposed = true;
      window.clearTimeout(timer);
      socket?.close();
    };
  }, []);

  return { frame, status };
}
