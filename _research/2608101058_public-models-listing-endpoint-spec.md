# Spec: Public models listing endpoint

**Card:** t_937ed477 — Design REST endpoint for listing models with hidden filter
**Root card:** t_bca012d9 — Add publish REST endpoint to get a listing of all models and their details
**Implements into:** t_fa898e85 (Dale), reviewed by t_7d9581e9 (Kova)
**Author:** chip (architect)
**Date:** 2026-08-10
**Code state described:** `feat/public-modalities-endpoint` @ `999f495`, Alembic head `453c7603f37a`, version 0.2.0

---

## 1. Summary / Recommendation

Add one route:

```
GET /api/v1/models[?include_hidden=true|false]   →   200   {"models": [ {...}, ... ]}
```

Unauthenticated. Served from `ai_models` with `selectin`-loaded modality
relationships, ordered `sort_name, name`. Default **excludes** hidden models.
Cacheable for 60 seconds, CORS-open, scoped to this route only.

Four things make this more than a serializer, and they are the substance of this
document:

1. **`AiModel.is_hidden` is broken as a SQL expression.** The hybrid shipped by
   PR #12 raises `InvalidRequestError` the moment it is used in a `WHERE`
   clause — which is the only reason it exists (D-020). The natural
   implementation of this endpoint is the first code that would trip it.
   Reproduced and fixed in §6.
2. **`id` belongs in this response, and D-026 said the opposite for
   modalities.** The two are not in conflict, but the difference has to be
   argued or a reviewer will read it as inconsistency. §4.2.
3. **Modality lists must come back in persisted `position` order, not the
   alphabetical order the HTML surfaces render** (D-008). A read→write round
   trip through this API must not silently reorder a model's stored modality
   sequence. §4.4.
4. **Exposing `hidden` publicly leaks nothing new** — verified, because
   `/admin/models/manage` already serves every model plus its hidden status to
   an unauthenticated client. §7 records this, and files it as an existing
   condition this card must not silently ride on.

**§B is empty. This document hands off directly to Dale.** Justification in §12.

---

## 2. What exists today

Verified by reading and by execution against `.venv` (SQLAlchemy 2.0.51,
Flask test client).

### 2.1 Route inventory

`app.url_map` on `create_app("testing")`, in full:

| Path | Methods | Auth | Notes |
|---|---|---|---|
| `/` | GET | none (D-004) | HTML dashboard, filters hidden (D-021) |
| `/health` | GET | none | liveness |
| `/api/v1/modalities` | GET | none | D-025..D-029, `999f495` |
| `/auth/session` | POST, DELETE | mixed | credential exchange |
| `/auth/whoami` | GET | token | |
| `/auth/recovery/claim` | POST | none | |
| `/admin/keys*` | GET/POST/DELETE | administrator | `Cache-Control: no-store` |
| `/admin/models/manage` | GET | **none** | HTML shell — see §7 |
| `/admin/models` | POST | administrator (D-006) | |
| `/admin/models/<id>` | PATCH | updater (D-012) | |
| `/admin/models/<id>/hidden` | PUT | administrator (D-019) | |

There is **no** `GET /admin/models` and no model read endpoint of any kind.
This endpoint is the first machine-readable read path for model data.

### 2.2 The data

`AiModel` (`app/models/ai_model.py:89-195`):

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | stable per row, addressed by two existing write endpoints |
| `name` | VARCHAR(128) UNIQUE | immutable for both roles (D-012) |
| `price_in` / `price_out` | FLOAT, CHECK `>= 0` | |
| `context_tokens` | INTEGER, CHECK `> 0` | |
| `created_at` / `updated_at` | DATETIME NOT NULL | naive, UTC — see §4.5 |
| `hidden_at` | DATETIME NULL | NULL = visible (D-020) |

Plus `input_content` / `output_content` — read-only `list[str]` properties over
ordered relationships (`:151-159`), and the `sort_name` (D-017) and `is_hidden`
(D-020) hybrids.

22 seeded rows (`app/data/sample_models.py`). This number governs every
scaling decision below.

### 2.3 Verified query cost

The `/` route's query shape, re-run with a `before_cursor_execute` counter:

```
select(AiModel).where(AiModel.hidden_at.is_(None))
    .options(selectinload(input_modalities), selectinload(output_modalities))
    .order_by(AiModel.sort_name, AiModel.name)
→ 3 queries, 21 rows (1 of 22 hidden)
```

Unfiltered: **3 queries, 22 rows.** The relationships are already
`lazy="selectin"` (`app/models/ai_model.py:132,140`), so the explicit
`.options()` is belt-and-braces — verified identical at 3 queries with the
options omitted. Dale should still pass them explicitly, matching
`app/routes/main.py:19-22`, so the guarantee is local to the query rather than
dependent on a relationship default a future edit could change.

---

## 3. Path, method, and the filter parameter

### 3.1 Decision (D-030a): the path is `GET /api/v1/models`

The card body suggests `/api/publish/models`. **Rejected.** D-025 (ASSUMED, and
load-bearing on shipped code at `999f495`) fixed `/api/v1/` as the public,
agent-facing REST prefix, chosen deliberately to denote *audience* rather than
auth class. "publish" is neither an audience nor a resource — it is a verb
fragment, and it would give this app two public API prefixes on its second
public endpoint.

`models` is the plural collection noun matching the resource, consistent with
`/api/v1/modalities`.

Anticipated shape, per D-013's binding consequence that naming should
anticipate the public write API:

```
GET    /api/v1/models          ← this card
GET    /api/v1/models/<id>     ← plausible next, not in scope
PATCH  /api/v1/models/<id>     ← the public write API D-013 told us to expect
```

The `id` field in §4.2 is what makes that progression addressable. This is a
concrete, non-hypothetical reason it is in the response.

### 3.2 Decision (D-030b): `?include_hidden=` — strict boolean, default `false`

Parameter name `include_hidden`. Accepted values: `true`, `false`,
**case-insensitive**, nothing else. Absent → `false`.

| Request | Behaviour |
|---|---|
| `/api/v1/models` | visible models only (`hidden_at IS NULL`) |
| `/api/v1/models?include_hidden=false` | identical to above |
| `/api/v1/models?include_hidden=true` | **all** models, hidden and visible |
| `/api/v1/models?include_hidden=TRUE` | same as `true` |
| `/api/v1/models?include_hidden=1` | **400** |
| `/api/v1/models?include_hidden=yes` | **400** |
| `/api/v1/models?include_hidden=` | **400** |
| `/api/v1/models?unknown=x` | ignored, 200 |

**Default `false` is the correct default and is not arbitrary.** It makes the
zero-configuration response agree with `/` (D-021), which is the surface a human
looks at. An agent that wants the full picture opts in explicitly. The reverse
default would mean the simplest possible call returns rows the dashboard denies
exist.

#### Why strict parsing, and why `type=bool` must not be used

Flask's built-in coercion is a trap here. Verified:

```
?include_hidden=false → request.args.get('include_hidden', type=bool) is True
?include_hidden=0     → True
?include_hidden=      → False
```

`type=bool` is `bool(str)` — non-empty is truthy. Using it would make
`include_hidden=false` *include* hidden models: the exact inversion of the
caller's intent, silently. **Dale must not use `type=bool`. Kova must reject it
on sight.**

The strict allow-list also follows D-022's precedent, which rejected `1` as a
value for `hidden` on `PUT /admin/models/<id>/hidden` for the same class of
reason (`1 == True` in Python). Two endpoints in the same app disagreeing about
whether `1` means true would be worse than either choice alone.

`1`/`0`/`yes`/`on` are rejected rather than accepted-leniently because a
rejected value produces a 400 the caller can read, whereas a leniently-accepted
one produces a plausible-looking wrong answer. For a filter whose entire job is
to decide what the caller does *not* see, silence is the expensive failure.

#### Duplicate parameter

`?include_hidden=true&include_hidden=false` → Werkzeug's `args.get` returns the
**first** value (verified: `getlist` gives `['all','hidden']` for a duplicated
key, `get` gives `'all'`). Specified behaviour: **first value wins**, no error.
Pin it in a test so the behaviour is known rather than incidental.

#### Rejected alternatives

- **`?hidden=include|exclude|only`** — a tri-state. Rejected: `only` is
  derivable client-side from `include_hidden=true` plus the per-object `hidden`
  field (§4.3), so it buys nothing and costs a third code path. If a real
  consumer needs server-side hidden-only, it is a purely additive parameter
  later.
- **`?visibility=visible|hidden|all`** — same objection, plus it renames the
  concept the rest of the codebase calls "hidden" (D-020, D-021, D-022).
- **Two endpoints** (`/models` and `/models/hidden`) — a filter is not a
  resource.

### 3.3 Methods

`methods=["GET"]` declared explicitly. Everything else is Flask's automatic
`405` — verified against the existing public route: `POST /api/v1/modalities`
returns `405` with `Allow: HEAD, OPTIONS, GET`. `HEAD` works automatically; do
not add a handler.

---

## 4. Response contract

### 4.1 Success

```
GET /api/v1/models
```

```
200 OK
Content-Type: application/json
Cache-Control: public, max-age=60
Access-Control-Allow-Origin: *
```

```json
{
  "models": [
    {
      "id": 1,
      "name": "anthropic/claude-haiku-4.5",
      "price_in": 1.0,
      "price_out": 5.0,
      "context_tokens": 200000,
      "input_content": ["Text", "Images", "Files"],
      "output_content": ["Text"],
      "hidden": false,
      "hidden_at": null,
      "created_at": "2026-08-10T10:54:19Z",
      "updated_at": "2026-08-10T10:54:19Z"
    }
  ]
}
```

Envelope is an object with a `models` key, **not** a bare top-level array.
Dale's card body says "return a JSON array"; that wording is overridden. The
envelope matches `GET /admin/keys` → `{"keys": [...]}`
(`app/routes/admin.py:93`) and `GET /api/v1/modalities` →
`{"modalities": [...]}` (D-026), and it leaves room for a sibling key (a
`count`, a cursor) without a breaking change. A bare array has no such room.

**No `count` / `total` field.** It is `len(models)` and adding it is a promise
to keep it correct through every future change for no consumer benefit.

### 4.2 Decision (D-031): `id` **is** included — and why that does not contradict D-026

D-026 kept `id` out of the modalities response. Three reasons were given; check
each against models:

| D-026's reason for omitting modality `id` | Does it apply to models? |
|---|---|
| Ids are not stable across deployments — assigned by seed insertion order from a code literal | **No.** `ai_models.id` is a persisted surrogate for an operator-created row. It is not derived from a code constant, and nothing renumbers it. |
| Nothing accepts an id — every write path addresses modalities **by name** | **No — inverted.** Both model write endpoints address the model **by id**: `PATCH /admin/models/<int:model_id>` (`app/routes/admin.py:394`) and `PUT /admin/models/<int:model_id>/hidden` (`:461`). Model `name` is explicitly immutable (D-012), but the addressing key is the id. |
| It is an internal surrogate with no consumer | **No.** The consumer is the agent this card exists for: read the listing, decide what to update, `PATCH` by id. Omitting `id` makes the read→write loop impossible without a second lookup that does not exist. |

All three reasons invert. `id` is in. The principle D-026 actually established —
*publish the token the client is meant to send back* — is what puts `id` in this
response and keeps it out of that one. Kova should treat the apparent
inconsistency as resolved here rather than as a defect.

### 4.3 Field set

| Field | Type | Source | Notes |
|---|---|---|---|
| `id` | int | `AiModel.id` | §4.2 |
| `name` | string | `AiModel.name` | verbatim, tilde and all (D-015) |
| `price_in` | number | `AiModel.price_in` | USD / 1M input tokens |
| `price_out` | number | `AiModel.price_out` | USD / 1M output tokens |
| `context_tokens` | int | `AiModel.context_tokens` | raw count, **not** humanized |
| `input_content` | list[string] | `AiModel.input_content` | §4.4 |
| `output_content` | list[string] | `AiModel.output_content` | §4.4 |
| `hidden` | bool | `hidden_at is not None` | §4.6 |
| `hidden_at` | string \| null | `AiModel.hidden_at` | ISO 8601, §4.5 |
| `created_at` | string | `AiModel.created_at` | ISO 8601, §4.5 |
| `updated_at` | string | `AiModel.updated_at` | ISO 8601, §4.5 |

**`context_tokens` is the raw integer.** `format_context()`
(`app/utils/helpers.py`) turns `200000` into `"200K"` for the HTML surfaces.
That is presentation. An API that returns `"200K"` forces every consumer to
parse it back. Kova should reject any use of `format_context` or `format_price`
in this route.

**Every field is always present.** No conditional keys. A consumer should never
have to branch on key existence; `hidden_at` is `null` rather than absent when
the model is visible, matching the existing `PUT .../hidden` response
(D-022).

**Nothing else is exposed.** No association-table `position` integers, no
`Modality.id`, no internal counts. The response is exactly the model's public
attributes.

### 4.4 Decision (D-032): modality lists in persisted `position` order, not alphabetical

`input_content` returns `["Text", "Images", "Files"]` for
`anthropic/claude-haiku-4.5` — verified. That is `position` order, the order the
author submitted (`app/routes/admin.py:368-383`).

The HTML surfaces render these **alphabetically** via a Jinja `| sort`
(D-008 / `app/templates/index.html:28-29`). This endpoint deliberately does
**not** do that. Reasons, in order of weight:

1. **Round-trip fidelity.** An agent that reads a model, changes a price, and
   `PATCH`es the whole object back would, under alphabetical ordering, rewrite
   every association row into alphabetical order as a side effect. `PATCH`
   deletes and re-inserts association rows from list order
   (`app/routes/admin.py:437-448`), so this is a real write, not a cosmetic one.
   A read endpoint must not cause data churn on write-back.
2. **D-008 was explicitly scoped as presentation-only.** Its assumption in force
   is a `| sort` in one template, with "the domain model, both relationship
   `order_by` clauses, both properties and the `position` column untouched."
   `input_content` *is* one of those properties. Sorting here would extend a
   presentation decision into the data contract.
3. `position` is currently write-mostly and unobservable on any surface (D-008).
   This endpoint makes it observable again, which is a small argument for its
   continued existence — relevant to the retirement question D-008 parked.

Kova will see two surfaces ordering modalities differently and should **not**
flag it. It is specified, and §8 test 6 pins it.

### 4.5 Decision (D-033): timestamps are ISO 8601 with an explicit `Z`

All three timestamp columns are stored **naive but genuinely UTC** — verified:
`_utcnow()` (`app/services/auth_service.py:69-71`) returns
`datetime.now(datetime.UTC).replace(tzinfo=None)`, and the `server_default` is
`func.now()`, which SQLite evaluates as UTC.

A bare `.isoformat()` therefore emits `2026-08-10T10:54:19` — a timestamp with
no zone, which a machine consumer cannot interpret without out-of-band
knowledge. Specified: emit `.isoformat() + "Z"`, giving
`2026-08-10T10:54:19Z` (or `...T10:54:19.690936Z` when microseconds are
present — both are valid RFC 3339 and both parse with
`datetime.fromisoformat` on Python 3.11).

This is a **deliberate departure** from the bare `.isoformat()` used across
`/admin/keys` (`app/routes/admin.py:82-88`, `:177-181`) and
`PUT .../hidden` (`:499`). Justified: those are consumed by this app's own
JavaScript, which renders them locally; this one is consumed by third-party
agents with no shared context. Do **not** retrofit the admin routes in this
card — that is a separate, purely cosmetic change with its own test churn.
Kova should treat the divergence as intended and scoped.

`hidden_at` is `null`, not `"null"` or `""`, when the model is visible.

### 4.6 `hidden` field naming

`hidden` (bool) and `hidden_at` (timestamp), exactly matching the response of
`PUT /admin/models/<id>/hidden` (D-022), which returns
`{"id", "name", "hidden", "hidden_at"}`. An agent that hides a model and then
lists models sees the same two field names meaning the same two things. No new
vocabulary is invented.

### 4.7 Ordering

`ORDER BY sort_name, name` — the D-017 hybrid, with raw `name` as the
mandatory secondary term (without it `~deepseek/tie` vs `deepseek/tie` has no
deterministic order and no test can pin the pair).

This is the same ordering as `/` (`app/routes/main.py:23`) and
`/admin/models/manage` (`app/routes/admin.py:244`), satisfying D-016: two views
of the same data must not order differently. Ordering happens in SQL, per the
standing rule from `_research/2607251644_models-listing-spec.md:167` (do not
re-sort in the route).

Standing trap, third recording (D-010, D-018): SQLite's binary collation is
case-sensitive, so `Zebra/x` sorts before `anthropic/x`. Unchanged behaviour,
out of scope, do not "fix" it here.

---

## 5. Errors

| Condition | Status | Body | Headers |
|---|---|---|---|
| Invalid `include_hidden` value | `400` | `{"error": "'include_hidden' must be 'true' or 'false'"}` | `Cache-Control: no-store` |
| Non-GET method | `405` | Flask default HTML | Flask default |
| Empty database | `200` | `{"models": []}` | normal success headers |
| Unknown query parameter | `200` | normal | normal |

**Error bodies use `{"error": "<message>"}`**, matching `_admin_error`
(`app/routes/admin.py:39-42`) and every other JSON error in the app. Dale should
add a small module-local `_api_error(status, message)` helper in
`app/routes/api.py` rather than importing `_admin_error` across blueprints — the
admin helper is private to that module and its `no-store` default is right for
`/admin/*` for a different reason.

**Error responses carry `Cache-Control: no-store`** and must **not** carry the
CORS or `max-age` headers. Caching a 400 for 60 seconds would make a client's
corrected retry return the stale error from its own cache.

**An empty database is `200` with an empty array, not `404`** — the collection
resource exists and is empty. This is D-029's ruling for modalities applied
unchanged; the bare `client` fixture (`tests/conftest.py:22-25`) is exactly this
state and costs no new fixture to test.

**A `?include_hidden=true` request against a database where every model is
hidden returns all of them.** A request without the parameter against that same
database returns `{"models": []}` — a `200`, not an error. Do not special-case
it.

---

## 6. Required fix: `AiModel.is_hidden` is broken as a SQL expression

**This is a real, shipped defect, not a style note.** Found while validating
this endpoint's query, reproduced in isolation.

### The failure

`app/models/ai_model.py:178-192`:

```python
@hybrid_property
def is_hidden(self) -> bool: ...

@is_hidden.expression          # ← wrong decorator form
@classmethod
def _is_hidden_expression(cls): ...
```

`select(AiModel).where(AiModel.is_hidden)` raises:

```
sqlalchemy.exc.InvalidRequestError: When interpreting attribute
"AiModel.is_hidden" as a SQL expression, expected __clause_element__() to
return a ClauseElement object, got: True
```

Under SQLAlchemy 2.0, the bare `@<hybrid>.expression` form does not replace the
Python getter for class-level access; the class-level attribute still evaluates
the instance getter, `self.hidden_at is not None` against the class returns
`True`, and SQLAlchemy is handed a Python `bool` where it expected a clause.
Reproduced against SQLAlchemy 2.0.51 in a minimal two-class script: the
`.expression` form fails, the `.inplace.expression` form compiles to
`WHERE f.hidden_at IS NOT NULL`.

### Why it has gone unnoticed

`is_hidden` is used in exactly five places, all **instance-level** (verified by
grep across the repo): `tests/test_models.py:90-91` and four Jinja references in
`app/templates/admin/models.html`. Instance access takes the Python getter and
works correctly. **No code has ever used it in a query** — `app/routes/main.py:18`
uses `AiModel.hidden_at.is_(None)` directly. So the hybrid works for every
current caller and fails for the one thing D-020 says it exists for:

> Plus an `is_hidden` hybrid property mirroring the existing `sort_name`
> pattern (D-017), so the predicate is defined once.

### The fix

One line: `@is_hidden.expression` → `@is_hidden.inplace.expression`. This is
the form `sort_name` already uses two definitions above
(`app/models/ai_model.py:172`), which is why `sort_name` works in `ORDER BY` and
`is_hidden` does not. **`sort_name` is the only other hybrid on the model and it
is already correct** — checked, so this is the whole class of the bug, not one
instance of it.

### Scope ruling

**In scope for t_fa898e85.** It is one line, it is on the direct path of this
card's query, and leaving it means either shipping a workaround or leaving a
booby trap for the next author. Dale must:

1. Apply the one-line fix.
2. **Use `AiModel.is_hidden` in the endpoint's `WHERE`**, not
   `hidden_at.is_(None)` — the point of the fix is that the predicate has one
   definition. (Filtering is `.where(~AiModel.is_hidden)` for the default case;
   no `WHERE` at all when `include_hidden=true`.)
3. Add the unit test in §8 test 12 pinning the *expression*, so a regression
   fails loudly instead of waiting for the next query author.

`app/routes/main.py:18` may keep `hidden_at.is_(None)` — changing it is
behaviour-neutral churn on a line Kova already approved. Not required, not
forbidden. If Dale changes it, `tests/test_models_listing.py:76-92`'s
3-query assertion must still pass.

---

## 7. Security review

### 7.1 What this endpoint exposes, and to whom

Everything in §4.3, to anyone, unauthenticated. Assessed field by field:

- `name`, `price_in`, `price_out`, `context_tokens`, `input_content`,
  `output_content` — **already public** on `/` (D-004, CONFIRMED: "Listing on
  `/` must not be sensitive and should be freely shared").
- `id` — a surrogate integer. It is the address for two write endpoints, both of
  which remain gated (`administrator` for create/hide, `updater` for edit).
  Knowing an id grants nothing without a token.
- `hidden`, `hidden_at`, `created_at`, `updated_at` — operational metadata.
  See §7.2.
- **No auth data of any kind.** No key names, no `kid`, no roles, no
  `last_used_at`, no `AuthEvent` rows. The endpoint touches `ai_models`,
  `modalities` and the two association tables, and nothing else. Kova should
  verify the query and the serializer reference no model from
  `app/models/auth.py`.

### 7.2 Hidden state is already public — verified, and this matters

Running the app unauthenticated:

```
GET /admin/models/manage  → 200, 31023 bytes
  contains 'anthropic/claude-opus-4.8'         → True
  after hiding that model, still contains it   → True
  contains 'data-hidden'                       → True
GET /                     → hidden model absent → True
```

`models_page` (`app/routes/admin.py:235-248`) has **no** `@require_role`. It
server-renders every model — hidden ones included, with a `data-hidden`
attribute and a literal `Hidden` / `Visible` cell (`admin/models.html:38-47`) —
to any anonymous caller. The docstring calls it a "public shell; data is
protected via `@require_role`", which is true of the *mutation* endpoints the
page calls and false of the model rows the page itself renders.

**Consequence for this card:** `include_hidden=true` discloses nothing that is
not already served in HTML at a guessable URL. The endpoint does not widen the
public surface; it makes an existing disclosure machine-readable. That is the
correct security finding and it is why §4.3 exposes `hidden` without
qualification.

**This is an existing condition and it is out of scope here.** It was not
introduced by this work and fixing it would change an unrelated page's auth
behaviour. But it should not be discovered a third time:

> **Recommended follow-up card for Suki/Erik (not created by me — it is a policy
> question, not an implementation one):** decide whether
> `GET /admin/models/manage` rendering full model data (including hidden rows)
> to anonymous callers is intended. If yes, the docstring at
> `app/routes/admin.py:237` is misleading and should say so plainly. If no, it
> needs a gate — and that is a D-004-adjacent operator decision about what is
> public, not a bug fix an agent should take unilaterally.

I am explicitly **not** filing this as §B of this document: it does not block
this endpoint, whose disclosure is authorised by the operator's own words on the
root card either way.

### 7.3 CORS

Same analysis as D-028b, which holds unchanged because the data is public and
the credential model has not moved:

- `Access-Control-Allow-Credentials` is **not** set, and `*` is incompatible
  with it by specification, so a cross-origin caller cannot attach credentials.
- Auth is a bearer token in `sessionStorage`, not a cookie — there is no ambient
  credential for a cross-origin request to ride on.
- `GET`-only with simple headers, so no preflight and no `OPTIONS` handler.

**Binding, and this is now the second route with the header:**
`Access-Control-Allow-Origin` goes on the `/api/v1/models` **success** response
only. It must **not** be applied via `after_request`, via a blueprint-level
hook, via `flask-cors`, or to any `/admin/*` or `/auth/*` route. With two routes
now needing the same header, factoring it into an app-wide hook is the
plausible-looking wrong implementation, and it would open the authenticated
surface. If Dale wants to avoid duplication, the correct shape is a small
module-local helper in `app/routes/api.py` that both handlers call — not a hook.
§8 test 11 is the regression guard and is **not optional**.

### 7.4 Rate limiting and payload size

There is no rate limiting anywhere in this application today, on any route,
authenticated or not. This endpoint returns 22 rows (≈6 KB of JSON), bounded by
the number of models an administrator has manually created. Adding a rate
limiter here alone would be inconsistent and would not protect the eleven other
unauthenticated-reachable routes. Recorded as an assumption (§A item 7), not
addressed.

---

## 8. Tests Dale must write

New file `tests/test_api_models.py`, following the structure of
`tests/test_api_modalities.py`. The `client`, `seeded_client` and `seeded_app`
fixtures (`tests/conftest.py`) cover every case with no new fixture work.

Dale will need a small local helper to hide a model (set `hidden_at` and
commit inside an app context) — `PUT /admin/models/<id>/hidden` requires an
administrator token, so direct ORM manipulation is the cheaper setup, matching
how `tests/test_models.py:67-91` does it.

1. `test_returns_all_visible_models` — `seeded_client`, no params. Asserts `200`
   and exactly 22 objects, none with `hidden: true`.
2. `test_excludes_hidden_by_default` — hide one model, then no params. Asserts
   21 objects and that the hidden model's name is absent. **This is the card's
   core behaviour.**
3. `test_include_hidden_true_returns_all` — hide one, `?include_hidden=true`.
   Asserts 22 objects and that the hidden one is present with `hidden: true` and
   a non-null `hidden_at`.
4. `test_include_hidden_false_matches_default` — asserts the
   `?include_hidden=false` body is byte-identical to the no-parameter body.
5. `test_model_object_shape` — asserts one object's keys are **exactly** the
   eleven in §4.3 (set equality, not a subset check — this catches an
   accidentally leaked field), and asserts `context_tokens` is an `int` equal to
   the raw seeded value, not a `"200K"` string.
6. `test_modality_lists_preserve_persisted_order` — asserts
   `anthropic/claude-haiku-4.5` returns `input_content ==
   ["Text", "Images", "Files"]`, i.e. **not** alphabetical. Pins D-032.
7. `test_ordering_matches_dashboard` — asserts the returned name sequence equals
   the names in `sort_name, name` order, including that a `~`-prefixed name
   sorts with its siblings. Pins D-016/D-017 agreement.
8. `test_timestamps_are_utc_iso8601` — asserts `created_at` and `updated_at` end
   with `"Z"` and parse with `datetime.fromisoformat`; asserts `hidden_at` is
   `None` for a visible model and a `Z`-suffixed string for a hidden one.
9. `test_invalid_include_hidden_returns_400` — parametrized over
   `["1", "0", "yes", "no", "on", "", "TRUE1", "maybe"]`. Asserts `400`, an
   `error` key, and `Cache-Control: no-store`. **`"1"` and `"0"` must be in this
   list** — they are the values a lenient implementation would silently accept.
10. `test_case_insensitive_boolean_accepted` — `TRUE`, `True`, `FALSE`, `False`
    all `200` with the correct filtering.
11. `test_sets_cache_and_cors_headers_and_admin_unaffected` — asserts the
    success response has `Cache-Control: public, max-age=60` and
    `Access-Control-Allow-Origin: *`; **and** that a `/admin/*` JSON response
    still has `Cache-Control: no-store` and **no** `Access-Control-Allow-Origin`.
    This is the test that catches an app-wide CORS hook (§7.3). Not optional.
12. `test_is_hidden_usable_as_sql_expression` — in `tests/test_models.py`,
    beside the existing `test_is_hidden_reflects_hidden_at`. Executes
    `db.session.scalars(select(AiModel).where(AiModel.is_hidden))` and asserts
    it returns exactly the hidden rows. **This test fails on `main` today** —
    red before, green after. Pins §6.
13. `test_empty_database_returns_empty_list` — bare `client`, asserts `200` and
    `{"models": []}` both with and without `?include_hidden=true`.
14. `test_all_hidden_returns_empty_list` — hide every model, no params, asserts
    `200` and `{"models": []}`; then `?include_hidden=true` returns all 22.
15. `test_requires_no_authentication` — no header, `200`.
16. `test_invalid_token_still_returns_200` — `Authorization: Bearer garbage`,
    asserts `200` and a body identical to the unauthenticated one. Guards
    against a future global auth hook capturing the endpoint.
17. `test_authenticated_response_is_identical` — a real key via
    `create_api_key(...)` (pattern at `tests/test_admin_models.py:8`), asserts
    the body equals the unauthenticated body. A public endpoint must not become
    role-sniffing.
18. `test_rejects_post` — `405`.
19. `test_duplicate_parameter_uses_first_value` — 
    `?include_hidden=true&include_hidden=false` behaves as `true`. Pins §3.2.
20. `test_uses_bounded_query_count` — the `before_cursor_execute` counter
    harness from `tests/test_models_listing.py:76-92`. Asserts **exactly 3**
    queries for both `include_hidden` values. Verified achievable. Unlike the
    modalities endpoint, this one has real relationship loading and a genuine
    N+1 risk if the `selectinload` options are dropped.

**The full existing suite must pass unchanged.** Nothing in this card alters an
existing contract. If `tests/test_models_listing.py` or
`tests/test_admin_models.py` breaks, something outside the specified scope was
touched.

---

## 9. Documentation

README's `## Public API` section (`README.md:77`) already exists from the
modalities work. This card:

1. Adds a row to the existing table:

   | Method | Path | Auth | Description |
   |---|---|---|---|
   | GET | `/api/v1/models` | None | All models with pricing, context, and modality details |

2. Adds a subsection after the modalities example with: the `include_hidden`
   parameter and its exact accepted values, a `curl` example, a trimmed sample
   response, and the 400 case.
3. States explicitly that `id` is the value to use in
   `PATCH /admin/models/<id>`, and that `input_content` / `output_content`
   values are the exact tokens accepted by the write paths — closing the
   read→write loop this endpoint exists to enable.
4. Notes the D-024 interaction, which is otherwise a genuine agent trap:
   **a hidden model still occupies the unique name index.** An agent that lists
   with the default filter, does not see `openai/gpt-6`, and `POST`s it will get
   a `409` it cannot explain. The fix is `?include_hidden=true`. This sentence
   is worth more to a consumer than the rest of the section.

`## Project Structure` needs no change — `app/routes/api.py` was added there by
the modalities card.

---

## 10. Implementation checklist for Dale

**Base branch:** this spec describes `999f495`, which is on
`feat/public-modalities-endpoint` and **not yet merged to `main`** (PR #13).
`app/routes/api.py` does not exist on `main`. Dale's branch must contain
`999f495` — branch from `main` if PR #13 has merged by then, otherwise from
`feat/public-modalities-endpoint`. Check before branching; do not assume.

1. `app/models/ai_model.py:188` — `@is_hidden.expression` →
   `@is_hidden.inplace.expression`. One line. (§6)
2. `app/routes/api.py` — add `list_models()` on the existing `api_bp`:
   parse and validate `include_hidden`, build the query with the `selectinload`
   options and `ORDER BY sort_name, name`, apply `.where(~AiModel.is_hidden)`
   unless including, serialize per §4.3, set the two success headers.
3. `app/routes/api.py` — add a module-local `_api_error(status, message)`
   returning `{"error": ...}` with `Cache-Control: no-store`. (§5)
4. `tests/test_api_models.py` — tests 1–11 and 13–20.
5. `tests/test_models.py` — test 12, beside the existing `is_hidden` test.
6. `README.md` — §9.
7. Run the full suite. Commit `_research/2608101058_public-models-listing-endpoint-spec.md`
   and the `_research/DECISION.md` additions alongside the code (AGENTS.md §4).

**Do not:** add pagination, add a `count` field, add `flask-cors`, add an
`after_request` hook, use `type=bool`, use `format_price` / `format_context`,
sort modality lists, gate the route, touch `/admin/models/manage`, or change
any existing endpoint's headers.

---

## 11. Review criteria for Kova

1. Route is exactly `GET /api/v1/models` on the existing `api_bp`, with
   `methods=["GET"]` declared explicitly. Not `/api/publish/models`.
2. **No `@require_role`** on the route, and no import of it into the handler.
   `401`/`403` are unreachable.
3. `include_hidden` parsing accepts only `true`/`false` case-insensitively.
   **`type=bool` must not appear anywhere.** `"1"` and `"0"` return 400.
4. Default (parameter absent) **excludes** hidden models.
5. Response is `{"models": [...]}`, each object having exactly the eleven fields
   of §4.3 — no more, no fewer, no conditional keys.
6. `context_tokens` is a raw integer; no `format_context` / `format_price`.
7. Modality lists are **not** alphabetized (D-032). This is intended; do not
   file it as an inconsistency with D-008.
8. Timestamps carry the `Z` suffix (D-033); `hidden_at` is `null` when visible.
   `/admin/*` timestamp formats are **unchanged**.
9. `Cache-Control: public, max-age=60` and `Access-Control-Allow-Origin: *` on
   the **success** response only. Error responses carry `no-store` and neither
   of those headers.
10. **No app-wide CORS**: no `after_request`, no `flask-cors` in
    `requirements.txt` / `pyproject.toml`, no blueprint-level hook. `/admin/*`
    still returns `no-store` and no CORS header — assert it, don't eyeball it.
11. `is_hidden` fix is `.inplace.expression`, and the endpoint's `WHERE` uses
    the hybrid rather than re-deriving `hidden_at.is_(None)`.
12. Query count is exactly 3 for both filter values.
13. No auth-model data (`ApiKey`, `AuthSession`, `AuthEvent`, `RecoveryKey`) is
    imported or serialized by the route.
14. No new Alembic revision. Head stays `453c7603f37a`.
15. Full existing suite passes untouched.
16. README table row and `include_hidden` documentation present, including the
    D-024 hidden-name-collision note.

---

## §A — Assumptions taken

Each is in force, each has an entry in `_research/DECISION.md`, each states its
reversal cost. Dale proceeds against these without further consultation.

1. **Path is `GET /api/v1/models`, overriding the card's `/api/publish/models`
   suggestion** (D-030a). D-025 already fixed `/api/v1/` as the public prefix
   and it is shipped at `999f495`. *Reversal cost: low now, rising.* A rename
   before any agent consumes it is one line; after adoption it is a breaking
   change for every external caller — the exact cost D-013 and D-014 told us to
   price in advance.

2. **Filter is `?include_hidden=true|false`, strict, case-insensitive,
   defaulting to `false`** (D-030b). `1`/`0`/`yes` are 400s, consistent with
   D-022's strict-boolean precedent. *Reversal cost: widening the accepted
   value set later is purely additive and breaks no client. Changing the
   default, or renaming the parameter, is breaking once consumed.*

3. **Response is `{"models": [...]}` — an envelope, not a bare array —
   overriding Dale's card body** (D-031). *Reversal cost: additive keys are
   free; unwrapping to a bare array later is breaking.* We are on the
   reversible side.

4. **`id` is included, deliberately diverging from D-026's no-`id` ruling for
   modalities** (D-031). All three of D-026's reasons invert for models: ids are
   persisted and stable, both write endpoints address models by id, and the
   read→write loop is this card's entire purpose. *Reversal cost: removing it
   later is breaking.* This one is genuinely hard to reverse — but omitting it
   makes the endpoint unusable for its stated purpose.

5. **Modality lists come back in persisted `position` order, not alphabetical**
   (D-032), diverging from the HTML surfaces (D-008). *Reversal cost: trivial
   mechanically (one `sorted()`), but it would silently reorder association rows
   on any client that round-trips through `PATCH`.* Raise it as its own card if
   ever reconsidered.

6. **Timestamps are ISO 8601 with an explicit `Z`; `/admin/*` formats are left
   alone** (D-033). *Reversal cost: nil for this endpoint. Retrofitting the
   admin routes for consistency is a separate cosmetic card.*

7. **`Cache-Control: public, max-age=60`, hand-written
   `Access-Control-Allow-Origin: *` scoped to this route, no `flask-cors`, no
   rate limiting** (D-034). 60s rather than modalities' 300s because model data
   is operator-mutable and an agent's write should become visible promptly.
   *Reversal cost: nil — change or delete a header.*

8. **No pagination, no `count`, no sort/field-selection parameters** (D-035).
   22 rows, ≈6 KB. *Reversal cost: additive — any parameter added later defaults
   to current behaviour and breaks nothing.* If the table ever reaches a few
   hundred rows, revisit; the envelope in §4.1 is what makes that additive.

9. **The `AiModel.is_hidden` expression fix is in scope for this card** (D-036).
   One line, on this endpoint's direct path, with a red-before/green-after test.
   *Reversal cost: n/a — it is a defect fix, not a choice.*

10. **`GET /admin/models/manage` serving full model data (hidden rows included)
    to anonymous callers is treated as an existing, out-of-scope condition.**
    Verified by execution (§7.2). It is why this endpoint's `hidden` field
    discloses nothing new. *Reversal cost: n/a here — but it is an unresolved
    policy question and §7.2 recommends a separate card for Erik. Do not fix it
    inside this one.*

---

## §B — Decisions required (BLOCKING)

**None. This document hands off directly to t_fa898e85.**

Per AGENTS.md §2, the emptiness of this section is justified explicitly against
each of the five tests rather than asserted:

- **Database schema or migration:** no change. No new table, no new column, no
  Alembic revision; head stays `453c7603f37a`. The only model-file edit is a
  decorator form on an existing hybrid property (§6), which emits no DDL.
- **Role / permission model:** unchanged. No new role, no new gate, no change to
  any existing gate. The endpoint is ungated, and that is not an agent
  assumption — the operator wrote it on the root card ("The endpoint does not
  need authentication"), consistent with D-004's CONFIRMED ruling that model
  listing data is public.
- **API request or response contract:** this document *defines* a new contract,
  it does not change an existing one. No shipped endpoint's request or response
  shape is altered. The two places where I overrode the card's literal wording
  (path, and array-vs-envelope) are both governed by standing decisions —
  D-025 for the prefix, D-026 for the envelope — so choosing otherwise would
  contradict prior work rather than resolve an open question.
- **The shape of a test pinned as intended behaviour:** every test in §8 pins
  behaviour that follows from an existing confirmed or assumed decision
  (D-016/D-017 ordering, D-021 default visibility, D-022 field naming and strict
  booleans, D-024 name collision, D-028 header scoping) or from a verified fact
  (the query count, the `is_hidden` defect). None of them pins a novel policy
  choice an operator would plausibly want to make differently.
- **Anything already shipped on a branch with an open PR:** PR #13
  (`feat/public-modalities-endpoint`) is open and this card builds on it, but
  changes nothing it shipped — no edit to `list_modalities`, its headers, or
  `app/data/modalities.py`. §10 records the base-branch dependency so Dale does
  not branch from a `main` that lacks `app/routes/api.py`.

The one genuinely contestable call in this document is the hidden-state
disclosure in §7.2. It is not filed as blocking because the operator's own words
on the root card — *"The endpoint should be able to filter out or keep models
that are hidden"* — are an explicit instruction that hidden models be retrievable
through this endpoint, and because §7.2 verifies the same data is already served
unauthenticated as HTML. The related question that *is* open (whether
`/admin/models/manage` should be public at all) is a pre-existing condition
outside this card's scope, and §7.2 recommends it as a separate card rather than
holding this one hostage to it.
