# Opportunity Tracking Agent -- API and jobs (WBS 13.1).
# One image, three commands: the API (default), the scheduler loop, or a single job.
#   docker run image                                  -> uvicorn
#   docker run image python -m scripts.scheduler      -> the in-process job loop
#   docker run image python -m scripts.run_job stall_sweep
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# pg_dump/pg_restore for the backup drill against Postgres (WBS 13.5).
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
RUN pip install ".[postgres]"

RUN useradd --create-home --uid 10001 opptrack && mkdir -p /app/data && chown -R opptrack /app
USER opptrack

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
