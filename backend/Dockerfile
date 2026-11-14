# The API is optional: the published site is static and complete without it.
# This image exists so running one is a single command when wanted.
#
#   docker build -t antilethe-api backend
#   docker run -p 8000:8000 -v "$PWD/data:/data" antilethe-api
#
# Mount an archive at /data, or run `antilethe ingest` inside the container.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    ANTILETHE_DB_PATH=/data/archive.db

WORKDIR /app

# Dependency metadata first, so a source edit does not reinstall the world.
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 antilethe \
    && mkdir -p /data \
    && chown -R antilethe:antilethe /data /app

USER antilethe

EXPOSE 8000

# The API serves computed data only; it never calls a model and never writes
# upstream, so a read-only container with a mounted archive is enough.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "antilethe.api:app", "--host", "0.0.0.0", "--port", "8000"]
