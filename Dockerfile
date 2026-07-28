# syntax=docker/dockerfile:1

FROM python:3.11-slim

# Prevent Python from writing bytecode and buffer stdout/stderr for clean logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=run.py

# Put the application on PATH.
ENV PATH="/app/.local/bin:${PATH}"

WORKDIR /app

# Create an unprivileged runtime user before installing dependencies.
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --home-dir /app --shell /bin/false appuser

# Install Python dependencies first so this layer can be cached across code changes.
COPY --chown=appuser:appuser requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the application source. The egg-info directory is excluded via .dockerignore.
COPY --chown=appuser:appuser pyproject.toml .
COPY --chown=appuser:appuser run.py .
COPY --chown=appuser:appuser migrations ./migrations
COPY --chown=appuser:appuser docker-entrypoint.sh .
COPY --chown=appuser:appuser app ./app

# Ensure the application and persistence directories are writable by the runtime user.
RUN mkdir -p /data && chown -R appuser:appuser /app /data

# Drop privileges for the runtime.
USER appuser

# Expose the port used by Gunicorn (keep in sync with the CMD bind address).
EXPOSE 8000

# Liveness probe: /health returns 200 without touching the database.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200 else 1)"

# Migration and seeding run once, single-process, before Gunicorn starts.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
# Default arguments passed to the entrypoint and on to Gunicorn.
CMD ["run:app", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "30"]
