# Health Endpoint Contract and Implementation Plan

**Goal:** Establish a stable, unauthenticated liveness endpoint that monitoring systems can call cheaply and safely.

**Architecture:** Retain the existing health route on the unprefixed main Flask blueprint. Treat it as a shallow process-liveness check: successful request handling means the application is alive. Do not query SQLAlchemy or any external service in this endpoint; dependency readiness can be introduced separately if deployment requirements emerge.

**Tech stack:** Flask application factory and blueprints; pytest with Flask's test client.

---

## Repository findings

- Framework: Flask 3+, built through `app.create_app()` in `app/__init__.py`.
- Routing convention: `main_bp` is registered without a prefix; `api_bp` is registered under `/api`.
- Existing monitoring-like routes:
  - `GET /health` in `app/routes/main.py` returns `{"status": "ok"}` with HTTP 200.
  - `GET /api/status` in `app/routes/api.py` returns the same payload.
- Tests use shared `app` and `client` fixtures from `tests/conftest.py`; route assertions live in blueprint-specific test modules.
- SQLAlchemy is initialized at application startup, but the existing health handler performs no database query.
- No authentication, authorization, CSRF, rate-limiting, or request middleware currently exists.
- Baseline verification: `venv/bin/pytest -q` reports 20 passing tests.

## Contract

### Canonical endpoint

- Path: `/health`
- Method: `GET`
- Purpose: shallow liveness monitoring only.
- Authentication: none. This endpoint must remain publicly callable within the deployment's network boundary and must be explicitly exempted if global authentication is introduced later.
- Request body and query parameters: ignored; clients should send neither.

### Healthy response

- Status: `200 OK`
- Content type: `application/json`
- Exact JSON payload: `{"status": "ok"}`
- Payload must remain small and stable. Do not expose application configuration, database URLs, credentials, host details, stack traces, dependency names, versions, or timing data.

### Dependency behavior

- Do not check the database, upstream price providers, DNS, storage, or other external dependencies.
- The route reports healthy whenever Flask can dispatch and execute the handler.
- Startup/configuration failures remain startup failures and therefore prevent the service from answering at all.
- A future readiness endpoint, if needed, should be separate (for example `/ready`) and may return `503 Service Unavailable` when mandatory dependencies fail. Do not overload `/health` with readiness semantics because transient dependency trouble should not trigger process restarts.

### Method behavior

- Declare `GET` explicitly in the route for readability of the public contract.
- Flask may automatically service `HEAD` and `OPTIONS`; no custom behavior is required for them.
- Unsupported methods should retain Flask's standard `405 Method Not Allowed` response.

### Middleware and caching

- No middleware exception is needed today because none exists.
- If global authentication, CSRF, or redirect-to-login behavior is later added, exempt `/health`; monitoring must receive JSON directly rather than a redirect or HTML login page.
- Network-level access control and ordinary infrastructure rate limits may still apply, but no user session or API token should be required.
- Do not add dependency-specific retries or long timeouts. The handler must be constant-time and side-effect free.

## Implementation plan

### Task 1: Lock down route-level behavior with tests

**Files:**
- Modify: `tests/test_main.py`

1. Keep the existing healthy-response test and ensure it asserts all three contract essentials: `200`, JSON content type, and exact payload.
2. Add a test that sends a non-GET mutating method such as `POST /health` and asserts `405`.
3. Do not mock or initialize external services specifically for health tests; the shared testing app fixture is sufficient.
4. Run the focused test module and confirm the new assertion fails only if the current route does not meet the contract.

Verification command:

`venv/bin/pytest tests/test_main.py -q`

Expected result after implementation: all tests in the module pass.

### Task 2: Make the endpoint declaration explicit

**Files:**
- Modify: `app/routes/main.py`

1. Keep the endpoint on `main_bp` at `/health`.
2. Explicitly restrict the declared application method to `GET` while allowing Flask's automatic `HEAD` and `OPTIONS` handling.
3. Preserve the exact response payload and explicit status code.
4. Do not import or call `db`, models, service clients, or configuration beyond what Flask already needs for routing.
5. Do not remove or repurpose `/api/status` in this change; it is existing behavior and may already have consumers. `/health` is simply the canonical monitor endpoint going forward.

Verification command:

`venv/bin/pytest tests/test_main.py tests/test_api.py -q`

Expected result: both existing status routes remain compatible and all focused tests pass.

### Task 3: Document the operational contract

**Files:**
- Modify: `README.md`

1. Add a short health-check section documenting `GET /health`, the `200` response, and the exact payload.
2. State that it is an unauthenticated shallow liveness check and intentionally does not verify the database or upstream providers.
3. Avoid documenting `/api/status` as the monitoring endpoint; retain it only for backward compatibility unless a later task formally deprecates it.

Verification command:

`venv/bin/pytest -q`

Expected result: the complete suite passes with no regressions.

## Acceptance criteria

- `GET /health` returns HTTP 200.
- Its response has an `application/json` content type and parses exactly as `{"status": "ok"}`.
- Repeated calls are side-effect free and do not query the database or any external dependency.
- `POST /health` returns Flask's standard HTTP 405 response.
- The endpoint requires no cookie, login, bearer token, or API key and is not redirected to an authentication page.
- The response reveals no secrets, environment details, dependency topology, versions, or exception information.
- Existing `/api/status` behavior is unchanged.
- The README identifies `/health` as a shallow liveness check and explains that it is not a dependency-readiness check.
- The full pytest suite passes.

## Risks and tradeoffs

- A shallow liveness check can be green while the database or an upstream provider is unavailable. This is intentional: liveness answers whether the process should be restarted, not whether every dependency is ready.
- Maintaining both `/health` and `/api/status` leaves some duplication. Removing or redirecting `/api/status` is out of scope because its consumers are unknown.
- Publicly reachable health endpoints can attract traffic. Keep the payload fixed and non-sensitive, and control exposure at the reverse proxy or network layer rather than adding application credentials.
