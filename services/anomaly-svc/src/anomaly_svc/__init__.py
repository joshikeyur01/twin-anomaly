"""anomaly-svc: scores live telemetry against a pinned model artefact.

Rolling window over the same MQTT telemetry state-svc consumes, features
computed by the shared ``features`` package (the serving half of the skew
tripwire), scores published as ``AnomalyScore`` on
``twin/<asset>/anomaly/score`` for telemetry-svc to persist. ``POST /score``
runs the identical scorer on an explicit window so notebooks and CI can
exercise serving without a broker.

Phase 0: health/metrics stub only. The scorer, the model loader, and real
readiness (broker + artefact + features-version match) land in Phase 4.
"""
