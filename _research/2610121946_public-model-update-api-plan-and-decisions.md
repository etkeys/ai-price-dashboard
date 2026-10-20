# Public model-update API — implementation plan and decision brief

- Card: `t_05923484`; root: `t_808b09aa`
- Author: Chip
- Date: 2026-10-12
- Status: READY — Erik ruled D-040 A with boolean-coercion correction, and D-041 A on 2026-10-12 (card comment transcribed into DECISION.md).
- Exact code state: branch `feat/output-context-pricing`, commit `d8c4de21be429a4d68a37d8b50a103b9a0a42266`; working tree clean before research.
- Alembic source head: `a1f2b3c4d5e6` (verified using the testing factory; not a claim about the deployed DB's revision).
- Implementation/test/review cards already exist: `t_67d556a0`, `t_e5b77657`, `t_e7326338`. §B is resolved; this plan is ready for handoff.

## 1. Codebase findings

Flask + Flask-SQLAlchemy + Flask-Migrate; dependencies are in `pyproject.toml:12-24`. Blueprints are registered in `app/__init__.py:49-58`. No request-schema library is installed; validation is manual.

`AiModel` maps to `ai_models` (`app/models/ai_model.py:122-170`). Default SQLite storage is `instance/app.db`; production can override `DATABASE_URL` (`app/config.py:17`, `README.md:57-72`). Schema changes belong to Alembic; this endpoint needs none.

| Attribute | Stored shape / meaning | Public update eligibility |
|---|---|---|
| `id` | Integer primary key | Server-owned, forbidden |
| `name` | Unique, indexed, non-null VARCHAR(128) | Forbidden for BOTH roles |
| `price_in` | Nullable FLOAT; null = not applicable, 0 = free | Editable |
| `price_out` | Non-null FLOAT, >= 0 | Editable |
| `context_type` | Non-null VARCHAR(16), `tokens` or `image` | Editable |
| `context_tokens` | Nullable INTEGER; positive for tokens, null for image | Editable |
| `pricing_unit` | Non-null VARCHAR(16), `million_tokens` or `image`; independent of context type | Editable |
| `created_at` | Non-null DATETIME, server default CURRENT_TIMESTAMP | Server-owned, forbidden |
| `updated_at` | Non-null DATETIME, server default/on-update; explicitly bumped for modality edits | Server-owned, forbidden |
| `hidden_at` | Nullable DATETIME; null = visible | Forbidden |
| `hidden` / `is_hidden` | Derived boolean from `hidden_at`, not another column | Forbidden |
| `input_content`, `output_content` | Derived ordered lists of modality names | Editable via association replacement |
| `sort_name` | Derived name with leading tildes ignored | Read-only internal property, not a public payload field |

The association tables `ai_model_input_modalities` / `ai_model_output_modalities` have composite PK `(ai_model_id, modality_id)` and non-null `position`; model FK cascades on delete, modality FK restricts (`app/models/ai_model.py:90-119`). Relationships/read properties preserve position order (`:172-188`, `:219-227`). Submit names, not association IDs or relationship objects.

The existing mirror is `PATCH /admin/models/<int:model_id>` (`app/routes/admin.py:489-567`): non-empty object, identity/unknown-field rejection, lookup by ID, prospective-row validation, modality resolution before mutation, one transaction, rollback on integrity failure, explicit `updated_at`, and 200 `{id,name}`. Hidden state has a separate administrator-only PUT (`:570-614`). Creation stays administrator-only (`:423-425`).

Roles are EXACT strings `updater` and `administrator`, not `admin` (`app/models/auth.py:59-61`, CHECK at `:97`). `@require_role(ROLE_UPDATER)` admits both by rank (`app/auth/decorators.py:48-65`, `app/services/auth_service.py:46,126-128`). Resolver accepts Bearer API keys or sessions, rejects recovery keys, validates secrets, expiration/revocation and session parent/idle lifetime (`app/services/auth_service.py:199-269`). Agents can use their long-lived API key directly; no new credential exchange is required. Never accept a caller-provided role field.

Binding policies: D-007/D-012 allow value/modality updates by updater, never row creation/deletion or name edits; D-019/D-022 reserve hidden changes for the separate administrator operation; D-014 explicitly accepts last-write-wins (no version/If-Match requirement), including the known eventual agent use case. D-037..D-039 define nullable input price, independent context/pricing vocabularies and atomic context transitions. D-013/D-025/D-030 already anticipate an ID-addressed public PATCH under `/api/v1`.

## 2. Proposed implementation contract

Route: `PATCH /api/v1/models/<int:model_id>` in `app/routes/api.py`, gated with `@require_role(ROLE_UPDATER)`. Public means externally documented, NOT unauthenticated. No PUT/upsert/batch endpoint; no new role or migration.

Request: `Content-Type: application/json`, `Authorization: Bearer <token>`, and a non-empty flat JSON object. Omitted keys preserve current values. Exact whitelist (the existing `_EDITABLE_FIELDS` at `app/routes/admin.py:33-41`):

`price_in`, `price_out`, `context_tokens`, `context_type`, `pricing_unit`, `input_content`, `output_content`.

Reject the whole request if any protected or unknown key is present, even if its value equals the stored value. Explicitly identify `name`, `hidden`, `hidden_at`, `is_hidden`, `id`, `created_at`, `updated_at` as protected; all other non-whitelisted keys (including ORM relationship names) are unknown. No mass assignment from arbitrary JSON.

Final schema (CONFIRMED D-040/D-041):

| Key | Accepted JSON value |
|---|---|
| `price_in` | Finite non-negative JSON number excluding booleans and strings, or null |
| `price_out` | Finite non-negative JSON number excluding booleans and strings; never null |
| `context_tokens` | Positive JSON integer excluding booleans, floats (including 3.0), and strings for resulting token context; null for resulting image context |
| `context_type` | Exact `"tokens"` / `"image"` |
| `pricing_unit` | Exact `"million_tokens"` / `"image"` |
| `input_content`, `output_content` | Non-empty arrays of distinct exact modality-name strings |

Allowed modality names are Text, Images, Files, Videos, Audio; each must also resolve to an existing `modalities` row (`app/routes/admin.py:386-420`). Each submitted list REPLACES that entire side in request order; omitted side is untouched. Validate the merged prospective row, not merely submitted scalar fields. Context type and billing unit are independent; do not infer either from modalities or force a token/image billing pairing.

D-041: require `context_tokens` in the same request only when submitted `context_type` differs from the stored value. An unchanged `context_type` alone succeeds, with the existing coherent context value retained. Both transition directions still require the pair and a coherent resulting value. Existing admin pairing behavior is NOT changed.

D-040's additional operator-requested defect correction: before any `float()` or `int()` coercion, reject JSON `true` AND `false` for `price_in`, `price_out`, and `context_tokens` in the shared admin validator, covering BOTH `POST /admin/models` and `PATCH /admin/models/<id>`, as well as the new public route. Return 400 with a clear numeric-type error; never partially mutate. Python `bool` is an `int` subclass: a generic numeric `isinstance` check alone is insufficient. Apart from boolean rejection, preserve existing admin numeric-string conversion, fractional context truncation, null/empty-string handling, and response contracts. Do not broaden the change into strict types on every route.

Example price-only body: `{"price_in": 0.1, "price_out": 0.4}`. Token-to-image transition: `{"context_type":"image","context_tokens":null,"pricing_unit":"image","price_in":null,"price_out":0.035}`. Numeric zero must never become null.

Success: 200 with the flat updated model object (not `{id,name}` and not a collection envelope), using the SAME object fields/semantics as an item of `GET /api/v1/models` (`app/routes/api.py:103-121`): `id`, `name`, `price_in`, `price_out`, `context_type`, `context_tokens`, `pricing_unit`, `input_content`, `output_content`, `hidden`, `hidden_at`, `created_at`, `updated_at`. Timestamps use the existing `_iso_utc` explicit Z helper (`:32-40`), nullable fields use JSON null. Refresh/expire both relationships after association replacement before serializing so the success body cannot return pre-write modalities.

Every handler success/error carries `Cache-Control: no-store`; no CORS wildcard or credentials header on the write route, and no new global hooks. Preserve existing public GET cache/CORS headers (D-028/D-034). The GET can remain externally cached for 60 seconds; PATCH's returned object is authoritative immediately. Hidden models remain updateable without unhiding (D-023).

| Status | Case / response |
|---|---|
| 400 | Missing/malformed JSON, wrong media type, empty/non-object body: `{ "error": "A non-empty JSON object is required" }`, following silent JSON parsing in the existing PATCH |
| 400 | Protected key: `{ "error": "Cannot update field: <key>" }`; unknown key: `{ "error": "Unknown model field" }` |
| 400 | Invalid field type/value, negative/non-finite price, context mismatch/missing pair, invalid/duplicate/empty/unpersisted modality; clear `{error: message}` |
| 401 | Missing/malformed/invalid/expired/revoked credentials or unusable session/recovery credential: existing `{ "error": "Authentication required" }`, with `WWW-Authenticate: Bearer` |
| 403 | Authenticated principal insufficient for the gate: existing `{ "error": "Insufficient role" }` |
| 404 | Valid request addresses an absent integer model ID: `{ "error": "Model not found" }` |
| 400 | Integrity failure while applying update: rollback, `{ "error": "Unable to update model" }`, matching internal PATCH |

Authentication runs before payload/row inspection. Body shape and protected/unknown checks precede lookup, matching the internal PATCH. Flask handles unmatched paths/wrong methods as framework 404/405; this card does not add app-wide JSON error handlers. Unexpected infrastructure failures remain server errors, not fabricated validation failures. No 409 name conflict or 412 precondition is expected because name is immutable and D-014 excludes optimistic concurrency.

## 3. Decision D-040 — strict public numeric types or coercive parity?

The conflict: the implementation card requires correct types, but the existing shared validator coerces through `float()` / `int()` (`app/routes/admin.py:307-339`). Read-only execution under the testing factory reproduced:

- `{"price_in": true}` becomes `price_in=1.0`.
- `{"price_out": "1.25"}` becomes `price_out=1.25`.
- `{"context_tokens": 3.75}` becomes `context_tokens=3`.

Options:

A. Strict types on the NEW public route: prices are JSON integers/numbers excluding booleans, strings and containers; context is a JSON integer excluding booleans/floats/strings, or null when allowed. Preserve internal admin coercion for browser compatibility. Cost: a small public prevalidation layer and type tests; deliberately documents different input syntax on the two surfaces, while sharing value/coherence/persistence logic.

B. Mirror internal coercion verbatim. Cost: simplest reuse, but public callers can silently submit wrong types and truncate context; tests would have to pin that permissive behavior, which weakens the new card's type-validation requirement.

C. Tighten BOTH endpoints. Cost: changes already-shipped internal behavior and existing browser-facing request contracts; needs a wider compatibility audit and approval beyond this card. Not necessary to deliver the new endpoint.

Original recommendation: A. Preserve the browser contract and reject malformed machine data. This changes 200-vs-400 behavior and pinned tests, so it was §B, not an assumption.

Resolved: Erik selected A, explicitly adding that boolean-to-number coercion must also be corrected in shipped behavior. The final contract in §2 therefore preserves admin coercion EXCEPT boolean numeric inputs. D-040 records the exact ruling and rationale; the broader option C was not selected.

## 4. Decision D-041 — context pair on actual transition or every supplied type?

The conflict: D-039 requires both fields when PATCH CHANGES context type (`_research/DECISION.md`, D-039). Existing validator instead requires `context_tokens` whenever `context_type` is present, even unchanged (`app/routes/admin.py:371-374`). Execution confirmed an existing token row rejects `{"context_type":"tokens"}` with 400.

A. Require the pair only for an actual type transition on the new public route; an unchanged type alone is a valid no-op field. Cost: compare against the current row, explicit same-type and transition tests, and a configurable/shared coherence check or small route-specific wrapper; leave internal admin behavior alone. Best literal fit to D-039.

B. Require the pair whenever `context_type` appears, matching the internal route. Cost: simpler shared validation, but clients sending unchanged metadata must redundantly include context; documents the stronger constraint and pins its 400 behavior.

Recommendation: A. The confirmed invariant is atomic transitions, not mandatory retransmission of an unchanged context value. Changing existing admin behavior remains out of scope unless Erik separately requests it. This request-contract difference requires a ruling before pinning tests.

Resolved: Erik selected A. Only the new public route changes same-type pairing semantics; the existing admin route retains its behavior. See CONFIRMED D-041 for the verbatim operator comment.

## What I need from Erik

Nothing further. D-040 and D-041 are ruled and transcribed. D-040 includes the explicitly authorized admin boolean-coercion defect fix, not a wider numeric compatibility change.

## Implementation cards to spawn once ruled

None: use the already-created graph. Erik's answers are transcribed into `DECISION.md`; this final contract is handed off to:

- `t_67d556a0` (Dale): add public route; extract shared validation/modality-resolution/transaction helpers as needed WITHOUT making the API blueprint call an admin view; factor one public model serializer for GET/PATCH; implement D-040 strict public types AND shared boolean rejection for admin POST/PATCH; implement D-041 public transition-only pairing. Keep other existing admin behavior/responses; update README Public API table, request/response/error/auth examples, intentional numeric syntax differences and read-to-write links. Commit this research doc and the decision log in the dedicated implementation branch; push/open PR per AGENTS.md.
- `t_e5b77657` (Dale): public endpoint tests. Both roles, direct API keys and session path; invalid/revoked/expired/recovery auth; synthetic insufficient authorization using a mocked known updater principal and denied `has_role` result (there is no real third/lower role in this schema). Never create a bogus DB role or assert updater gets 403. Mixed valid+protected/invalid payloads must leave scalars, association rows, name, hidden_at and updated_at unchanged; verify a fresh-session reread, full response, reordered modalities, hidden-row updates, null-vs-zero, independent pricing/context and D-040/D-041 edge cases. Include rollback coverage and unchanged admin/read API regressions.
- D-040 test matrix: public PATCH rejects true/false in EACH numeric field, numeric strings, and float context (3.0 and 3.75); accepts finite int/float prices and integer context, plus permitted nulls. Admin POST and PATCH each reject true/false in EACH numeric field before coercion; mixed PATCH errors leave all model state unchanged and invalid POST inserts neither model nor association rows. Pin that admin numeric strings/fractional context still behave as before. D-041 matrix: unchanged tokens/image type alone succeeds publicly; token-to-image and image-to-token without `context_tokens` return 400 without writes; paired valid transitions succeed; wrong/null token context and non-null image context fail. Admin same-type pairing behavior remains unchanged.
- `t_e7326338` (Kova): verify all the above, particularly numeric bool/coercion traps, context pairing, atomicity, fresh relationship serialization and absence of write CORS/cache leakage. Reviews remain forward-flowing and release the Suki root only after both Dale cards complete.

Dale's cards share a workspace/assignee: use one coordinated feature branch/PR, with test work following the agreed route; do not fork competing contract implementations. No additional dependencies or schema migrations needed.

## Verification performed

`.venv/bin/python -m pytest -q tests/test_admin_models.py tests/test_api_models.py tests/test_auth.py`: **142 passed in 3.70s** against the unmodified baseline. The public write route is not implemented yet; these are existing-path checks, not acceptance of the new API.

After the ruling, the same suite was rerun on the same code baseline: **142 passed in 3.69s**. Schema, decorator and admin/public route definitions were re-read; this finalization changes only the two research files. The requested boolean correction and new endpoint still require Dale's implementation and tests.

`.venv/bin/python -m flask --app 'app:create_app("testing")' db heads`: `a1f2b3c4d5e6 (head)`. The initial `--app run:app` head query failed because the environment selected production without a SECRET_KEY; testing factory resolved that read-only query without adding credentials or changing configuration. Validator probe reproduced all four cases documented above. No production code or persistent model data changed.

## §A — Assumptions taken

None. Existing confirmed policies are reused; public request differences and the additional admin boolean correction are explicitly ruled in D-040/D-041, not unilateral defaults.

## §B — Decisions required (BLOCKING)

None. D-040 A (with explicit boolean correction on existing admin numeric writes) and D-041 A are CONFIRMED. The final contract follows the root's requested full updated representation and protected fields, the existing public item serializer, and prior ID-addressed PATCH/auth policies; no additional role/schema change is proposed.
