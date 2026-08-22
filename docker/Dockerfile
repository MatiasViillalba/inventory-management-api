# Multi-stage build for the Inventory Management API.
#
# The same image is used for every Python process in this project —
# the FastAPI web server, the Celery worker, and Celery Beat — since
# they share the exact same dependency set (see requirements/base.txt).
# docker-compose selects which one a given container runs by overriding
# CMD, rather than building a separate image per process.
#
# Stage "builder" installs build tooling and compiles/downloads every
# Python dependency into an isolated virtualenv. Stage "runtime" copies
# only that finished virtualenv and the application source across, so
# the final image never carries a C compiler, pip's cache, or any other
# build-time-only weight — only what's needed to actually run the app.

# --- Stage 1: builder ---
FROM python:3.12-slim-bookworm AS builder

# build-essential is only needed here in case a dependency (or a future
# one) has no prebuilt wheel for the target platform and must be
# compiled from source; it never reaches the runtime stage.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# A dedicated virtualenv, rather than installing into the system
# site-packages, is what makes "copy the whole environment to the next
# stage" possible: everything the app depends on lives under this one
# self-contained directory.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build

# Copied and installed before the rest of the source so this layer is
# only invalidated by a dependency change, not by every code change.
COPY requirements/base.txt requirements/base.txt
RUN pip install --upgrade pip \
    && pip install -r requirements/base.txt

# --- Stage 2: runtime ---
FROM python:3.12-slim-bookworm AS runtime

# curl backs the HEALTHCHECK below; nothing else here needs system
# packages, since asyncpg speaks the Postgres wire protocol directly
# (no libpq) and psycopg2-binary bundles its own libpq statically.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --create-home --shell /bin/bash appuser

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser migrations ./migrations
COPY --chown=appuser:appuser alembic.ini ./alembic.ini

USER appuser

EXPOSE 8000

# Reuses the same health check the load balancer/orchestrator would
# use, so a container that reports unhealthy here also reports
# unhealthy in production.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# The default process is the web server; docker-compose overrides this
# CMD for the Celery worker and Beat containers, which reuse this same
# image and virtualenv.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
