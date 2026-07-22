"""telemetry-svc: ingests MQTT telemetry, validates against contracts,
writes to InfluxDB. Replaces twin-hello's Telegraf: L4 needs one place that
enforces contracts rather than merely parsing."""
