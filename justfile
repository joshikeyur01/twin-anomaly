# twin-anomaly task runner. `just` for a listing.

set shell := ["bash", "-euo", "pipefail", "-c"]

# ─── setup ─────────────────────────────────────────────────────────────────

# Install dev dependencies for the whole workspace with uv.
install:
    uv sync --all-groups --all-packages
    # iCloud's fileproviderd asynchronously sets the macOS hidden flag on
    # dot-dirs; Python >= 3.12 skips hidden .pth files, silently breaking
    # editable installs (setuptools#4595). Clearing is idempotent.
    chflags -R nohidden .venv 2>/dev/null || true

# Fetch model artefacts (models/ is git-lfs; a fresh clone has pointers only).
lfs:
    git lfs install --local
    git lfs pull

# Regenerate protobuf stubs into contracts.gen (checked in — commit the diff).
gen:
    uv run python -m grpc_tools.protoc \
        --proto_path=contracts/proto \
        --python_out=contracts/src/contracts/gen \
        --grpc_python_out=contracts/src/contracts/gen \
        --mypy_out=contracts/src/contracts/gen \
        --mypy_grpc_out=contracts/src/contracts/gen \
        contracts/proto/state.proto
    # grpc_tools emits top-level imports; rewrite to package-relative so
    # the stubs work as contracts.gen.* (long-standing protoc quirk).
    uv run python -c "import pathlib; p = pathlib.Path('contracts/src/contracts/gen/state_pb2_grpc.py'); p.write_text(p.read_text().replace('import state_pb2 as', 'from . import state_pb2 as'))"

# ─── quality gates ─────────────────────────────────────────────────────────

# iCloud re-hides .pth files after every sync (see install); run before any
# uv-run recipe so editable imports never silently vanish.
_unhide:
    @chflags -R nohidden .venv 2>/dev/null || true

lint: _unhide
    uv run ruff check .
    uv run ruff format --check .

format: _unhide
    uv run ruff format .
    uv run ruff check --fix .

typecheck: _unhide
    uv run mypy contracts features detector fault-injector data-pipeline services bridge

test: _unhide
    uv run pytest

check: lint typecheck test

# ─── stack ─────────────────────────────────────────────────────────────────

# Build all service images.
build:
    docker compose build

# Start infra + inherited services + anomaly-svc.
up:
    docker compose up -d --build
    @echo "Grafana:    http://localhost:3000 (admin/admin)"
    @echo "Prometheus: http://localhost:9090"
    @echo "Viz:        http://localhost:8004"
    @echo "Score API:  http://localhost:8005"

down:
    docker compose down

logs svc="":
    docker compose logs -f {{svc}}

# ─── health ────────────────────────────────────────────────────────────────

_check name url:
    @curl -sf {{url}} >/dev/null && echo "{{name}} ✓" || echo "{{name}} ✗"

# Smoke check: infra, inherited services, and anomaly-svc answer.
healthz:
    @just _check grafana    http://localhost:3000/api/health
    @just _check influx     http://localhost:8086/health
    @just _check prometheus http://localhost:9090/-/healthy
    @just _check telemetry  http://localhost:8001/healthz/ready
    @just _check state      http://localhost:8002/healthz/ready
    @just _check command    http://localhost:8003/healthz/ready
    @just _check viz        http://localhost:8004/healthz/ready
    @just _check anomaly    http://localhost:8005/healthz/ready
    @docker compose exec -T mosquitto mosquitto_sub -t '$SYS/broker/uptime' -C 1 -W 2 >/dev/null 2>&1 \
        && echo "mqtt ✓" || echo "mqtt ✗"

# ─── sim + injection (host side; ROS 2 required where noted) ───────────────

# Launch Gazebo with the UR5 world. Requires ROS 2 Jazzy sourced.
sim:
    ros2 launch sim/launch/ur5_demo.launch.py

# Run the DDS↔MQTT bridge locally (requires ROS 2 sourced and `just up`).
bridge: _unhide
    MQTT_HOST=localhost uv run python -m bridge.main

# Run the fault-injector node: /joint_states_raw → /joint_states passthrough,
# faults on MQTT command. Requires ROS 2 sourced and `just up`.
injector: _unhide
    MQTT_HOST=localhost uv run python -m fault_injector.main

# Send a typed FaultCommand over MQTT (no ROS needed), e.g.:
#   just inject stuck --joint elbow --duration 10
#   just inject clear
inject *args: _unhide
    MQTT_HOST=localhost uv run python -m fault_injector.cli {{args}}

# ─── dataset + models ──────────────────────────────────────────────────────

# Run the scripted fault schedule against the live sim to build the corpus.
collect: _unhide
    uv run python scripts/collect.py

# Batch InfluxDB telemetry into labelled parquet windows in data/.
dataset *args: _unhide
    uv run python -m data_pipeline.cli {{args}}

# Notebooks (01 explore · 02 isoforest · 03 lstm-ae · 04 evaluate).
lab: _unhide
    uv run jupyter lab notebooks/

# ─── demo ──────────────────────────────────────────────────────────────────

# Inherited kill demo: each service in turn, assert graceful degradation.
chaos: _unhide
    uv run python scripts/chaos.py

# The repo's demo: inject all four faults; assert the score crosses the
# threshold inside every labelled window and stays under it otherwise.
demo: _unhide
    uv run python scripts/demo.py

# Record a 15s screencast of the overlay panel for the README. Requires peek.
record:
    peek --start-timer 3 --duration 15 --output-format gif \
         --output docs/demo/twin-anomaly.gif
