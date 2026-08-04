#!/usr/bin/env python3
"""Kill each service in turn; assert graceful degradation and recovery.

The success criterion (VISION.md): killing any single service leaves the
other three ALIVE and HONEST — reporting degraded readiness where a
dependency vanished is correct behaviour, crashing is not. Recovery must
need no manual step inside the service.

Note: `restart: unless-stopped` does NOT revive a CLI-killed container —
Docker treats `docker kill` as a manual stop — so this script owns the
restart, mirroring what an orchestrator would do.

Run with the stack up:  just up && just chaos
"""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request

SERVICES: dict[str, int] = {
    "telemetry-svc": 8001,
    "state-svc": 8002,
    "command-svc": 8003,
    "viz-svc": 8004,
}
# Killing a service may legitimately degrade the services that depend on it.
EXPECTED_CASCADE: dict[str, set[str]] = {
    "state-svc": {"viz-svc"},
}
TIMEOUT_S = 30.0
POLL_S = 0.5
HTTP_OK = 200


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], check=True, capture_output=True)


def probe(port: int, endpoint: str) -> int | None:
    """HTTP status of a health endpoint, or None if unreachable."""
    try:
        with urllib.request.urlopen(
            f"http://localhost:{port}/healthz/{endpoint}", timeout=2
        ) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return None


def wait_until(check: object, description: str) -> bool:
    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        if check():  # type: ignore[operator]
            return True
        time.sleep(POLL_S)
    print(f"  FAIL: timed out waiting for {description}")
    return False


def all_ready() -> bool:
    return all(probe(port, "ready") == HTTP_OK for port in SERVICES.values())


def run_cycle(victim: str) -> bool:
    port = SERVICES[victim]
    survivors = {name: p for name, p in SERVICES.items() if name != victim}
    print(f"\n=== chaos: kill {victim} ===")

    compose("kill", victim)
    if not wait_until(lambda: probe(port, "live") is None, f"{victim} to be gone"):
        return False

    # Survivors must stay alive; degraded readiness is allowed only where
    # a dependency on the victim makes it honest.
    ok = True
    for name, sport in survivors.items():
        alive = probe(sport, "live") == HTTP_OK
        ready = probe(sport, "ready") == HTTP_OK
        expected_degraded = name in EXPECTED_CASCADE.get(victim, set())
        if not alive:
            print(f"  FAIL: {name} died with {victim} (not graceful)")
            ok = False
        elif not ready and not expected_degraded:
            print(f"  FAIL: {name} degraded unexpectedly")
            ok = False
        else:
            state = "ready" if ready else "degraded (expected cascade)"
            print(f"  ok: {name} alive, {state}")
    if not ok:
        compose("start", victim)
        return False

    compose("start", victim)
    if not wait_until(all_ready, "all four services ready again"):
        return False
    print(f"  ok: {victim} recovered, all four ready")
    return True


def main() -> int:
    if not all_ready():
        print("stack not ready — run `just up` and wait for `just healthz` green")
        return 2
    failures = [victim for victim in SERVICES if not run_cycle(victim)]
    if failures:
        print(f"\nchaos: FAILED for {', '.join(failures)}")
        return 1
    print("\nchaos: all four kills degraded gracefully and recovered ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
