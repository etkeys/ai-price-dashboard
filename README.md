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

4. Run the development server:
   ```bash
   python run.py
   ```
   This always uses `DevelopmentConfig`; no `FLASK_CONFIG` or `SECRET_KEY` is required.

5. Open http://127.0.0.1:5000 in your browser.

## Project Structure

- `app/` — Application package
  - `__init__.py` — Application factory (`create_app`)
  - `config.py` — Environment-based configuration classes
  - `extensions.py` — Flask extension instances (db, migrate)
  - `routes/` — Flask blueprints
  - `templates/` — Jinja2 templates
  - `static/` — CSS/JS assets
  - `utils/` — Helper functions
- `tests/` — Pytest test suite
- `migrations/` — Database migrations (generated via Flask-Migrate)
- `run.py` — Development entry point

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

Use a WSGI server such as Gunicorn. The WSGI entry point reads the
`FLASK_CONFIG` environment variable and defaults to `production`, so the
documented command always runs with `ProductionConfig`:

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
