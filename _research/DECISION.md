# Decisions log — ai-price-dashboard

Append-only record of operator rulings. **Newest entries at the top.**

## Who writes what

- **Erik** writes the `Ruling` and `Rationale` fields. Rationale matters more
  than the ruling: a ruling settles one question, a rationale settles the next
  six without another round trip.
- **Chip** creates the entry stub (ID, question, options, links) and reads this
  file *first* on every new research task, citing prior rulings instead of
  re-deriving or re-asking.
- **Dale / Kova** treat a `CONFIRMED` ruling here as binding. If a spec conflicts
  with a confirmed ruling in this file, the ruling wins and the conflict gets
  raised, not silently resolved.

## Status vocabulary

| Status | Meaning |
|---|---|
| `CONFIRMED` | Erik ruled explicitly. Binding. |
| `OPEN` | Blocking. No implementation cards may be spawned against it. |
| `ASSUMED` | Agent default in force, never confirmed by Erik. Code depends on it. Reversible at the stated cost. |
| `SUPERSEDED` | Replaced by a later entry. Never delete — link forward. |

Never edit a `CONFIRMED` entry in place. Add a new entry and mark the old one
`SUPERSEDED by D-xxx`.

## Entry template

```
### D-000 — <one-line question>
- Status: OPEN | CONFIRMED | ASSUMED | SUPERSEDED
- Date raised: YYYY-MM-DD   Date ruled: YYYY-MM-DD
- Source: _research/<doc>.md §<n>
- Card: t_xxxxxxxx
- Question: <what actually has to be decided>
- Options: <A / B / C, one line each>
- Chip recommends: <option + one line why>
- Ruling: <Erik's answer>
- Rationale: <Erik's reasoning — the part that generalizes>
- Reversal cost: <what it takes to change our mind later>
```

---

# Log

### D-036 — `AiModel.is_hidden` is broken as a SQL expression; fixed in this card
- Status: **ASSUMED** (defect fix, not a policy choice)
- Date raised: 2026-08-10   Date ruled: —
- Source: `_research/2608101058_public-models-listing-endpoint-spec.md` §6, §A item 9
- Card: t_937ed477 (implements in t_fa898e85)
- **This is a real shipped defect, found while validating this endpoint's query
  and reproduced in isolation.** `app/models/ai_model.py:188` uses the bare
  `@is_hidden.expression` form. Under SQLAlchemy 2.0.51,
  `select(AiModel).where(AiModel.is_hidden)` raises
  `InvalidRequestError: ... expected __clause_element__() to return a
  ClauseElement object, got: True` — class-level access still runs the instance
  getter, so SQLAlchemy is handed a Python `bool`.
- **Why it went unnoticed:** all five existing uses are instance-level
  (`tests/test_models.py:90-91` and four Jinja refs in
  `app/templates/admin/models.html`), which take the Python getter and work.
  No code has ever used it in a query — `app/routes/main.py:18` filters with
  `AiModel.hidden_at.is_(None)` directly. So the hybrid fails at exactly the one
  job D-020 created it for: defining the predicate once.
- Fix: `@is_hidden.expression` → `@is_hidden.inplace.expression`, the form
  `sort_name` already uses at `app/models/ai_model.py:172` — which is why
  `sort_name` works in `ORDER BY` and `is_hidden` does not. Verified in a
  minimal two-class script: the `.expression` form raises, `.inplace.expression`
  compiles to `WHERE hidden_at IS NOT NULL`. `sort_name` is the only other
  hybrid on the model and is already correct, so this is the whole class of the
  bug.
- In scope for t_fa898e85: one line, on this endpoint's direct query path, with
  a red-before/green-after unit test pinning the *expression* form. The endpoint
  must then use `.where(~AiModel.is_hidden)` rather than re-deriving the
  predicate.
- Reversal cost: n/a — a defect fix, not a choice.

### D-035 — No pagination, count, sort, or field-selection parameters on the models listing
- Status: **ASSUMED**
- Date raised: 2026-08-10   Date ruled: —
- Source: `_research/2608101058_public-models-listing-endpoint-spec.md` §4.1, §A item 8
- Card: t_937ed477 (implements in t_fa898e85)
- Assumption in force: `GET /api/v1/models` returns every matching row in one
  response. No `limit`/`offset`/cursor, no `count` or `total` key, no `sort` or
  `fields` parameter. 22 seeded rows, ≈6 KB of JSON, bounded by the number of
  models an administrator has manually created.
- A `count` field is `len(models)` and adding it is a standing promise to keep
  it correct for no consumer benefit.
- Reversal cost: **additive** — any parameter added later defaults to current
  behaviour and breaks nothing. The `{"models": [...]}` envelope (D-031) is
  precisely what keeps pagination metadata additive rather than breaking. If the
  table ever reaches a few hundred rows, revisit then.

### D-034 — Models listing is cacheable for 60s and CORS-open; scoped to the route, no rate limiting
- Status: **ASSUMED**
- Date raised: 2026-08-10   Date ruled: —
- Source: `_research/2608101058_public-models-listing-endpoint-spec.md` §7.3, §7.4, §A item 7
- Card: t_937ed477 (implements in t_fa898e85)
- Assumption in force: the success response carries
  `Cache-Control: public, max-age=60` and `Access-Control-Allow-Origin: *`,
  both hand-written on that one response. **Error responses carry
  `Cache-Control: no-store` and neither of those headers** — caching a 400 for a
  minute would serve a client its own stale error on the corrected retry.
- **60 seconds, not modalities' 300** (D-028): model data is operator-mutable
  through two write endpoints, so an agent's write should become visible
  promptly. The modality vocabulary changes only by code change and redeploy.
- **Binding, and now the second route needing the header:** the CORS header must
  NOT be applied app-wide, via `after_request`, via a blueprint hook, or via
  `flask-cors`. With two routes wanting it, factoring it into a hook is the
  plausible-looking wrong implementation and it would open the authenticated
  surface. The correct shape is a module-local helper both handlers call. The
  regression test asserting `/admin/*` still has `no-store` and **no** CORS
  header is required, not optional.
- Safety unchanged from D-028b: `Access-Control-Allow-Credentials` is not set
  and `*` is incompatible with it by spec; auth is a bearer token in
  `sessionStorage`, not a cookie; `GET`-only so no preflight.
- **No rate limiting.** There is none anywhere in this app today, on any route.
  Adding it to this endpoint alone would be inconsistent and would not protect
  the eleven other unauthenticated-reachable routes.
- Reversal cost: nil — change or delete a header.

### D-033 — Public API timestamps are ISO 8601 with an explicit `Z`; `/admin/*` is left alone
- Status: **ASSUMED**
- Date raised: 2026-08-10   Date ruled: —
- Source: `_research/2608101058_public-models-listing-endpoint-spec.md` §4.5, §A item 6
- Card: t_937ed477 (implements in t_fa898e85)
- Assumption in force: `created_at`, `updated_at` and `hidden_at` are emitted as
  `.isoformat() + "Z"` → `2026-08-10T10:54:19Z`. `hidden_at` is JSON `null`, not
  `""`, when the model is visible.
- **Verified: the columns are naive but genuinely UTC.** `_utcnow()`
  (`app/services/auth_service.py:69-71`) is
  `datetime.now(datetime.UTC).replace(tzinfo=None)` and the `server_default` is
  `func.now()`, which SQLite evaluates as UTC. A bare `.isoformat()` therefore
  emits a zoneless timestamp a machine consumer cannot interpret without
  out-of-band knowledge.
- **Deliberate departure** from the bare `.isoformat()` used across
  `/admin/keys` (`app/routes/admin.py:82-88`, `:177-181`) and
  `PUT /admin/models/<id>/hidden` (`:499`). Those are consumed by this app's own
  JavaScript with shared context; this one by third-party agents without it.
  **Do not retrofit the admin routes in this card** — separate cosmetic change
  with its own test churn. Kova should treat the divergence as intended.
- Reversal cost: nil for this endpoint; retrofitting `/admin/*` for consistency
  is an independent card.

### D-032 — Public model modality lists keep persisted `position` order, not alphabetical
- Status: **ASSUMED**
- Date raised: 2026-08-10   Date ruled: —
- Source: `_research/2608101058_public-models-listing-endpoint-spec.md` §4.4, §A item 5
- Card: t_937ed477 (implements in t_fa898e85)
- Question: the HTML surfaces render modalities alphabetically via a Jinja
  `| sort` (D-008). Should the API do the same, so the two agree?
- Assumption in force: **no.** `input_content` / `output_content` are returned in
  persisted `position` order — verified, `anthropic/claude-haiku-4.5` returns
  `["Text", "Images", "Files"]`.
- Why, in order of weight: (1) **round-trip fidelity.** An agent that reads a
  model, changes a price and `PATCH`es the object back would, under alphabetical
  ordering, rewrite every association row into alphabetical order as a side
  effect — `PATCH` deletes and re-inserts association rows from list order
  (`app/routes/admin.py:437-448`), so that is a real write, not a cosmetic one.
  A read endpoint must not cause data churn on write-back. (2) **D-008 was
  explicitly scoped as presentation-only**, with the properties and the
  `position` column named as untouched; `input_content` is one of those
  properties, so sorting here would extend a presentation choice into the data
  contract. (3) it makes `position` observable again, which bears on the column
  retirement question D-008 parked.
- Kova will see two surfaces ordering modalities differently. **That is
  specified, not a defect**, and a test pins it.
- Reversal cost: trivial mechanically (one `sorted()`), but it would silently
  reorder association rows for any client that round-trips through `PATCH`.
  Raise as its own card if ever reconsidered.

### D-031 — Response is `{"models": [...]}` with `id` included, diverging from D-026
- Status: **ASSUMED**
- Date raised: 2026-08-10   Date ruled: —
- Source: `_research/2608101058_public-models-listing-endpoint-spec.md` §4.1, §4.2, §A items 3, 4
- Card: t_937ed477 (implements in t_fa898e85)
- Assumption in force: an envelope object with a `models` key, **not** a bare
  top-level array (overriding t_fa898e85's card wording), each object carrying
  exactly eleven always-present fields: `id`, `name`, `price_in`, `price_out`,
  `context_tokens`, `input_content`, `output_content`, `hidden`, `hidden_at`,
  `created_at`, `updated_at`. No conditional keys, no `count`.
- Envelope matches `GET /admin/keys` → `{"keys": [...]}`
  (`app/routes/admin.py:93`) and `/api/v1/modalities` → `{"modalities": [...]}`
  (D-026), and leaves room for additive siblings.
- **`id` is included, and this is not a contradiction of D-026** — all three of
  D-026's reasons for omitting modality `id` invert for models: (1) `ai_models.id`
  is a persisted surrogate for an operator-created row, not a seed artefact of a
  code literal, so it *is* stable; (2) both model write endpoints address the
  model **by id** — `PATCH /admin/models/<int:model_id>`
  (`app/routes/admin.py:394`) and `PUT /admin/models/<int:model_id>/hidden`
  (`:461`) — while `name` is immutable (D-012); (3) the consumer is the agent
  this card exists for, and without `id` the read→write loop is impossible.
  D-026's actual principle — *publish the token the client is meant to send
  back* — is what puts `id` in here and keeps it out there.
- `context_tokens` is the **raw integer**; `format_context` / `format_price` are
  presentation helpers and must not appear in this route.
- `hidden` + `hidden_at` reuse the exact field names from D-022's
  `PUT .../hidden` response, so no new vocabulary is invented.
- Reversal cost: **asymmetric.** Additive keys are free; unwrapping the envelope
  or removing `id` later is breaking. The `id` decision is the genuinely hard one
  to reverse — but omitting it makes the endpoint useless for its stated purpose.

### D-030 — `GET /api/v1/models` with a strict `?include_hidden=true|false`, defaulting to false
- Status: **ASSUMED**
- Date raised: 2026-08-10   Date ruled: —
- Source: `_research/2608101058_public-models-listing-endpoint-spec.md` §3, §A items 1, 2
- Card: t_937ed477 (implements in t_fa898e85; root t_bca012d9)
- Question: the cards suggest `/api/publish/models` and "a query parameter to
  control inclusion of hidden models". What path, what parameter, what default?
- Assumption in force (a): path is **`GET /api/v1/models`**, overriding the
  card's `/api/publish/models`. D-025 already fixed `/api/v1/` as the public,
  agent-facing prefix and it is shipped at `999f495`. "publish" is a verb
  fragment, neither audience nor resource, and adopting it would give the app two
  public API prefixes on its second public endpoint. Anticipates
  `GET/PATCH /api/v1/models/<id>` per D-013's binding naming consequence.
- Assumption in force (b): parameter is **`include_hidden`**, accepting only
  `true` / `false` **case-insensitively**; absent → `false`. `1`, `0`, `yes`,
  `on`, `""` and anything else are **400** with `{"error": ...}` and
  `Cache-Control: no-store`. Duplicate keys: first value wins (Werkzeug
  `args.get` semantics, verified).
- **Binding: `request.args.get(..., type=bool)` must NOT be used.** Verified —
  `type=bool` is `bool(str)`, so `?include_hidden=false` yields `True` and
  `?include_hidden=0` yields `True`. Using it inverts the caller's intent
  silently. This is the same class of trap D-022 guarded against by rejecting
  `{"hidden": 1}`, and the two endpoints must not disagree about whether `1`
  means true.
- Default `false` makes the zero-configuration response agree with `/` (D-021),
  the surface a human looks at; an agent opts in to the full picture explicitly.
  The reverse default would make the simplest call return rows the dashboard
  denies exist.
- Rejected: `?hidden=include|exclude|only` and `?visibility=visible|hidden|all` —
  the `only` case is derivable client-side from `include_hidden=true` plus the
  per-object `hidden` field, so a tri-state buys nothing and costs a code path;
  and `visibility` renames the concept D-020/D-021/D-022 all call "hidden". Also
  rejected: a separate `/models/hidden` endpoint — a filter is not a resource.
- Reversal cost: (a) **low now, rising** — a rename before any agent consumes it
  is one line; after adoption it is a breaking change for every external caller,
  the exact cost D-013 and D-014 told us to price in advance. (b) widening the
  accepted value set later is purely additive; changing the default or the
  parameter name is breaking once consumed.

### D-029 — An empty modality vocabulary is `200` + empty array, not an error
- Status: **ASSUMED**
- Date raised: 2026-08-08   Date ruled: —
- Source: `_research/2608081520_public-modalities-endpoint-spec.md` §7 case 1, §A item 5
- Card: t_4ce58bc1 (implements in t_8e6dd729)
- Assumption in force: `GET /api/v1/modalities` against a migrated-but-unseeded
  database returns `200` with `{"modalities": []}`. Not `404`, not `503`.
- **Reachable, not theoretical.** Verified by execution: a fresh `db.create_all()`
  leaves `modalities` empty until `seed_database()` runs `_upsert_modalities()`
  (`app/commands.py:123-133`). The bare `client` fixture
  (`tests/conftest.py:22-25`) is exactly this state, so the case costs no new
  fixture to test.
- Reasoning: the collection resource exists and is empty. A `404` would say
  "no such endpoint" and send a client hunting for the wrong URL.
- Reversal cost: trivial mechanically, but it becomes a contract change once
  pinned by a test. Change it on its own card, not in passing.

### D-028 — Public read is cacheable and CORS-open; scoped to one route, no `flask-cors`
- Status: **ASSUMED**
- Date raised: 2026-08-08   Date ruled: —
- Source: `_research/2608081520_public-modalities-endpoint-spec.md` §6, §A item 4
- Card: t_4ce58bc1 (implements in t_8e6dd729)
- Assumption in force: the modalities response carries
  `Cache-Control: public, max-age=300` and `Access-Control-Allow-Origin: *`,
  both hand-written on that one response. **No `flask-cors` dependency** — a
  production dependency for a single static header is not justified.
- **This is a deliberate departure from `no-store`, and the departure is the
  point.** Every authenticated response in this app sets `Cache-Control:
  no-store` (`app/routes/admin.py:40,93,155`, `app/auth/decorators.py:70`)
  because it is per-principal. This one is a five-element constant that changes
  only by code change. Cache semantics thereby become a corroborating tell for
  which side of the auth boundary a response is on.
- **Binding: the CORS header must NOT be applied app-wide**, via `after_request`
  or otherwise, and must not reach any `/admin/*` or `/auth/*` route. An
  app-wide hook is the plausible-looking wrong implementation and it would open
  the authenticated surface. A regression test asserting `/admin/*` still has
  `no-store` and **no** `Access-Control-Allow-Origin` is required, not optional.
- Safety: no credentials are exposed. `Access-Control-Allow-Credentials` is not
  set and `*` is incompatible with it by spec; auth is a bearer token in
  `sessionStorage`, not a cookie, so there is no ambient credential to ride on.
  `GET`-only, so no preflight and no `OPTIONS` handler.
- Reversal cost: nil — delete a header or lower `max-age`. Adopting `flask-cors`
  later stays open if a real browser client with non-trivial CORS needs appears.

### D-027 — One canonical `ALLOWED_MODALITIES`; the endpoint serves table ∩ allow-list
- Status: **ASSUMED**
- Date raised: 2026-08-08   Date ruled: —
- Source: `_research/2608081520_public-modalities-endpoint-spec.md` §2, §3, §A item 3
- Card: t_4ce58bc1 (implements in t_8e6dd729)
- Question: the assignable vocabulary is defined in three places —
  `app/commands.py:37` (list, seed source), `app/routes/admin.py:24`
  (frozenset, write validation) and the `modalities` table. Which one does a
  discovery endpoint publish?
- Assumption in force: **neither alone — the intersection.** A name is assignable
  only if it passes `issubset(ALLOWED_MODALITIES)` (`app/routes/admin.py:306`)
  *and* resolves to a table row (`app/routes/admin.py:318-322`). Publishing
  either source alone advertises names the write path then rejects with a 400.
  Query: `SELECT id, name FROM modalities WHERE name IN (<allow-list>) ORDER BY name`.
- Also in force: collapse the duplicate constants into `app/data/modalities.py`
  as a **tuple in seed order** (`Text, Images, Files, Videos, Audio`), imported
  by both call sites. Order is preserved deliberately — it determines seed
  insertion order and therefore existing row ids. `app/routes/admin.py` keeps
  its module-level `ALLOWED_MODALITIES` name and `frozenset` type so `.issubset`,
  the set difference and `sorted(...)` are untouched and no existing test moves.
- **Divergence is not hypothetical in one direction:** `_upsert_modalities()`
  inserts but never deletes, so retiring a name from the constant leaves an
  orphan row in every existing database. The endpoint must not advertise it.
- `tests/test_models_listing.py:12`'s independent copy of the five values stays.
  A test asserting against the constant it is checking would be vacuous.
- Standing trap, inherited from D-010: the SQL `ORDER BY name` is correct only
  because all five names are capitalised single-case. A lowercase name would
  need `COLLATE NOCASE` here *and* at `app/templates/index.html:28-29`.
- Reversal cost: trivial — the constant can move again; both call sites keep
  their existing names and types, so nothing downstream is coupled to its home.

### D-026 — The public modality object exposes `name` only; no `id`
- Status: **ASSUMED**
- Date raised: 2026-08-08   Date ruled: —
- Source: `_research/2608081520_public-modalities-endpoint-spec.md` §5, §A item 2
- Card: t_4ce58bc1 (implements in t_8e6dd729)
- Question: card t_4ce58bc1 asks for "modality objects with id and name". Should
  the surrogate key be published?
- Assumption in force: **no `id`.** Response is
  `{"modalities": [{"name": "Audio"}, ...]}`. This deliberately overrides the
  card body's literal wording.
- Why, in order of weight: (1) **the ids are not stable.** Verified by execution
  — seeding assigns `Text=1, Images=2, Files=3, Videos=4, Audio=5` from the list
  literal's insertion order at `app/commands.py:37`, not alphabetically. Two
  databases seeded from different revisions can disagree. Publishing an
  identifier in a discovery endpoint promises it means the same thing tomorrow
  and on the next host; we cannot keep that promise. (2) **Nothing accepts an
  id** — every write path addresses modalities by name. Returning an id invites
  a client to submit it, which 400s. (3) it is an internal surrogate key with no
  consumer that we would then have to keep working.
- Objects rather than bare strings (`[{"name": "Audio"}]` not `["Audio"]`): nine
  characters per element buys an additive field later — a display label, a
  deprecation flag — without a `v2`.
- Envelope `{"modalities": [...]}` rather than a bare array, matching
  `GET /admin/keys` → `{"keys": [...]}` (`app/routes/admin.py:92`).
- Reversal cost: **asymmetric, and we are on the reversible side.** Adding `id`
  later is purely additive and breaks no client. Removing it after publication
  would be breaking.

### D-025 — `/api/v1/` is the public API prefix; it denotes audience, not auth class
- Status: **ASSUMED**
- Date raised: 2026-08-08   Date ruled: —
- Source: `_research/2608081520_public-modalities-endpoint-spec.md` §4, §A item 1
- Card: t_4ce58bc1 (implements in t_8e6dd729; root t_18fefad3)
- Question: Erik on the root card — *"it may be awkward to have some REST
  endpoints that do not require authentication and some that do and how would
  you sign post the difference. Do what provides the better user experience."*
- Rejected: **prefix by auth class** ("everything under `/api` is public").
  Accidentally true of the app today, and guaranteed false the moment the public
  *write* API lands — which D-013's CONFIRMED rationale tells us is a known,
  expected use case. A signpost that turns into a lie is worse than none.
- Assumption in force: prefix by **audience**, which is stable.
  `/api/v1/**` = public agent-facing REST, **mixed auth by design**;
  `/admin/**` = the dashboard's own control plane; `/auth/**` = credential
  exchange; `/` and `/health` = public HTML and liveness.
- The auth boundary is signposted three ways, all already supported by the code:
  1. **HTTP itself** — a gated endpoint called without credentials returns 401
     with `WWW-Authenticate: Bearer` (`app/auth/decorators.py:71-73`). The
     machine-readable signpost, free, and already correct. An agent does not
     need to be told which endpoints are public; it needs the gated ones to say
     so, and they do.
  2. **README `## Public API` table with an explicit Auth column.** The human
     signpost, and the actual deliverable answering Erik's question. Every
     future `/api/v1/` route adds a row.
  3. **Cache semantics as a corroborating tell** — see D-028.
- Version segment `/api/v1/`, not `/api/`: one path component now versus two
  inconsistent schemes forever once agents hardcode paths. Same "take the free
  forward option" reasoning D-013 and D-014 both argued for.
- Implementation: new `app/routes/api.py` with
  `Blueprint("api", __name__, url_prefix="/api/v1")`. **This reinstates a
  blueprint deliberately deleted** by
  `_research/2607231705_api-status-removal-plan.md`, whose §4 Option B kept it
  "as a mount point for imminent future JSON API routes ... unless an API route
  is already planned". That condition is now met — this is Option B arriving on
  schedule, not a reversal. `/api/status` is **not** resurrected; `/health`
  remains canonical.
- Not filed as §B: the ungated decision is the operator's own stated position on
  the root card, and choosing the prefix now is D-013's CONFIRMED instruction
  (*"may impact choices made now (e.g., choice of route names)"*) being carried
  out, not a fresh question.
- Reversal cost: **low now, and it only rises.** Renaming or dropping the version
  segment before any agent consumes it is a one-line change. After adoption it
  is a breaking change for every external caller — precisely the cost D-013 and
  D-014 told us to price in advance.

### D-024 — Hidden models still occupy the unique name index; only the 409 copy changes
- Status: **ASSUMED**
- Date raised: 2026-08-05   Date ruled: —
- Source: `_research/2608050700_model-inactivation-implementation-plan.md` §5, §A item 5
- Card: t_66c8528e (implemented by t_736da718)
- Assumption in force: `ai_models.name` stays globally unique across hidden and
  visible rows. Hiding `openai/gpt-6` and re-adding it therefore returns
  **409**, from a dashboard that no longer shows the row. Confirmed by
  execution. The fix is message copy only: the 409 in `create_model`
  (`app/routes/admin.py:331-332`, and the `IntegrityError` branch at `:367-369`)
  says the existing model is *hidden* and points at the manage page. Ships with
  this work, not as a follow-up.
- Rejected: a partial unique index scoped to visible rows. It would let a hidden
  row and a visible row share a name, which makes unhiding ill-defined — there
  is no rule for which row wins.
- Reversal cost: **High, deliberately.** Scoping the index later is a schema
  change plus a resolution rule for the duplicate-name collision it creates.
  This assumption is the cheap side of that trade.

### D-023 — Hiding never blocks an `updater` value sync; downgrade drops hidden state; no index
- Status: **ASSUMED**
- Date raised: 2026-08-05   Date ruled: —
- Source: `_research/2608050700_model-inactivation-implementation-plan.md` §A items 6, 7, 8
- Card: t_66c8528e (implemented by t_736da718)
- Three assumptions bundled because none is separately contestable:
  1. **`updater` may keep `PATCH`ing a hidden model.** Verified by execution:
     price updates apply, `hidden_at` is preserved, the row stays hidden.
     Follows directly from D-012's governing test — a scrape syncs an existing
     row regardless of whether a human finds it interesting.
  2. **The Alembic downgrade discards which models were hidden.** Standard for
     an additive nullable column. Documented in the PR body rather than
     engineered around; preserving it would mean an archive table.
  3. **No index on `hidden_at`.** 22 rows, and `ORDER BY ltrim(name,'~')`
     already forces a temp B-tree per D-018 item 2, so the scan is already the
     plan.
- Reversal cost: (1) low mechanically — one guard in the `PATCH` handler — but
  it is a behaviour change deserving its own card, since it makes hiding partly
  destructive of the scraper's job. (2) n/a. (3) one additive Alembic revision.

### D-022 — Endpoint is `PUT /admin/models/<id>/hidden`, idempotent, not a `PATCH` field
- Status: **ASSUMED**
- Date raised: 2026-08-05   Date ruled: —
- Source: `_research/2608050700_model-inactivation-implementation-plan.md` §3.3, §4d, §A item 3
- Card: t_66c8528e (implemented by t_736da718)
- Assumption in force: one new route, `PUT /admin/models/<int:model_id>/hidden`,
  body `{"hidden": <bool>}`, response
  `{"id", "name", "hidden", "hidden_at"}` with `Cache-Control: no-store`.
  Idempotent: re-hiding an already-hidden model returns 200 and **preserves the
  original `hidden_at`** — do not restamp. Strict `isinstance(x, bool)`
  validation; `{"hidden": 1}` is a 400, because `1 == True` in Python makes
  truthiness a real trap here.
- **Binding: `hidden` must NOT be added to `_EDITABLE_FIELDS`.** Two reasons,
  both proven by execution. Decisive: `PATCH` is gated at `updater` per D-012,
  so folding `hidden` in silently grants the power to updaters and pre-empts
  D-019 by accident. Secondary: `_validate_model_values(require_all=True)`
  treats a missing field as fatal, so widening the tuple breaks
  `POST /admin/models` for every existing client. The current
  `400 Unknown model field` response to a `hidden` key is intended behaviour and
  gets a regression test.
- Rejected: `POST /hide` + `POST /unhide` — two verbs for one state.
- Naming anticipates the public REST surface per D-013's binding consequence:
  resource addressed by id, JSON in / JSON out, noun sub-resource not RPC verb.
- Reversal cost: **Low but non-zero, and it grows.** Once the dashboard JS
  speaks this contract, the deferred public REST card either adopts it or
  versions around it — the same trap D-013 and D-014 both flagged.

### D-021 — `/` filters hidden models; `/admin/models/manage` shows all of them, marked
- Status: **ASSUMED**
- Date raised: 2026-08-05   Date ruled: —
- Source: `_research/2608050700_model-inactivation-implementation-plan.md` §3.4, §A items 2, 4
- Card: t_66c8528e (implemented by t_736da718, t_266a1995)
- Assumption in force: `app/routes/main.py` gains
  `.where(AiModel.hidden_at.is_(None))`; `app/routes/admin.py:217-230` gains
  **nothing** and keeps listing every row, with hidden ones visually marked by
  text (not colour alone) plus `data-hidden` on the `<tr>`.
- **This asymmetry is the mechanism, not an oversight.** The manage page is the
  only place a hidden model can be found and unhidden; filtering it too would
  make hiding a one-way door reachable only via `sqlite3`. Kova must treat
  "the manage page still lists hidden models" as a required behaviour. It is a
  deliberate exception to D-016's two-views-must-agree principle.
- Verified: the `WHERE` keeps `/` at exactly **3 queries**, so
  `tests/test_models_listing.py:76-92` passes untouched. Hiding every row
  renders the existing `No models available.` empty state
  (`app/templates/index.html:31-34`) — no work needed.
- Also assumed: **no `?include_hidden=` parameter on `/` and no filter widget**
  on the manage page. The manage page showing everything already satisfies the
  child card's "optional filter" ask at 22 rows.
- Reversal cost: trivial — one `where` clause. The query parameter is purely
  additive later and would default to current behaviour, so it breaks nothing.

### D-020 — Hidden state is a nullable `hidden_at DATETIME`, not an `is_active` boolean
- Status: **ASSUMED**
- Date raised: 2026-08-05   Date ruled: —
- Source: `_research/2608050700_model-inactivation-implementation-plan.md` §3.1, §3.2, §4a, §A item 1
- Card: t_66c8528e (implemented by t_736da718)
- Question: the root card asks for hiding without deletion. What shape does the
  state take — `is_active BOOLEAN`, `hidden_at` timestamp, `deleted_at`, or a
  `status` enum?
- Assumption in force: **one nullable `hidden_at DATETIME`** on `ai_models`.
  `NULL` = visible. Plus an `is_hidden` hybrid property mirroring the existing
  `sort_name` pattern (D-017), so the predicate is defined once.
- Why, in order of weight: (1) it matches the convention already load-bearing in
  this repo — `ApiKey.revoked_at`, `AuthSession.revoked_at`,
  `RecoveryKey.consumed_at` (`app/models/auth.py:82,133,161`) are all
  nullable-timestamp lifecycle flags, and `_key_status()` already derives a
  status string from them; a boolean would be the only lifecycle flag shaped
  differently from its three siblings. (2) "when did this stop being
  interesting?" is free with a timestamp and unrecoverable with a boolean, and
  the operator's phrasing was temporal. (3) a nullable column is a pure
  `ALTER TABLE ADD COLUMN`; a `NOT NULL DEFAULT 1` boolean means a table rebuild
  under SQLite `batch_alter_table` with a server default that lingers.
- Rejected: `deleted_at` — a category error. Soft-delete means "gone, retained
  for audit"; the operator wants "still here, might come back". The name would
  mislead every future reader and invite a purge job over live rows. Also
  rejected: a `status` enum, which invents states nobody asked for (cf. D-001),
  and a `hidden_models` join table, which normalises a 22-row table for nothing.
- **Filed as ASSUMED rather than §B because the API contract is
  `{"hidden": <bool>}` either way** (D-022), so the storage shape is genuinely
  internal and does not leak to any client.
- Migration: one autogenerated Alembic revision,
  `down_revision = '248f2949289c'`, `batch_alter_table` add/drop of the column.
  No backfill — existing rows get `NULL` = visible, so the migration is
  behaviour-preserving on its own. Upgrade→downgrade→upgrade round-trip verified
  on a populated 22-row database with `ix_ai_models_name` intact.
- Reversal cost: **Low.** One additive Alembic revision plus a backfill
  (`is_active = (hidden_at IS NULL)`), the hybrid property's definition, and
  nothing else. No endpoint contract change, no client change, no test rewrite
  beyond the model unit test. Costed knowing it would run against a live DB.

### D-019 — May an `updater` hide/unhide a model, or is it administrator-only?
- Status: **CONFIRMED**
- Date raised: 2026-08-05   Date ruled: 2026-08-05
- Source: `_research/2608050702_model-hide-gating-decision.md` §1
- Card: t_66c8528e (blocks t_736da718, t_266a1995, t_51953389; root t_3c65170f)
- Question: what role gates `PUT /admin/models/<int:model_id>/hidden`? The two
  confirmed precedents point opposite ways. D-007 reserves **row lifecycle** for
  `administrator`, and hiding is the nearest thing this app has to deletion —
  the operator asked for it *instead of* deletion. D-012's governing test asks
  "does this operation sync an existing row with its upstream source?", and
  hiding changes no row's existence, leaves the name unique, and leaves the row
  `PATCH`-able. A retired-upstream-model scraper story reads naturally under
  either reading.
- Options: (a) administrator only. (b) updater and administrator —
  `@require_role(ROLE_UPDATER)` admits both by rank. (c) updater may hide,
  administrator only may unhide.
- Chip recommends: **(a)**. Hiding is the deletion this app deliberately does
  not have; narrowing later is a 403 contract break for a client that previously
  got 200, whereas widening later costs one decorator argument; and the scraper
  story is speculative — no scraper exists yet (D-007 records that `updater`
  today can only call `DELETE /auth/session`). Given genuine ambiguity about
  intent, take the reversible side. **(c) is recommended against**: it needs
  in-handler branching on the request body, which is exactly the per-field
  gating D-012 explicitly ruled out.
- Why this is §B and not an §A assumption: it changes the role/permission model,
  it is a 403-vs-200 API contract difference for an entire role, and it fixes
  the shape of a test that will be pinned as intended behaviour. It is also the
  precise question AGENTS.md §2 cites as precedent — an
  `updater`-vs-`administrator` gating question was filed as non-blocking once,
  code shipped on the assumption, and it resurfaced a day later.
- Ruling: **(a) administrator only.** Erik: *"An updater may not hide models.
  Only administrators can do this."*
- Rationale: Erik's ruling was the bare answer; the generalizable reading is that
  D-007's row-lifecycle line governs, and it is read **broadly** — an operation
  does not have to add or remove a row to be a lifecycle decision. What matters
  is whether the operation states an intent about *whether a model belongs on the
  dashboard*. That is a human curation call, so `administrator`. D-012's
  "sync an existing row with its upstream source" test is therefore narrower than
  its literal wording suggests: it admits `updater` for **value** writes on a row
  whose place in the collection is already settled, not for writes that decide
  that placement. Standing rule for the next model endpoint: **if the operation
  answers "should this model be here at all?", it is `administrator`; if it
  answers "what are this model's current values?", it is `updater`.**
- Reversal cost: asymmetric, and that asymmetry is the argument. (a)→(b) is one
  decorator argument and one test edit, no client breakage. (b)→(a) is a 403 for
  any updater client already hiding models. We are on the reversible side.

### D-018 — Name sort stays case-sensitive; no functional index; SQLite-only
- Status: **ASSUMED**
- Date raised: 2026-08-04   Date ruled: —
- Source: `_research/2608042002_tilde-insensitive-name-sorting-plan.md` §A items 5, 6, 7
- Card: t_185a7a47 (implemented by t_a7bbc3b7)
- Three assumptions bundled because they share one cause — the sort expression
  is SQLite's `ltrim(name, '~')` and nothing else about ordering changes:
  1. **Case-sensitivity is untouched.** SQLite's binary collation sorts
     `Zebra/x` before `anthropic/x`. That is the behaviour on `main` today; the
     operator did not raise it and no seeded name has an uppercase leading
     character. Same standing trap already recorded for modalities in D-010.
  2. **No functional index.** `ORDER BY ltrim(name,'~')` cannot use the index on
     `ai_models.name`; SQLite falls back to `USE TEMP B-TREE FOR ORDER BY`
     (confirmed via `EXPLAIN QUERY PLAN`). Unmeasurable at 23 rows.
  3. **SQLite is the only backend that must work.** `app/config.py:17` defaults
     to `sqlite:///app.db` for every environment. Two-arg `ltrim(string, chars)`
     is confirmed on SQLite 3.53.1 and identical on PostgreSQL; MySQL's `LTRIM`
     takes one argument and would need `TRIM(LEADING '~' FROM name)`.
- Reversal cost: (1) low but not free — `COLLATE NOCASE` or a `lower()` wrapper
  changes ordering for any future mixed-case name and needs its own test; raise
  as a separate card. (2) one additive Alembic revision if the table ever grows.
  (3) one expression, and only on a MySQL port nothing suggests is coming.

### D-017 — Sort key is defined once as an `AiModel.sort_name` hybrid property
- Status: **ASSUMED**
- Date raised: 2026-08-04   Date ruled: —
- Source: `_research/2608042002_tilde-insensitive-name-sorting-plan.md` §3, §4a, §A item 4
- Card: t_185a7a47 (implemented by t_a7bbc3b7)
- Assumption in force: a `hybrid_property` named `sort_name` on `AiModel`
  (Python `str.lstrip("~")`, SQL `func.ltrim(cls.name, "~")`) rather than
  inlining `func.ltrim` at each `order_by` call site. One canonical definition
  for the surfaces that exist plus the public REST index D-013 anticipates.
  Inlining is an acceptable fallback if the property fights the type checker —
  observable behaviour is identical.
- Binding detail: **`str.lstrip("~")`, never `str.removeprefix("~")`.**
  `removeprefix` strips one occurrence, so `~~qwen/...` would still sort under
  `~`. Verified in `.venv`.
- Also binding: **`ORDER BY sort_name, name`** — the raw `name` as secondary
  term. Without it, `~deepseek/tie` vs `deepseek/tie` has no deterministic
  order and no test can pin the pair.
- Reversal cost: Trivial either way — one property, two `order_by` lines.

### D-016 — Both listing surfaces share the ordering; no client-side sort exists
- Status: **ASSUMED**
- Date raised: 2026-08-04   Date ruled: —
- Source: `_research/2608042002_tilde-insensitive-name-sorting-plan.md` §2, §A item 3
- Card: t_185a7a47 (implemented by t_a7bbc3b7)
- Assumption in force: the new ordering applies to **both** `app/routes/main.py:22`
  (`/`) and `app/routes/admin.py:226` (`/admin/models/manage`). Two views of the
  same data ordering differently is a bug; the operator would have to ask for
  that explicitly.
- Verified fact worth not rediscovering: **there is no JavaScript sort anywhere
  in this repo.** Grep for `sort` across all JS returns zero hits. Both tables
  are server-rendered and the edit dialog reloads the page
  (`app/static/js/admin-models.js:112,200`) instead of re-ordering the DOM. Any
  future card claiming the sort is "in the UI" is describing the route query.
- Also out of scope, checked individually: the Jinja `| sort` on modality lists
  (`app/templates/index.html:28-29`, `app/templates/admin/models.html:40-41` —
  D-008/D-010), `sorted(ALLOWED_MODALITIES)` at `app/routes/admin.py:229`
  (D-011), `sorted(...)[0]` error-message picks at `app/routes/admin.py:290,308,391`,
  and the 16 `order_by(AiModel.name)` row-fetch helpers in
  `tests/test_admin_models.py` — those must not need touching.
- Reversal cost: Trivial — revert one line.

### D-015 — Tilde-insensitive name sorting is presentation-only
- Status: **ASSUMED**
- Date raised: 2026-08-04   Date ruled: —
- Source: `_research/2608042002_tilde-insensitive-name-sorting-plan.md` §3, §4e, §A items 1, 2
- Card: t_185a7a47 (implemented by t_a7bbc3b7)
- Question: OpenRouter's `~deepseek/deepseek-v4-flash-latest` must sort beside
  its `deepseek/deepseek-*` siblings. Does the fix change the `ORDER BY`, or
  does it normalise the stored name?
- Assumption in force: **`ORDER BY` only.** Stored names keep their `~`
  verbatim; nothing strips, normalises, or duplicates the name on write, and
  `name` stays immutable for both roles per D-012. All leading tildes fold, not
  just the first; interior and trailing `~` are untouched.
- Rejected: normalising on write, or a second canonical-name column. Both
  destroy or duplicate operator data to solve a display problem, and a schema
  change of that kind would be a §B blocking question. Unnecessary — the
  display-only fix satisfies the request completely.
- Not a violation of `_research/2607251644_models-listing-spec.md:167` ("do NOT
  re-sort in the route"), the line D-008 leaned on: the sort already lives in
  the route's query. Changing the `ORDER BY` *expression* leaves ordering in the
  database. The prohibition is on fetching rows then re-sorting in Python.
- Reversal cost: None for the display behaviour — three source lines, no
  migration, no schema change, no API contract change. Choosing write-time
  normalisation later means a schema change plus a data migration, and becomes a
  §B question at that time.

### D-014 — No optimistic concurrency control on model updates
- Status: **CONFIRMED**
- Date raised: 2026-08-02   Date ruled: 2026-08-04
- Source: `_research/2608021645_model-edit-implementation-plan.md` §A item 5;
  `_research/2608021650_model-edit-policy-decisions.md` §What I need from Erik, item 3
- Card: t_d833f297 (implemented by t_1de70700)
- Assumption in force: `PATCH /admin/models/<id>` is **last-write-wins**. No
  `If-Match`, no `updated_at` precondition, no version column. Two updaters
  scraping the same model concurrently can silently overwrite each other.
  Acceptable today: single-user dashboard, one automated scraper.
- Reversal cost: **Moderate, and it grows.** Adding a precondition later changes
  the request contract and every client that speaks it. The deferred public REST
  update card is where this bites — if that card ships a contract without
  concurrency control, retrofitting becomes a breaking change for external
  callers rather than an internal edit. Raise it again on that card.
- Ruling: **last write wins** is acceptable.
- Rationale: While there could be multiple updaters attempting to updated the same
  model at the same time, the chances are very, very low. And even if this sitautation
  did occur, there isn't a good way conceptually to adjudicate which updater is correct.
  This is just a limitation that we'll have to accept until it really becomes a problem.

### D-013 — May the model-edit card add `PATCH /admin/models/<id>`?
- Status: **CONFIRMED** — resolved as option (a). Chip's recommendation was accepted.
- Date raised: 2026-08-02   Date ruled: 2026-08-02
- Source: `_research/2608021650_model-edit-policy-decisions.md` §Question 2
- Card: t_d833f297 (blocks t_1de70700, t_54e744a4; root t_23aec619)
- Question: Dale's card says "do not create new REST API endpoints" and this
  research card says "focus on the existing UI update flow". There is no
  existing update flow — the only model write path in the repo is
  `POST /admin/models` (`app/routes/admin.py:220-308`). No `PATCH`, no `PUT`,
  no `DELETE`, no route accepting a model id, no hidden flags. The feature is
  unimplementable without one new server route.
- Options: (a) add exactly one internal endpoint
  `PATCH /admin/models/<int:model_id>` under `/admin`, consumed only by the
  dashboard's own JS via `authFetch`; public REST stays deferred. (b) park this
  card until the public REST API is designed first, and build the UI against it.
  (Rejected: reusing `POST /admin/models` as an upsert — it would break
  `tests/test_admin_models.py:206` and silently widen creation to updaters,
  contradicting D-006.)
- Chip recommends: (a). Keeps the new-endpoint count at exactly one by
  server-rendering the existing-models table from the same query `/` already
  uses (public per D-004), rather than adding a `GET /admin/models`.
- Ruling: **(a) Yes.** `PATCH /admin/models/<int:model_id>` may be added now.
- Rationale (Erik): "The original wording on the ticket wasn't intended as 'do
  not add new routes' rather 'a known use case (known to the operator at least)
  will need to be implemented eventually and it is similar to this effort and it
  may impact choices made now (e.g., choice of route names)'."
- Consequences, binding on future work:
  - The "no new REST API endpoints" clause on `t_1de70700` is amended: it
    prohibits building the **public, agent-facing** REST surface, not adding a
    server route the dashboard's own JS consumes.
  - A future public update API is a known, expected use case. Naming and shape
    chosen now should anticipate it: `PATCH` (partial update, not `PUT`), a
    resource path addressing the model by id, and JSON in / JSON out. Prefer a
    contract the public card can adopt verbatim under a different prefix over
    one it has to version around.
- Reversal cost: Low but non-zero. Once the dashboard's JS speaks this contract,
  the deferred public REST card either adopts it or versions around it.

### D-012 — May an `updater` edit modality lists, or only price/context?
- Status: **CONFIRMED** — resolved as option (a). Chip's recommendation (b) was rejected.
- Date raised: 2026-08-02   Date ruled: 2026-08-02
- Source: `_research/2608021650_model-edit-policy-decisions.md` §Question 1
- Card: t_d833f297 (blocks t_1de70700, t_54e744a4; root t_23aec619)
- Question: Root card t_23aec619 says "all fields should be editable except
  Model Name" for both roles, which grants `updater` write access to
  `input_content` / `output_content`. D-007 (CONFIRMED) enumerates `updater`'s
  remit as `PATCH`/`PUT` on "price and context fields" and does not name
  modalities. A modality edit is not row-lifecycle (so not "structural" by the
  letter of D-007) but it is a claim about what a model *is*, not a scraped
  number — and it rewrites association rows, not an `ai_models` column.
- Options: (a) `updater` edits everything except `name` — one
  `@require_role(ROLE_UPDATER)` decorator, matches the card's literal text.
  (b) `updater` edits `price_in`, `price_out`, `context_tokens` only; modality
  lists are administrator-only via an in-handler `principal.is_administrator`
  check (`app/services/auth_service.py:64-66`). (c) two endpoints split by
  sensitivity — rejected, loses transactional atomicity for no gain over (b).
- Chip recommends: (b). D-007's rationale — the role is defined by its intended
  operator, a scraper — does not extend to capability metadata. The card's "all
  fields" most likely describes the form a human sees, not a deliberate widening
  of a role defined 48 hours earlier. Counter-argument acknowledged: (a) is
  simpler and a wrong modality is embarrassing, not dangerous.
- Ruling: **(a) Yes.** `updater` may alter model modality lists. `updater` edits
  every model field except `name`.
- Rationale (Erik): "Source data may change after administrator originally
  created the entry within the app (not likely but possible). Updater is
  essentially trying to sync source data with data within the app."
- Consequences, binding on future work:
  - This **clarifies, and does not supersede, D-007.** D-007's line is still row
    lifecycle: `updater` never creates or deletes models. Its "price and context
    fields" wording was enumeration by example, not an exhaustive whitelist.
  - The governing test for an `updater` gate is now: *does this operation sync an
    existing row with its upstream source?* If yes → `updater`. If it changes
    which rows exist → `administrator`.
  - Model **name** remains excluded from the edit surface entirely, for both
    roles, per the root card. Renaming is not in scope for either role here.
  - Implementation: a single `@require_role(ROLE_UPDATER)` decorator on
    `PATCH /admin/models/<int:model_id>`. No in-handler `is_administrator`
    split, no per-field gating, no disabled fieldsets in the edit dialog.
- Reversal cost: Non-trivial in the wrong direction. Narrowing later is a 403
  contract break for any updater client already editing modalities.

### D-011 — Admin add-model form modality order is out of scope (documentary)
- Status: **ASSUMED** (documentary — records a verified fact, not a choice)
- Date raised: 2026-08-02   Date ruled: —
- Source: `_research/2608021411_modality-display-ordering-spec.md` §7
- Card: t_14e7d6b3
- Assumption in force: the modality checkbox lists at
  `app/templates/admin/models.html:35,45` are **already alphabetical** —
  `app/routes/admin.py:217` passes `modalities=sorted(ALLOWED_MODALITIES)`. No
  work and no follow-up card. `app/static/js/admin-models.js:68-69` therefore
  submits modalities in alphabetical order, which is what gets persisted as
  `position`.
- Reversal cost: None. Nothing was changed.

### D-010 — No explicit case-folding sort key for modality display
- Status: **ASSUMED**
- Date raised: 2026-08-02   Date ruled: —
- Source: `_research/2608021411_modality-display-ordering-spec.md` §5
- Card: t_14e7d6b3
- Assumption in force: Jinja's `| sort` filter is case-insensitive by default
  (`case_sensitive=False`, verified against Jinja 3.1.6 in `.venv`), so the
  operator's case-insensitivity requirement is met with no extra code. No custom
  sort key, no case-insensitivity test — the closed vocabulary at
  `app/commands.py:37` is single-case capitalised (D-001) and
  `app/routes/admin.py:261` rejects anything outside it, so mixed case is
  unreachable through any supported write path.
- Standing trap for future work: Python's `sorted()` is case-**sensitive**. If
  this sort is ever moved out of the template into Python, `key=str.casefold`
  becomes mandatory or the requirement silently regresses.
- Reversal cost: Nil — the behaviour is already correct as specified.

### D-009 — `test_index_page_preserves_modality_ordering` is renamed and re-pointed
- Status: **ASSUMED**
- Date raised: 2026-08-02   Date ruled: —
- Source: `_research/2608021411_modality-display-ordering-spec.md` §6
- Card: t_14e7d6b3 (implemented by t_b378287b)
- Assumption in force: `tests/test_models_listing.py:64-71` asserts that `/`
  renders modalities in persisted `position` order. The operator's request
  contradicts that assertion directly, so it is renamed to
  `test_index_page_renders_modalities_alphabetically` and re-pointed at
  `"Audio, Files, Images, Text, Videos"` (plus a negative assertion on the old
  string, giving red-before / green-after). Filed as ASSUMED rather than raised
  as §B because no alternative answer exists — the change is entailed by the
  request, not chosen.
- Explicitly **not** changed: `tests/test_models.py:46-48` and
  `tests/test_admin_models.py:283-308`, which pin `position`-governed
  persistence. Those remain the home of that coverage and must not be inverted.
- Reversal cost: Revert one test function alongside the template change; they
  move together.

### D-008 — Alphabetical modality display is presentation-only; `position` stays
- Status: **ASSUMED**
- Date raised: 2026-08-02   Date ruled: —
- Source: `_research/2608021411_modality-display-ordering-spec.md` §3, §4
- Card: t_14e7d6b3 (implemented by t_b378287b)
- Question: where does the alphabetical sort live, and what happens to the
  association `position` column once display no longer honours it?
- Options: (a) Jinja `| sort` in `app/templates/index.html`; (b) sort inside the
  `input_content` / `output_content` properties; (c) change the relationship
  `order_by` to `Modality.name`; (d) build a sorted view-model in the route.
- Assumption in force: **option (a)**. Two lines of
  `app/templates/index.html:28-29` gain a `| sort` before the existing
  `| join(', ')`. The domain model, both relationship `order_by` clauses, both
  properties and the `position` column are untouched. `position` is retained as a
  write-mostly column: still persisted (`app/routes/admin.py:290,298`,
  `app/commands.py:89,97`), still the ORM read ordering
  (`app/models/ai_model.py:126,134`), but no longer observable on any user-facing
  surface.
- Chip recommends: (a). It is the only option that keeps the change out of §B —
  (b) and (c) falsify tests that pin persistence, and (c) would make `position`
  genuinely unreferenced on every read path, converting column retirement from a
  preference into a migration question. (d) contradicts
  `_research/2607251644_models-listing-spec.md:167` ("Do NOT re-sort in the
  route").
- Consequence accepted: a dashboard reader can no longer tell what order an
  author entered modalities in. That is the requested outcome, not a side effect.
- No retirement card for `position` is proposed. Dropping it needs an Alembic
  revision on two `NOT NULL` columns
  (`migrations/versions/637848f507e4_...py:46,54`) — and because both
  association tables are `PK(ai_model_id, modality_id)`, removing it leaves the
  rows an unordered set with no tiebreaker, making the order data
  unrecoverable. That needs an Erik ruling before anyone starts.
- Reversal cost: **Display choice: trivial** — delete two filter tokens.
  **Retiring `position` later: high** — one Alembic revision plus edits to
  `app/routes/admin.py:285-300`, `app/commands.py:84-99`,
  `app/models/ai_model.py:68,84,126,134` and three test files, plus permanent
  loss of existing order data.

### D-007 — `updater` is for automated price refreshes, not structural writes
- Status: **CONFIRMED**
- Date raised: 2026-07-30   Date ruled: 2026-07-30
- Source: Erik's ruling on D-006; supersedes the open concern noted in D-001
- Ruling: The `updater` role exists for **agents that scrape pricing data on a
  regular basis and update existing model records.** It is a machine role for
  mutating values on rows that already exist. It must never create or delete
  models.
- Rationale (Erik): the role is defined by its intended operator — a scraper,
  not a person. That draws the line at row lifecycle, not at field sensitivity.
- Consequences, binding on future work:
  - Structural writes (`POST`/`DELETE` on models) → `administrator` only.
  - Value updates on existing models (`PATCH`/`PUT` on price and context fields)
    → `updater` is the correct gate when that endpoint is built. **It does not
    exist yet** — there is currently no update-price endpoint, so `updater` today
    can only call `DELETE /auth/session`
    (`app/auth/decorators.py:190`). The role is provisioned ahead of its purpose.
  - Any new endpoint must be classified as structural or value-mutating before a
    gate is chosen. That classification is now the deciding question, not
    "how dangerous does this feel".
- Reversal cost: Conceptual, not mechanical. Reversing means redefining what
  `updater` means, which invalidates every gate chosen under this rule.
- See also: **D-012** clarifies (does not supersede) this entry. The "price and
  context fields" enumeration above is by example, not an exhaustive whitelist;
  `updater` may also sync modality lists on existing rows. The row-lifecycle
  line drawn here is unchanged.

### D-006 — Gate model writes at `updater` or `administrator`?
- Status: **CONFIRMED** — resolved as option 2c. Chip's recommendation (2a) was rejected.
- Date raised: 2026-07-30   Date ruled: 2026-07-30
- Source: `_research/2607302123_model-create-policy-decisions.md` §Question 2
  (also raised, mislabelled non-blocking, as `_research/2607302045_web-auth-ui-gap-analysis.md` §9 item 3)
- Card: t_17b0af72 (child of root t_d3b3414f)
- Question: Should `POST /admin/models` require `administrator`, or is `updater`
  sufficient?
- Ruling: **Administrator only.** Updaters must not be allowed to add or delete
  models.
- Rationale (Erik): updaters are automated scrapers that refresh pricing on
  existing records. Creating and deleting models is a human, structural act.
  See D-007 for the general rule this establishes.
- Code state: **already correct, no change required.**
  `app/routes/admin.py:220-221` gates `POST /admin/models` at
  `@require_role(ROLE_ADMINISTRATOR)`, and
  `tests/test_admin_models.py:20 test_updater_returns_403` pins it. Chip
  recommended widening this to `ROLE_UPDATER`; that recommendation is
  withdrawn. The existing test is correct as written and must not be inverted.
- Note: this ruling retires the D-001 concern. `updater` has a real purpose, so
  the two-role closed enum stands.
- Reversal cost: Low mechanically (one decorator, one test), high in principle —
  it would contradict D-007.

### D-005 — Should name-only model creation succeed?
- Status: **CONFIRMED** — resolved as option B. Chip's recommendation (A) was rejected.
- Date raised: 2026-07-30   Date ruled: 2026-07-30
- Source: `_research/2607302123_model-create-policy-decisions.md` §Question 1
- Card: t_17b0af72
- Question: Root card says non-name attributes are optional. Schema says
  `price_in`, `price_out`, `context_tokens` are `NOT NULL` with CHECK
  constraints (`app/models/ai_model.py:96-107`, `:138-142`). A name-only insert
  fails at the DB layer. Which side gives?
- Ruling: **Option B — the schema wins. All fields are required.** Adding a
  model requires every attribute, not just the name. The root card's wording was
  loose and is amended, not the schema.
- Rationale (Erik): "I was just being lazy. If I'm adding a model name, I have
  all the other information too." The optionality was never a real requirement —
  it was imprecise card wording. A model row with no price is not useful to a
  price dashboard.
- Code state: **endpoint already correct, no migration needed.**
  `app/routes/admin.py:239-240` rejects the zero-optional-field case, and
  `tests/test_admin_models.py:66 test_all_optional_missing_returns_400` pins it.
  The three columns stay `NOT NULL`. Chip recommended option A (nullable
  migration); that recommendation is withdrawn — it would have been a schema
  change in service of a requirement that did not exist.
- Outstanding fix: the form copy at `app/templates/admin/models.html:8` still
  promises optionality ("Provide every other attribute or leave all optional
  attributes blank") and contradicts the API. This is the **only** code change
  arising from D-005. Wording throughout the endpoint and template should stop
  calling these fields "optional".
- Reversal cost: Now high. Reversing means the nullable migration described in
  option A, on a branch with a merged PR.

### D-004 — Does `/` stay publicly readable?
- Status: **CONFIRMED** — needs confirmation
- Date raised: 2026-07-30   Date ruled: 2026-07-31
- Source: `_research/2607302045_web-auth-ui-gap-analysis.md` §9 item 1
- Assumption in force: yes, the model listing at `/` is public. True since
  project start; no card asked to change it.
- Reversal cost: One decorator on the index route plus a sign-in redirect path.
  Low.
- Ruling: Yes, `/` stays public.
- Rationale: Listing on '/' must not be sensitive and should be freely shared. Having to log in for day to day viewing would be too much friction. And with the idle timeout, I'd have to log in many times a day just to see anything even when I don't need write operations.

### D-003 — Session idle timeout of 60 minutes
- Status: **CONFIRMED** — needs confirmation
- Date raised: 2026-07-30   Date ruled: 2026-07-31
- Source: `_research/2607301109_api-key-auth-design.md` §3.4;
  `_research/2607302045_web-auth-ui-gap-analysis.md` §9 item 4
- Assumption in force: `AUTH_SESSION_IDLE_TIMEOUT` = 60 min,
  `AUTH_SESSION_ABSOLUTE_LIFETIME` = 12 h, `AUTH_RECOVERY_KEY_LIFETIME` = 15 min.
- Note: a dashboard left open on a second monitor logs itself out over lunch.
  That is a habits question only Erik can answer.
- Reversal cost: Config value on `Config` in `app/config.py`. Trivial.
- Ruling: 60 minutes is fine.
- Rationale: Workflows requiring authentication are not long. If the timeout needs to be increased, established environment variables provide an easy way to adjust.

### D-002 — Sign-in surface: modal dialog vs. dedicated `/login` page
- Status: **CONFIRMED** — needs confirmation
- Date raised: 2026-07-30   Date ruled: 2026-07-31
- Source: `_research/2607302045_web-auth-ui-gap-analysis.md` §4C, §9 item 2
- Assumption in force: modal dialog, because it avoids redirect-after-login
  state. Either is defensible.
- Reversal cost: Moderate once built — template plus JS plus any bookmarked
  URL expectations.
- Ruling: Modal if possible.
- Rationale: Less of a context switch and feel faster.

### D-001 — Two roles as a closed TEXT enum, not a roles/permissions table
- Status: **CONFIRMED** — needs confirmation
- Date raised: 2026-07-30   Date ruled: 2026-07-30
- Source: `_research/2607301109_api-key-auth-design.md` §4.1
- Assumption in force: `role VARCHAR(16) NOT NULL CHECK (role IN
  ('administrator','updater'))`, ordered capability rather than a permission
  matrix. Mirrors the closed `modalities` vocabulary at `app/commands.py:17`.
- Reversal cost: High once keys exist — a real schema migration plus a
  permission model rewrite. Confirm this one deliberately.
- Resolved concern (2026-07-30): this entry previously flagged that if `updater`
  had no purpose, the two-role enum was wrong. D-007 gives `updater` a concrete
  purpose (automated price refreshes), so the closed two-role enum stands. The
  enum shape itself is still `ASSUMED` and unconfirmed.
- Ruling: Two roles as a closed TEXT enum is good.
- Rational: 'updater', when implemented, will only be able to do a few things. Anything that 'updater' can do, an 'administor' can do. A role/permissions table is too complex for this app when we're really just trying to defend against unauthorized changes.

### D-000 — Canonical virtualenv is `.venv/`
- Status: **CONFIRMED** — implemented, Erik approved the destructive step verbally
- Date raised: 2026-07-25   Date ruled: 2026-07-31
- Source: `_research/2607251753_venv-consolidation-spec.md` §3
- Assumption in force: `.venv/` is canonical; `venv/` was removed. README
  documents `.venv/`.
- Reversal cost: None worth paying. Recorded for completeness.
- Ruling: Use '.venv/'
- Rational: Personal prefence. It's the convention that I'm used to.

---

## Reconstruction note (2026-07-30)

Entries D-000 through D-004 were reconstructed by Chip from the existing
`_research/` corpus, not transcribed from operator rulings. A sweep of all 14
research docs for recorded operator decisions returned **zero** hits — every
"Decision" heading in `_research/` is an agent recommendation. Everything above
marked `ASSUMED` is load-bearing in shipped code and has never been confirmed by
Erik. That is the gap this file exists to close.
