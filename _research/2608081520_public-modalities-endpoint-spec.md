# Spec: Public modalities discovery endpoint

**Card:** t_4ce58bc1 — Research and design the public modalities endpoint
**Root card:** t_18fefad3 — Add public REST endpoint to get all possible modalities
**Implements into:** t_8e6dd729 (Dale), reviewed by t_b2839780 (Kova)
**Author:** chip (architect)
**Date:** 2026-08-08
**Code state described:** `main` @ `638ca3f`, Alembic head `453c7603f37a`, version 0.2.0

---

## 1. Summary / Recommendation

Add one route:

```
GET /api/v1/modalities   →   200   {"modalities": [{"name": "Audio"}, ...]}
```

Unauthenticated. Served from the `modalities` table, intersected with the
canonical allow-list, ordered by name. Cacheable for 5 minutes, CORS-open.

Three things make this more than a two-line route, and they are the substance of
this document:

1. **The assignable vocabulary is currently defined in three places.** The write
   path validates against a Python constant and *then* resolves against a
   database table. An endpoint that advertises the wrong one of those will
   promise modalities that `400` on use. §3 fixes this.
2. **The prefix decision pre-commits the public write API's home**, which D-013
   (CONFIRMED) explicitly told us to anticipate now rather than version around
   later. §4 settles it, and settles Erik's "how would you sign post the
   difference" question in a way that survives the arrival of authenticated
   public routes.
3. **Surrogate modality ids are not stable across deployments.** Verified by
   execution. §5 is why `id` is not in the response despite the card asking for
   it.

**§B is empty. This document hands off directly to Dale.** Justification in §11.

---

## 2. Where modalities actually live today

Four surfaces, verified by reading:

| # | Location | Content | Role |
|---|---|---|---|
| 1 | `app/commands.py:37` | `ALLOWED_MODALITIES = ["Text", "Images", "Files", "Videos", "Audio"]` (list) | Seed source. `_upsert_modalities()` (`app/commands.py:123-133`) inserts each name into the `modalities` table if absent. Idempotent, never deletes. |
| 2 | `app/routes/admin.py:24` | `ALLOWED_MODALITIES = frozenset({...})` (frozenset, same five values) | Write-path validation. `_validate_model_values` rejects anything outside it (`app/routes/admin.py:306-308`). Also feeds the add/edit checkboxes via `sorted(ALLOWED_MODALITIES)` (`:246`). |
| 3 | `modalities` table | `id INTEGER PK`, `name VARCHAR(32) NOT NULL UNIQUE` (`app/models/ai_model.py:45-56`) | Storage. `_modality_rows` (`app/routes/admin.py:313-326`) resolves submitted names to rows and `400`s on any name with no row. |
| 4 | `tests/test_models_listing.py:12` | A third copy of the same five values | Test assertion only. |

**The effective assignable set is the intersection of (2) and (3).** A name must
pass `issubset(ALLOWED_MODALITIES)` *and* have a table row. Neither source alone
is a truthful answer to "what may I assign?":

- Serve only the constant → no `id`, and a name whose row is missing would be
  advertised then rejected by `_modality_rows` with `400 Unknown modality: X`.
- Serve only the table → a hand-inserted row not in the constant would be
  advertised then rejected by `_validate_model_values` with
  `400 '<field>' contains invalid modality: X`.

Divergence is not hypothetical in one direction: `_upsert_modalities()` inserts
but never deletes, so retiring a modality from the constant in a future change
leaves an orphan row in every existing database. The endpoint must not advertise
it.

### Verified seed behaviour

```
modalities before seed: []
modalities after  seed: [(5,'Audio'), (3,'Files'), (2,'Images'), (1,'Text'), (4,'Videos')]
```

Two facts fall out, both load-bearing below:

- **Ids follow `commands.ALLOWED_MODALITIES` insertion order, not alphabetical
  order.** They are an artefact of the list literal at `app/commands.py:37`.
- **A migrated-but-unseeded database has zero modality rows.** The empty-list
  case in §7 is reachable, not theoretical.

---

## 3. Source of truth: collapse the constant, serve the table

**Decision (D-027).** Introduce one canonical definition and have both existing
call sites import it. Serve the endpoint from the `modalities` table filtered to
that allow-list.

New module `app/data/modalities.py`:

- Exports `ALLOWED_MODALITIES: tuple[str, ...]` with the five values **in the
  current `app/commands.py:37` order** — `Text, Images, Files, Videos, Audio`.
  Order is preserved deliberately: it determines seed insertion order and
  therefore existing row ids. Re-ordering the literal would renumber ids on
  fresh installs for no benefit.
- `app/data/` is the right home: it already holds seed vocabulary
  (`app/data/sample_models.py`), and `app/commands.py:13` already imports from
  it, so the import direction is established and creates no cycle.

Call-site changes, both name-preserving so nothing else moves:

- `app/commands.py:37` — replace the literal with an import. `_upsert_modalities`
  iterates it unchanged; a tuple iterates identically to a list.
- `app/routes/admin.py:24` — replace the literal with
  `ALLOWED_MODALITIES = frozenset(_ALLOWED_MODALITIES)`. The module-level name
  and its `frozenset` type are unchanged, so `.issubset` (`:306`), the set
  difference (`:307`) and `sorted(...)` (`:246`) all behave identically and
  `tests/test_admin_models.py` needs no edit.

`tests/test_models_listing.py:12` is **left alone.** A test asserting against an
independently written literal is doing its job; importing the constant it is
checking would make the assertion vacuous.

### The query

```
SELECT id, name FROM modalities
WHERE name IN (<allow-list>)
ORDER BY name
```

One statement, five rows, no joins, no `selectinload`, no N+1. Ordering happens
in SQL, matching the repo convention that ordering lives in the query
(`_research/2607251644_models-listing-spec.md:167`, upheld by D-008 and D-015).

**Ordering caveat, inherited from D-010:** SQLite's default binary collation is
case-sensitive. It produces correct alphabetical order here only because all
five names are capitalised single-case. If the vocabulary ever gains a
lowercase name, this needs `COLLATE NOCASE` — and so does the Jinja `| sort` at
`app/templates/index.html:28-29`. Same standing trap, recorded once more so it
is not rediscovered a third time.

---

## 4. Path, prefix, and how the auth boundary is signposted

Erik's question on the root card, quoted in full because it is the interesting
part of this card:

> I don't think this endpoint needs authentication. But it may be awkward to
> have some REST endpoints that do not require authentication and some that do
> and how would you sign post the difference. Do what provides the better user
> experience.

### The trap in the obvious answer

The tempting signpost is *prefix by auth class*: "everything under `/api` is
public, everything under `/admin` needs a token." That reading is even
accidentally true of the app today (`/` and `/health` public; `/admin/*` and
`/auth/session DELETE` gated).

It is the wrong rule, and D-013 (CONFIRMED) is why. Erik's rationale there:

> a known use case (known to the operator at least) will need to be implemented
> eventually and it is similar to this effort and it may impact choices made now
> (e.g., choice of route names)

That known use case is the public, agent-facing **write** API — the thing
`/admin/models/<id>` PATCH is currently standing in for. It will need
authentication, and it will need to live beside this endpoint, because an agent
that discovers modalities and then submits a model is one client. The moment it
lands, "everything under `/api` is public" is false, and a signpost that turns
into a lie is worse than no signpost.

### Decision (D-025): prefix by audience, signpost auth per endpoint

```
/api/v1/**    the public, agent-facing REST API — mixed auth, by design
/admin/**     the dashboard's own control-plane JSON — authenticated
/auth/**      credential exchange
/  /health    public HTML and liveness
```

The prefix answers "who is this for", which is stable. Authentication is
signposted three ways, all of which the codebase already supports:

1. **HTTP itself.** A protected endpoint called without credentials returns
   `401` with `WWW-Authenticate: Bearer` — `_auth_error` already emits that
   header (`app/auth/decorators.py:71-73`). This is the machine-readable
   signpost, it costs nothing, and it is the one every HTTP client already
   understands. An agent does not need to be told which endpoints are public;
   it needs the ones that are not to say so correctly. They already do.
2. **Documentation.** README gains an API table with an explicit **Auth**
   column (§9). Every future `/api/v1/` route adds a row. This is the human
   signpost and it is the deliverable that actually answers Erik's question.
3. **Cache semantics as a corroborating tell.** Public reads are cacheable;
   every authenticated response in this app sets `Cache-Control: no-store`
   (`app/routes/admin.py:40`, `:93`, `:155`, and eight more). §6 keeps that
   invariant clean in both directions.

### Version segment

`/api/v1/`, not `/api/`. D-013 and D-014 both flag the same failure mode — a
contract that external callers adopt becomes expensive to change. A version
segment chosen now costs one path component and nothing else; retrofitting one
after agents have hardcoded `/api/modalities` means two inconsistent schemes
coexisting forever. Take the free option.

### Blueprint

New `app/routes/api.py`:

- `api_bp = Blueprint("api", __name__, url_prefix="/api/v1")`
- Registered in `create_app` alongside the other three
  (`app/__init__.py:48-54`).

Note for the reviewer: this **reinstates a blueprint that was deliberately
deleted.** `_research/2607231705_api-status-removal-plan.md` removed `api_bp`
along with `/api/status`, and its §4 "Option B" kept the empty blueprint as
"a mount point for imminent future JSON API routes", recommending against it
"unless an API route is already planned for the next sprint." That condition is
now met. This is Option B arriving on schedule, not a reversal.

`/api/status` is **not** resurrected. `/health` remains the canonical liveness
endpoint per `_research/2607230701_health-endpoint-contract.md`.

Rejected alternatives:

- `/modalities` on `main_bp` — no room to grow, and puts an agent-facing JSON
  route in the same namespace as the HTML dashboard.
- `/admin/modalities` — a public endpoint under an authenticated prefix is
  precisely the mixed signal Erik asked us to avoid.

---

## 5. Response contract

### Success

```
GET /api/v1/modalities
```

```
200 OK
Content-Type: application/json
Cache-Control: public, max-age=300
Access-Control-Allow-Origin: *
```

```json
{
  "modalities": [
    {"name": "Audio"},
    {"name": "Files"},
    {"name": "Images"},
    {"name": "Text"},
    {"name": "Videos"}
  ]
}
```

### Envelope

An object with a `modalities` key, not a bare top-level array. Matches the
existing convention — `GET /admin/keys` returns `{"keys": [...]}`
(`app/routes/admin.py:92`) — and leaves room for siblings without a breaking
change.

### Decision (D-026): no `id` field

The card body asks for "modality objects with id and name". **Recommend
against, and this spec omits `id`.** Three reasons, in order of weight:

1. **The ids are not stable across deployments.** Verified in §2: they are
   assigned by insertion order from the list literal at `app/commands.py:37`.
   Two databases seeded from different code revisions, or one restored from a
   partial dump, can disagree. Publishing an identifier in a discovery endpoint
   is a promise that it means the same thing tomorrow and on the next host. We
   cannot keep that promise, so we should not make it.
2. **Nothing accepts an id.** Every write path in the app addresses modalities
   **by name** — `input_content: ["Text"]`, validated by name
   (`app/routes/admin.py:306`) and resolved by name
   (`app/routes/admin.py:318-322`). Returning an id next to a name in an
   endpoint whose entire purpose is "here is what you may submit" invites a
   client to submit the id, which `400`s. The response should contain the
   token the client is meant to send, and only that token.
3. **It is an internal surrogate key.** Exposing it creates a second addressing
   scheme with no consumer, that we would then be obliged to keep working.

**Objects, not bare strings.** `[{"name": "Audio"}]` over `["Audio"]` costs nine
characters per element and buys the ability to add a field — a display label, a
deprecation flag — without a `v2`. Same reasoning as the version segment: take
the cheap forward option now.

### Ordering

Alphabetical by name, from SQL (§3). Deterministic, so tests can pin the exact
array. Consistent with every other modality-bearing surface: `/`
(`app/templates/index.html:28-29`, D-008), the manage page
(`app/templates/admin/models.html:40-41`), and the checkbox lists
(`app/routes/admin.py:246`, D-011).

### Errors

There are none to design. No path parameters, no query parameters, no request
body, no database state that can fail a lookup. The only non-200 responses are
Flask's automatic `405` (§7) and a `500` from an unreachable database, which is
not this endpoint's concern.

**No input validation is required, because there is no input.** Dale should not
invent query parameters — no `?include_deprecated`, no `?format`. Kova should
treat any added parameter as scope creep and reject it.

---

## 6. Caching and CORS

### Decision (D-028a): `Cache-Control: public, max-age=300`

The response is a five-element constant that changes only when
`app/data/modalities.py` changes, which requires a code change and a redeploy.
An agent polling this endpoint before every model submission should be served
from its own HTTP cache. Five minutes is well inside the deploy cycle.

This is a deliberate departure from the `no-store` used on every `/admin/*`
response, and the departure is the point: `no-store` there is correct because
those responses are authenticated and per-principal. **Kova should verify that
`no-store` was not copy-pasted onto this route**, and equally that no
`/admin/*` route acquired a cacheable header.

### Decision (D-028b): `Access-Control-Allow-Origin: *`, hand-written, no dependency

One header on this one response. Explicitly **not** `flask-cors` — adding a
production dependency (`requirements.txt`, `pyproject.toml:12-18`) for a single
static header is not justified.

Safety analysis, since this is the one line in the spec with a security
surface:

- The response contains a hard-coded five-element vocabulary. There is no
  per-user, per-principal, or otherwise sensitive content to leak.
- `Access-Control-Allow-Credentials` is **not** set, and `*` is incompatible
  with it by specification. A cross-origin caller therefore cannot attach
  credentials, so this cannot become a confused-deputy read of authenticated
  data.
- The app's auth is a bearer token in `sessionStorage`, not a cookie, so there
  is no ambient credential for a cross-origin request to ride on regardless.
- `GET` only, so no preflight is triggered and no `OPTIONS` handler is needed.

**Binding constraint: this header goes on the `/api/v1/modalities` response
only.** It must not be applied app-wide, via an `after_request` hook, or to any
`/admin/*` or `/auth/*` route. Kova should check this specifically — an
app-wide CORS hook is the plausible-looking wrong implementation of this
requirement and it would open the authenticated surface.

---

## 7. Edge cases and behaviours to pin

| # | Case | Required behaviour | Why it matters |
|---|---|---|---|
| 1 | **Empty vocabulary** — migrated but unseeded database | `200` with `{"modalities": []}`. Not `404`, not `500`, not `503`. | Verified reachable in §2. The collection resource exists and is empty; that is a `200`. A `404` would mean "no such endpoint" and mislead a client into thinking it has the wrong URL. |
| 2 | **`POST`/`PUT`/`DELETE`/`PATCH`** | `405`, Flask automatic. Route declares `methods=["GET"]` explicitly. | Mirrors `tests/test_main.py:12-15` for `/health`, and the explicit-methods convention from `_research/2607230701_health-endpoint-contract.md:49`. Verified: Flask returns `405` with `Allow: HEAD, OPTIONS, GET`. |
| 3 | **No `Authorization` header** | `200`. | The endpoint is public. This is the primary contract. |
| 4 | **Invalid/garbage/expired bearer token** | `200`, identical body. Not `401`. | Verified on the existing public route: `GET /` with `Authorization: Bearer garbage` returns `200`, because a route with no `@require_role` never calls `get_principal()` (`app/auth/decorators.py:32-45`). Same must hold here. This test is the guard against a future global auth hook silently capturing the endpoint — the exact risk `_research/2607230701_health-endpoint-contract.md:56` raised for `/health`. |
| 5 | **Valid administrator or updater token** | `200`, identical body. No role-varying content. | A public endpoint must not become a role-sniffing one. |
| 6 | **Orphan row** — a `modalities` row not in the allow-list | Excluded from the response. | §2. The endpoint advertises what is assignable, and that row is not. |
| 7 | **`HEAD`** | `200`, no body. Flask automatic. | No work needed; do not add a handler. |

---

## 8. Tests Dale must write

New file `tests/test_api_modalities.py`. The `client` and `seeded_client`
fixtures already exist (`tests/conftest.py:22-32`) and cover cases 1 and 3
respectively with no new fixture work.

1. `test_returns_all_modalities` — `seeded_client`, asserts the exact ordered
   payload `{"modalities": [{"name": "Audio"}, {"name": "Files"},
   {"name": "Images"}, {"name": "Text"}, {"name": "Videos"}]}`. Exact equality,
   not a subset check.
2. `test_response_is_json_and_ordered_alphabetically` — asserts
   `content_type == "application/json"` and that the extracted names equal
   `sorted(names)`.
3. `test_empty_vocabulary_returns_empty_list` — bare `client` (unseeded), asserts
   `200` and `{"modalities": []}`. **Case 1 of §7; this is the card's named edge
   case and must not be skipped.**
4. `test_requires_no_authentication` — no header, `200`.
5. `test_invalid_token_still_returns_200` — `Authorization: Bearer nonsense`,
   asserts `200` and that the body matches the unauthenticated response. Case 4.
6. `test_authenticated_response_is_identical` — a real key via
   `create_api_key(...)` (pattern at `tests/test_admin_models.py:8`), asserts the
   body equals the unauthenticated body.
7. `test_rejects_post` — `405`. Case 2.
8. `test_sets_cache_and_cors_headers` — asserts
   `Cache-Control == "public, max-age=300"` and
   `Access-Control-Allow-Origin == "*"`.
9. `test_admin_routes_remain_no_store` — regression guard. Asserts a `/admin/*`
   JSON response still carries `Cache-Control: no-store` and **no**
   `Access-Control-Allow-Origin` header. This is the test that catches an
   app-wide CORS hook (§6).
10. `test_excludes_rows_outside_allow_list` — insert a `Modality(name="Bogus")`
    row directly, assert it is absent from the response. Case 6, and the only
    test that actually pins the intersection semantics of §3.

Plus one query-count assertion is **not** required — the endpoint is a single
`SELECT` over five rows and the existing counter harness
(`tests/test_models_listing.py:76-92`) exists for the N+1 risk on `/`, which
does not apply here.

Full suite must pass unchanged. If any existing test in
`tests/test_admin_models.py` or `tests/test_models_listing.py` breaks, the
constant collapse in §3 was done wrong — the names and types are specified to be
preserved precisely so that nothing else moves.

---

## 9. Documentation (part of the deliverable, not optional)

This is the half of Erik's question that code cannot answer. README gains a
`## Public API` section, placed **before** `## Authentication` (currently
`README.md:77`), containing:

1. A one-line statement of the rule: *`/api/v1/` is the public, agent-facing
   REST API. Some of its endpoints require authentication and some do not; the
   table below is authoritative, and any endpoint that requires a token returns
   `401` with a `WWW-Authenticate: Bearer` header when called without one.*
2. The table, with a row per endpoint and an explicit **Auth** column:

   | Method | Path | Auth | Description |
   |---|---|---|---|
   | GET | `/api/v1/modalities` | None | Modality vocabulary assignable to a model |

3. A `curl` example with its exact response body, matching the style of the
   existing examples at `README.md:149-211`.
4. An explicit note that the returned `name` values are the exact tokens to send
   in `input_content` / `output_content` when creating or editing a model —
   closing the loop for the agent-updater use case the root card was written
   for.

`## Project Structure` (`README.md:40-56`) gains `app/routes/api.py`.

---

## §A — Assumptions taken

Each is in force, each has an entry in `_research/DECISION.md`, each states its
reversal cost. Dale proceeds against these without further consultation.

1. **`/api/v1/` is the public API prefix, and it denotes audience rather than
   auth class** (D-025). Mixed-auth is an intended property of the prefix; the
   `401` + `WWW-Authenticate` response and the README table are the signposts.
   *Reversal cost: low now, and it only rises.* Renaming or dropping the version
   segment before any agent consumes it is a one-line change. After adoption it
   is a breaking change for every external caller — which is the exact cost
   D-013 and D-014 both told us to price in advance.

2. **Response is `{"modalities": [{"name": ...}]}` with no `id`** (D-026),
   overriding the card body's request for id-and-name. *Reversal cost: adding
   `id` later is purely additive and breaks no client.* Removing it after
   publication would be breaking. We are on the reversible side, deliberately.

3. **One canonical `ALLOWED_MODALITIES` in `app/data/modalities.py`; the
   endpoint serves the `modalities` table intersected with it** (D-027).
   *Reversal cost: trivial* — the constant can move again, and the two call
   sites keep their existing names and types so nothing downstream is coupled to
   the location.

4. **`Cache-Control: public, max-age=300` and a hand-written
   `Access-Control-Allow-Origin: *`, scoped to this one route; no `flask-cors`
   dependency** (D-028). *Reversal cost: nil* — delete a header, or lower
   `max-age`. Adding `flask-cors` later remains open if a real browser client
   with non-trivial CORS needs appears.

5. **Empty vocabulary is `200` + empty array, not an error** (D-029).
   *Reversal cost: trivial*, but it would be a contract change once pinned by
   test 3, so raise it as its own card rather than changing it in passing.

6. **No pagination, filtering, or query parameters.** Five rows, closed
   vocabulary (D-001). *Reversal cost: additive; any parameter added later
   defaults to current behaviour and breaks nothing.*

7. **No deprecation or lifecycle metadata on modalities.** The vocabulary is
   closed and changes only by code change (D-001). *Reversal cost: additive
   field on the modality object — which is exactly what the object-not-string
   choice in §5 preserves.*

8. **`tests/test_models_listing.py:12`'s independent copy of the vocabulary
   stays.** *Reversal cost: nil.* Deliberate duplication in a test asserting
   against the value under test.

---

## §B — Decisions required (BLOCKING)

**None. This document hands off directly to t_8e6dd729.**

Given AGENTS.md §2's standing warning about a gating question that was misfiled
as non-blocking, the emptiness of this section is justified explicitly rather
than assumed:

- **Database schema or migration:** no change. No new table, no new column, no
  Alembic revision. Head stays `453c7603f37a`. `app/data/modalities.py` is a
  Python constant, not DDL.
- **Role / permission model:** unchanged. No new role, no new gate, no change to
  any existing gate. The endpoint is ungated — and that is not an agent
  assumption, it is the operator's own stated position on the root card ("I
  don't think this endpoint needs authentication"), paired with an explicit
  delegation of the remaining sub-question ("Do what provides the better user
  experience"). §4 is the answer to the question Erik delegated, not a decision
  taken over his head.
- **An existing API request or response contract:** none is modified. Every
  currently shipped endpoint keeps its exact behaviour, headers included; test 9
  in §8 exists to prove it.
- **A test pinned as intended behaviour:** no existing test changes. §3 specifies
  name-and-type-preserving refactors precisely so that
  `tests/test_admin_models.py` and `tests/test_models_listing.py` need no edit.
  A broken existing test is a signal the refactor was done wrong, not a signal
  the spec is wrong.
- **Anything shipped on a branch with an open PR:** nothing. `main` @ `638ca3f`
  is clean, PR #12 is merged.

The one decision with a genuine forward cost — the `/api/v1/` prefix
pre-committing where the future public write API lives — is not an open
question, because D-013's CONFIRMED rationale is Erik instructing us to make
exactly that choice now: *"a known use case ... will need to be implemented
eventually ... it may impact choices made now (e.g., choice of route names)."*
This spec executes that instruction. Re-asking would be the mistake AGENTS.md §1
warns against: re-deriving a question already ruled.

---

## 10. Implementation checklist for Dale (t_8e6dd729)

**Add**

- `app/data/modalities.py` — canonical `ALLOWED_MODALITIES` tuple, seed order.
- `app/routes/api.py` — `api_bp` at `/api/v1`, one `GET /modalities` view.
- `tests/test_api_modalities.py` — the ten tests in §8.

**Modify**

- `app/commands.py:37` — import the constant.
- `app/routes/admin.py:24` — import the constant, wrap in `frozenset`, keep the
  module-level name.
- `app/__init__.py:48-54` — import and register `api_bp`.
- `README.md` — `## Public API` section before `## Authentication`;
  `app/routes/api.py` in `## Project Structure`.

**Do not touch**

- Any migration. Alembic head stays `453c7603f37a`.
- Any existing route, decorator, or `Cache-Control` header.
- `tests/test_models_listing.py:12`.
- `app/templates/*` — this card ships no UI.

**Branch and PR** per AGENTS.md §4: dedicated branch, commit this
`_research/` file and the `DECISION.md` entries alongside the code, push, open a
PR, self-verify, comment findings, complete the ticket.

---

## 11. Review criteria for Kova (t_b2839780)

1. Route is exactly `GET /api/v1/modalities` on a new `api_bp`, `methods=["GET"]`
   declared explicitly.
2. No `@require_role` on the new view; no auth import used to gate it.
3. Response body is `{"modalities": [{"name": ...}]}` — envelope present, `id`
   **absent**, alphabetically ordered, ordering done in SQL not Python.
4. Serves the DB table intersected with the allow-list — not the constant alone,
   not the table alone. Test 10 must actually exercise an orphan row.
5. Exactly one canonical `ALLOWED_MODALITIES` definition remains in `app/`;
   `app/routes/admin.py` still exposes a module-level `frozenset` under that
   name.
6. `Cache-Control: public, max-age=300` and `Access-Control-Allow-Origin: *` are
   present **on this route only**.
7. **No app-wide CORS hook, no `after_request` header injection, no
   `flask-cors` in `requirements.txt` or `pyproject.toml`.** Test 9 must pass
   and must genuinely assert the absence of the CORS header on `/admin/*`.
8. Unseeded database returns `200` `{"modalities": []}`.
9. Invalid bearer token returns `200`, not `401`.
10. No new query parameters, no pagination, no filtering.
11. No migration added; Alembic head unchanged.
12. Full `pytest` suite green with no existing test modified.
13. README `## Public API` section exists, before `## Authentication`, with an
    explicit **Auth** column and the `curl` example. Documentation is a
    deliverable of this card, not a nicety — it is the substance of Erik's
    "how would you sign post the difference" question.
