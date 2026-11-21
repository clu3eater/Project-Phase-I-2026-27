# Digital twin for aero piston engines -- DRDO PS 26054.
#
# Two stages. The console is a compiled artifact, so Node is needed to BUILD it
# and has no business in the image that runs. The runtime stage carries Python,
# the application and the built console, and nothing else.

# ---------------------------------------------------------------------------
# Stage 1: build the console
# ---------------------------------------------------------------------------
FROM node:22-slim AS console

WORKDIR /build
# package.json and the lockfile are copied first so that a source-only change
# does not invalidate the dependency layer.
COPY layer5_viz/gcs_console/package*.json ./
RUN npm ci --no-audit --no-fund

COPY layer5_viz/gcs_console/ ./
RUN npm run build


# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim

# Cantera and SciPy need a compiler toolchain only at install time; it is
# removed again so it does not travel to a deployed edge node.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# DEPENDENCIES FIRST, FROM A HASH-VERIFIED LOCK FILE.
#
# requirements.lock is fully pinned and resolved for linux/amd64.
# --require-hashes makes the build refuse any artefact whose SHA-256 does not
# match, so an image built today and one built in six months contain the same
# code. That is the point for a deliverable that has to be auditable.
#
# THE PREVIOUS VERSION OF THIS BLOCK COULD NOT BUILD AT ALL. It ran
# `pip install .` here, with only pyproject.toml copied and no source yet, so
# setuptools had no packages to build and the step died with "Getting
# requirements to build wheel did not run successfully". The image was never
# producible and `docker compose up` had never worked. Verified by reproducing
# it in an isolated directory containing only pyproject.toml.
#
# Splitting it fixes that and keeps the layer-cache intent: dependencies are a
# cached layer that survives every source change; the project itself installs
# afterwards, once its source actually exists.
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY common/       ./common/
COPY configs/      ./configs/
COPY layer1_edge/  ./layer1_edge/
COPY layer2_physics/ ./layer2_physics/
COPY layer3_ai/    ./layer3_ai/
COPY layer4_core/  ./layer4_core/
# Declared as a package in pyproject, so `pip install .` needs its
# source present or the build fails with 'package directory
# fleet_server does not exist'. Caught by CI on the first push.
COPY fleet_server/ ./fleet_server/
COPY layer5_viz/__init__.py ./layer5_viz/
COPY scripts/      ./scripts/
COPY docs/         ./docs/
COPY README.md ./
COPY docs/prd/PROJECT_PLAN.md docs/ps.md docs/

# The precomputed adiabatic-flame lookup (decision D7). These three JSON files
# are TRACKED, not generated, and the physics needs one on every tick:
# `combustion.py::_lookup_flame` raises RuntimeError without it, and the only
# fallback is a live Cantera solve -- the `physics` extra, deliberately not
# installed here because an equilibrium solve blows the 10-20 ms budget of PRD
# Part 1 s6.4. `.dockerignore` used to exclude all of `data/`, so the image
# shipped without them and the engine could not have run even had it started.
COPY data/physics/ ./data/physics/

# The project itself, now that its source exists. --no-deps because every
# dependency is already installed from the hash-verified lock above, and a
# resolver run here could silently pull something the lock never sanctioned.
RUN pip install --no-cache-dir --no-deps .
RUN apt-get purge -y build-essential && apt-get autoremove -y

COPY --from=console /build/dist ./layer5_viz/gcs_console/dist

# The virtual CAN bus is in-process (python-can's `virtual` interface), so the
# container needs no privileged access and no kernel module. Decision D1: on a
# real edge node this becomes socketcan, which is a configuration string.
# 0.0.0.0, because 127.0.0.1 inside a container is the CONTAINER's own
# loopback: a published port forwards to an interface nothing listens on.
# The image started perfectly and was unreachable, which CI caught as
# 'container never reported a running pipeline'.
#
# The insecure-bind opt-in is explicit rather than implied. A container's
# isolation boundary is the network it is attached to, and a real
# deployment puts a TLS-terminating proxy in front. Set DT_TLS_CERT and
# DT_TLS_KEY to terminate TLS in-process instead, and the opt-in no longer
# applies because the refusal it bypasses no longer triggers.
ENV PYTHONUNBUFFERED=1 \
    DT_DATA_DIR=/app/data \
    DT_HOST=0.0.0.0 \
    DT_ALLOW_INSECURE_BIND=1

# Run as an unprivileged user. The image previously ran as root, which is a
# needless privilege for a process that binds one port and writes one data
# directory. /app/data is created and chowned HERE, before the USER switch, so
# that Docker propagates this ownership to the named volume mounted over it --
# a volume mounted onto a root-owned path would be unwritable to appuser.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# A container that reports itself healthy only once the pipeline is actually
# producing ticks, not merely once the port is open.
HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request,json,sys; \
d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/healthz')); \
sys.exit(0 if d.get('ok') else 1)"

CMD ["python", "-m", "layer4_core.twin_api"]
