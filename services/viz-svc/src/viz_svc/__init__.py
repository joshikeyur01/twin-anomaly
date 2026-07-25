"""viz-svc: serves the React + react-three-fiber viewer and proxies
state-svc's StreamState gRPC stream into a WebSocket. The browser consumes
the same contract as any other client — no private side channel, no MQTT,
no InfluxDB."""
