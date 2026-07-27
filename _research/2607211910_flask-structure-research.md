# Flask Project Structure Research

## Purpose

This document defines the recommended directory layout, configuration approach, and entry points for the ai-price-dashboard Flask application. It serves as the blueprint for task t_d1470ae6 (create boilerplate) and ultimately t_b4f15a37 (assemble the project).

---

## 1. Recommended Directory Layout

```
ai-price-dashboard/
├── app/                          # Application package
│   ├── __init__.py               # Application factory (create_app)
│   ├── config.py                 # Configuration classes (Dev, Prod, Test)
│   ├── extensions.py             # Flask extension instances (db, migrate, etc.)
│   ├── models/                   # Data models (SQLAlchemy or similar)
│   │   ├── __init__.py
│   │   └── price.py              # Example: Price model
│   ├── routes/                   # Blueprints (view logic)
│   │   ├── __init__.py
│   │   ├── main.py               # Main/dashboard blueprint
│   │   └── api.py                # API blueprint (JSON endpoints)
│   ├── services/                 # Business logic layer
│   │   ├── __init__.py
│   │   └── price_service.py      # Price data fetching/processing
│   ├── templates/                # Jinja2 templates
│   │   ├── base.html             # Base layout
│   │   └── index.html            # Dashboard page
│   ├── static/                   # Static assets (CSS, JS, images)
│   │   ├── css/
│   │   │   └── style.css
│   │   └── js/
│   │       └── dashboard.js
│   └── utils/                    # Utility functions
│       ├── __init__.py
│       └── helpers.py
├── tests/                        # Test suite (outside app package)
│   ├── __init__.py
│   ├── conftest.py               # Pytest fixtures (app factory, test client)
│   ├── test_main.py             # Route tests
│   └── test_api.py              # API tests
├── migrations/                   # Database migrations (Flask-Migrate / Alembic)
├── .env.example                  # Example environment variables
├── .gitignore
├── pyproject.toml                # Project metadata, dependencies, tool config
├── requirements.txt              # Pinned production dependencies (optional, for Docker)
├── run.py                        # Development entry point
└── README.md                     # Project documentation
```

---

## 2. Key Architectural Decisions

### 2.1 Application Factory Pattern

The core of the structure is the `create_app()` factory function in `app/__init__.py`. Instead of creating a Flask app at module level, we define a function that constructs and returns the app. This pattern is recommended by the official Flask documentation and is the de facto standard for any non-trivial Flask project.

**Why:**
- Enables multiple configurations (dev, test, prod) from the same codebase.
- Makes testing straightforward — each test can create a fresh app instance with test config.
- Avoids circular import problems that arise when extensions are defined at module level.
- Allows blueprints to be registered conditionally based on environment.

**Structure in `app/__init__.py`:**

```python
from flask import Flask

def create_app(config_name="default"):
    app = Flask(__name__)
    
    # Load configuration
    app.config.from_object(f"app.config.{config_name}")
    
    # Initialize extensions
    from app.extensions import db, migrate
    db.init_app(app)
    migrate.init_app(app, db)
    
    # Register blueprints
    from app.routes.main import main_bp
    from app.routes.api import api_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    
    return app
```

### 2.2 Blueprints for Modular Routes

Flask Blueprints group related views, templates, and static files. Each major feature area gets its own blueprint.

**Why:**
- Keeps `app/__init__.py` thin — it only wires things together.
- Routes are split by concern (dashboard views vs API endpoints vs auth).
- Blueprints can be moved to separate packages or even installed as separate packages in larger projects.

### 2.3 Configuration via Class Hierarchy

Configuration lives in `app/config.py` as a class hierarchy. The `create_app()` function selects a config class by name, typically driven by the `FLASK_ENV` environment variable.

**Why:**
- Sensitive values (secret keys, database URIs) are read from environment variables, not hardcoded.
- Different configs for development, testing, and production.
- The base `Config` class holds defaults; subclasses override as needed.

**Structure in `app/config.py`:**

```python
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False

class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
```

### 2.4 Extensions in a Separate Module

All Flask extension objects (SQLAlchemy, Migrate, etc.) are instantiated in `app/extensions.py` without being bound to an app. They are bound later inside `create_app()` via `db.init_app(app)`.

**Why:**
- Prevents circular imports — extensions don't import the app, the app imports them.
- Centralized location for all extension instances.
- Extensions are easy to find and add.

### 2.5 Service Layer

Business logic (fetching prices, processing data, calling external APIs) lives in `app/services/`, separate from route handlers.

**Why:**
- Route handlers stay thin — they validate input, call a service, and return a response.
- Business logic is testable without HTTP context.
- If the project grows, services can be extracted into a separate package.

### 2.6 Tests Outside the App Package

Tests live in a top-level `tests/` directory, not inside `app/`. This is the Flask documentation's own convention.

**Why:**
- Tests are not part of the distributable package.
- `conftest.py` provides pytest fixtures that call `create_app()` with `TestingConfig`.
- Each test module can get a fresh app and test client via fixtures.

---

## 3. Entry Points

### 3.1 Development Server: `run.py`

A thin script at the project root for local development. It imports the factory and starts the Flask dev server.

```python
from app import create_app

app = create_app("development")

if __name__ == "__main__":
    app.run()
```

### 3.2 Production: WSGI Server

For production, a WSGI server (Gunicorn or uWSGI) imports the factory:

```bash
gunicorn "run:app" --bind 0.0.0.0:8000
```

The `app` object in `run.py` is the WSGI application.

### 3.3 CLI via pyproject.toml (Optional)

For a more polished setup, define a console script entry point in `pyproject.toml`:

```toml
[project.scripts]
ai-price-dashboard = "app.cli:main"
```

This enables `flask --app run.py` commands and custom CLI commands via `app.cli`.

---

## 4. Configuration Files

### 4.1 pyproject.toml

The modern standard for Python project metadata. Replaces `setup.py` and `setup.cfg`. Contains:

- Project name, version, description, Python version requirement.
- Dependencies (Flask, SQLAlchemy, python-dotenv, etc.).
- Dev dependencies (pytest, flake8/ruff) in optional groups.
- Tool configuration (ruff, black, pytest).

### 4.2 requirements.txt

A pinned list of production dependencies for reproducible installs (especially in Docker). Can be generated from `pyproject.toml` via `pip freeze` or `uv export`.

### 4.3 .env.example

A template for environment variables. The real `.env` file (gitignored) holds actual secrets locally. This file documents what variables the app expects.

### 4.4 .gitignore

Standard Python gitignore plus Flask-specific entries:
- `.env` (secrets)
- `__pycache__/`, `*.pyc`
- `instance/` (Flask instance folder for local config)
- `app.db` (dev SQLite database)
- `.venv/`

---

## 5. Summary of Conventions

| Concern              | Pattern                          | Location                  |
|----------------------|----------------------------------|---------------------------|
| App creation         | Application Factory              | `app/__init__.py`         |
| Configuration        | Class hierarchy + env vars       | `app/config.py`           |
| Extensions           | Deferred init via init_app       | `app/extensions.py`       |
| Routes               | Blueprints by feature            | `app/routes/`             |
| Business logic       | Service layer                    | `app/services/`           |
| Data models          | SQLAlchemy models                | `app/models/`             |
| Templates            | Jinja2                           | `app/templates/`          |
| Static assets        | CSS/JS                           | `app/static/`             |
| Tests                | Pytest, outside app package      | `tests/`                  |
| Entry point (dev)    | run.py                           | Project root              |
| Entry point (prod)   | WSGI import                      | `gunicorn "run:app"`      |
| Dependencies         | pyproject.toml + requirements.txt| Project root              |
| Environment vars     | .env + .env.example              | Project root              |

---

## 6. Notes for Dale (t_d1470ae6)

- All directories that are Python packages need `__init__.py` files.
- `app/extensions.py` should instantiate `db = SQLAlchemy()` and `migrate = Migrate()` but NOT call `init_app` — that happens in `create_app()`.
- `run.py` at root level should be minimal: import `create_app`, call it, and run.
- `tests/conftest.py` should define an `app` fixture that calls `create_app("testing")` and a `client` fixture that returns `app.test_client()`.
- `pyproject.toml` should include at minimum: flask, flask-sqlalchemy, flask-migrate, python-dotenv as dependencies. Dev group: pytest, pytest-cov.
- The `.venv` directory already exists in the workspace — do not recreate it.
- `migrations/` will be generated by `flask db init` later; create the directory but it can start empty or be omitted until Dale runs the init command. A placeholder `migrations/README.txt` is sufficient.
