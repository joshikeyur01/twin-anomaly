# Build context is the repo root (see docker-compose.yml) so the image can
# include contracts/ and features/. Model artefacts are NOT copied in —
# compose bind-mounts models/ read-only, keeping the image artefact-free.

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Manifests first: dependency layers survive source-only changes. uv needs
# every workspace member's pyproject present to resolve, so copy them all.
COPY pyproject.toml uv.lock .python-version ./
COPY contracts/pyproject.toml contracts/
COPY features/pyproject.toml features/
COPY detector/pyproject.toml detector/
COPY bridge/pyproject.toml bridge/
COPY fault-injector/pyproject.toml fault-injector/
COPY data-pipeline/pyproject.toml data-pipeline/
COPY services/telemetry-svc/pyproject.toml services/telemetry-svc/
COPY services/state-svc/pyproject.toml services/state-svc/
COPY services/command-svc/pyproject.toml services/command-svc/
COPY services/viz-svc/pyproject.toml services/viz-svc/
COPY services/anomaly-svc/pyproject.toml services/anomaly-svc/

RUN uv sync --frozen --no-dev --no-install-workspace --package anomaly-svc

# Now the source that actually changes.
COPY contracts/ contracts/
COPY features/ features/
COPY detector/ detector/
COPY services/anomaly-svc/ services/anomaly-svc/

RUN uv sync --frozen --no-dev --package anomaly-svc

RUN useradd --create-home --uid 10001 svc
USER svc

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8005
CMD ["python", "-m", "anomaly_svc.main"]
