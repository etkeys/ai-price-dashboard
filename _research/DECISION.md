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
