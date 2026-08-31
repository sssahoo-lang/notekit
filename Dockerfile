# Production image for the NoteKit API.
#
# The embedding and reranking models run locally, which is what keeps this on a
# single API key, and what makes the image large. Two things follow:
#
#   * The CPU-only torch build is installed explicitly. The default wheel pulls
#     CUDA libraries worth well over a gigabyte that will never be used on a
#     server without a GPU.
#   * Model weights are downloaded at build time, not first request. Otherwise
#     every cold start fetches 421MB from HuggingFace before it can answer, and
#     a platform health check times out long before that finishes.

FROM python:3.11-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /app

# CPU-only torch first, so the resolver does not pull the CUDA build.
RUN uv venv /app/.venv \
    && VIRTUAL_ENV=/app/.venv uv pip install --no-cache \
        --index-url https://download.pytorch.org/whl/cpu torch

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN VIRTUAL_ENV=/app/.venv uv pip install --no-cache .


FROM python:3.11-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/.cache/huggingface \
    # Threads are capped because the container is small and torch will happily
    # spawn one worker per visible core, which on a shared host means
    # contention rather than speed.
    OMP_NUM_THREADS=2 \
    TOKENIZERS_PARALLELISM=false

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

# The user is created before anything is copied so ownership can be set during
# COPY. A `chown -R` afterwards rewrites every file's metadata and duplicates
# the whole venv into a second layer, measured at 1.73GB on top of the 1.5GB
# it was copying.
RUN useradd --create-home --uid 10001 notekit

WORKDIR /app

COPY --from=builder --chown=notekit:notekit /app/.venv /app/.venv
COPY --chown=notekit:notekit src ./src
COPY --chown=notekit:notekit scripts/schema.sql ./scripts/schema.sql
COPY --chown=notekit:notekit evalsets ./evalsets
COPY --chown=notekit:notekit fixtures ./fixtures

# /app itself is created by WORKDIR and stays root-owned, so the cache
# directory has to be made writable explicitly. The model download below runs
# as notekit and cannot create it otherwise.
RUN mkdir -p ${HF_HOME} && chown -R notekit:notekit /app/.cache

USER notekit

# Bake the weights in, as the runtime user so the cache is already owned
# correctly. Without this the first request after every deploy pays a 421MB
# download before it can retrieve anything, and the health check times out.
RUN python -c "\
from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('BAAI/bge-small-en-v1.5'); \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2'); \
print('models cached')"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-8000}/api/health || exit 1

# Railway and most platforms inject PORT. One worker on purpose: each would
# load its own copy of the models, and two copies will not fit the RAM this
# image is sized for.
CMD ["sh", "-c", "uvicorn notekit.api:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
