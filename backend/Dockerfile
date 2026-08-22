# ── TrustRail Backend Dockerfile ─────────────────────────────────────────────
# Build context: project root (so `backend/` and `agent/` are both available)

FROM python:3.11-slim

# Install libpq for psycopg2 (needed even for the binary wheel on slim)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first so Docker can cache the pip layer
COPY backend/requirements.txt ./backend/requirements.txt

# psycopg2-binary is only needed for Postgres — harmless when using SQLite locally
RUN pip install --no-cache-dir \
        -r backend/requirements.txt \
        psycopg2-binary

# Copy application source
COPY backend/ ./backend/
COPY agent/   ./agent/

# Expose the API port
EXPOSE 8000

# Run with --reload so bind-mounted source changes are picked up in dev
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
