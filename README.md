# AI Price Dashboard

A Flask application for tracking and displaying AI-related prices.

## Quick Start

1. Create and activate the project's virtual environment (`.venv/` is the canonical environment; recreate it with `python3.11 -m venv .venv` if it is missing):
   ```bash
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   # or, for development:
   pip install -e ".[dev]"
   ```

3. Copy environment variables:
   ```bash
   cp .env.example .env
   ```

4. Create the SQLite database and seed the sample models:
   ```bash
   flask --app run:app db upgrade
   flask --app run:app seed
   ```
   The default `sqlite:///app.db` resolves under the Flask instance folder
   (`<repo>/instance/app.db`).

5. Run the development server:
   ```bash
   python run.py
   ```
   This always uses `DevelopmentConfig`; no `FLASK_CONFIG` or `SECRET_KEY` is required.

6. Open http://127.0.0.1:5000 in your browser.

## Project Structure

- `app/` — Application package
  - `__init__.py` — Application factory (`create_app`)
  - `config.py` — Environment-based configuration classes
  - `extensions.py` — Flask extension instances (db, migrate)
  - `models/` — SQLAlchemy model definitions
  - `commands.py` — Custom Flask CLI commands (e.g. `flask seed`)
  - `routes/` — Flask blueprints
  - `templates/` — Jinja2 templates
  - `static/` — CSS/JS assets
  - `utils/` — Helper functions
  - `data/` — Seed data modules
- `tests/` — Pytest test suite
- `migrations/` — Database migrations (generated via Flask-Migrate)
- `run.py` — Development entry point

## Database

The application uses a persistent SQLite database via Flask-SQLAlchemy and
Flask-Migrate.

- **New installs** self-seed with the 22 sample models from
  `app/data/sample_models.py` when you run `flask seed` or use the Docker
  entrypoint.
- **Schema changes** are applied with `flask db upgrade`; `create_app()` does
  not perform any DDL, so it is safe to run multi-worker Gunicorn deployments.
- **Development DB location:** the default `sqlite:///app.db` resolves under
  `<repo>/instance/app.db`. Delete `instance/app.db` and rerun `flask db
  upgrade && flask seed` to reset.
- **Container DB location:** `docker-compose.yml` mounts `/data` from an
  `app-data` named volume and sets `DATABASE_URL=sqlite:////data/app.db`, so
  data survives container restarts.
- **Re-seeding:** `flask seed --force` deletes existing model rows and re-seeds
  from `SAMPLE_MODELS`. This is intended for development only and is not run by
  the container entrypoint.

## Health Check

`GET /health` is an unauthenticated, shallow liveness endpoint used by load
balancers and orchestrators. It returns HTTP 200 with the JSON payload:

```json
{ "status": "ok" }
```

This endpoint intentionally does not query the database or any upstream price
providers. It only confirms that the Flask process can accept and dispatch a
request. Dependency readiness checks (readiness probes) should target a separate
endpoint if they become necessary.

## Running Tests

```bash
.venv/bin/python -m pytest
```

## Production

Use a WSGI server such as Gunicorn. The provided `docker-entrypoint.sh` runs
migrations and seeding once before exec'ing Gunicorn:

```bash
# Make sure SECRET_KEY is set to a real, secret value.
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export FLASK_CONFIG=production

gunicorn "run:app" --bind 0.0.0.0:8000
```

`ProductionConfig` requires a non-empty `SECRET_KEY`; Gunicorn will fail to
start if `SECRET_KEY` is missing, empty, or whitespace.

To run locally, use the development server which always selects
`DevelopmentConfig`:

```bash
python run.py
```
