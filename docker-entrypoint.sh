#!/usr/bin/env sh
set -e

# Apply database schema migrations and seed sample data before starting the
# WSGI server. Running these single-process steps here prevents a multi-worker
# Gunicorn race and leaves a correct alembic_version row.
flask db upgrade
flask seed
flask auth bootstrap

# Replace the shell with Gunicorn so signals (e.g. SIGTERM) reach the workers.
exec gunicorn "$@"
