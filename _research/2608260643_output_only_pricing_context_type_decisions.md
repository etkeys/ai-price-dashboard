# Output-only pricing and variable context types — decision brief

- Card: `t_c2ba9f5b`
- Author: Chip
- Date: 2026-08-26
- Status: **RULED 2026-08-26 — approved as recommended; see D-037..D-039**
- Code state: commit `0da3e58d215a5b84adf2b765d97659cb6dc9eca7`, branch `feat/public-models-listing-endpoint`, Alembic head `453c7603f37a`
- Downstream implementation: `t_0500161d`
- Downstream review: `t_739c4ae4`

## 1. Findings from the existing implementation

### 1.1 The workaround is enforced at every layer

`AiModel.price_in`, `price_out`, and `context_tokens` are all non-null columns. The database requires non-negative prices and a strictly positive token context (`app/models/ai_model.py:98-109,145-149`; original DDL at `migrations/versions/637848f507e4_add_ai_models_modalities_and_modality_.py:24-31`). Consequently, the current schema cannot distinguish “not applicable” from either zero or a fabricated number.

The shared create/update validator rejects `null` and empty strings for every editable field, converts both prices to floats and context to an integer, then requires non-negative prices and `context_tokens > 0` (`app/routes/admin.py:251-291`). The browser forms make all three numeric fields required and constrain context to at least one (`app/templates/admin/models.html:72-85,123-136`); JavaScript always converts them with `Number(...)` (`app/static/js/admin-models.js:118-148,211-238`).

Both dashboard surfaces assume the values are numeric. The public page globally labels prices “USD per 1M tokens,” always prepends `$`, and always humanizes a token count (`app/templates/index.html:8,25-27`). The management table and its row data attributes also emit raw numeric values (`app/templates/admin/models.html:30-45`). `format_price` and `format_context` accept only numeric values (`app/utils/helpers.py:11-31`).

The new public endpoint exposes the same assumptions as an API contract: `price_in`, `price_out`, and `context_tokens` are always-present raw numeric fields (`app/routes/api.py:103-117`). D-031 explicitly pinned the original eleven-key object and stated that `context_tokens` is a raw integer.

### 1.2 There is no automated OpenRouter importer in this repository

The only bulk ingestion path is `flask seed`, which inserts `SAMPLE_MODELS` into an empty database and does not update an existing row (`app/commands.py:44-103`). The only supported automated refresh path is the updater-authorized partial endpoint `PATCH /admin/models/<id>` (`app/routes/admin.py:394-458`), consistent with D-007 and D-012. Therefore “automated model-update/import logic” means two concrete paths for this change:

1. make the seed record shape capable of expressing output-only/per-image data; and
2. make `PATCH` able to transition an existing model between token and image context without sentinels.

No OpenRouter HTTP client, scraper, import command, pricing calculation, or aggregation logic exists to modify. Adding one would be unrelated scope.

### 1.3 The upstream example is genuinely output-only/per-image

The live OpenRouter Seedream 5.0 Lite page identifies `bytedance-seed/seedream-5-0-lite` as image generation, displays `$0.035/image`, and labels the provider price column `Output/img`. It does not present a meaningful token context size. This confirms that copying `0.035` into both price columns and `1` into `context_tokens` loses semantics rather than merely formatting them poorly.

### 1.4 Baseline is healthy

At the inspected commit, `pytest -q` reports `220 passed`; Alembic reports one head, `453c7603f37a`.

## 2. Question 1 — How is an inapplicable input price represented?

### The conflict

D-005 requires every model attribute because a model row with missing pricing was considered useless. That ruling addressed omitted model data, not a billing dimension that does not exist. Nonetheless, allowing `price_in = null` changes the database schema, create/update contract, public response, UI controls, and pinned tests, so this cannot be treated as a quiet extension of D-005.

### Option A — Nullable `price_in` (recommended)

- Change `ai_models.price_in` to nullable.
- JSON `null` means explicitly “not applicable”; an omitted key still means missing on create and “leave unchanged” on PATCH.
- Keep `price_out` required, finite, and non-negative.
- Render `price_in = null` as `N/A`, with no dollar sign.
- Preserve zero as a real numeric free-input price. This is important: `0` and “not applicable” are different claims.

Cost: a SQLite batch migration, validation changes, optional typing, UI form handling, and clients of `GET /api/v1/models` must tolerate `null` for this field.

### Option B — Keep `price_in` numeric and add `input_price_applicable`

- Keep the existing non-null float and add a boolean.
- When false, the numeric value is ignored.

Cost: a new column and API field while retaining contradictory state (`false` plus any number). Every writer and reader must enforce or interpret two fields atomically. It also perpetuates a meaningless stored number.

### Option C — Reserve a numeric sentinel (`0` or a negative number)

Cost: no useful representation. Zero already means free and is valid; negative values violate the existing constraint and make arithmetic unsafe. Recommended against.

### Recommendation

Choose **A**. SQL/JSON null is the conventional explicit representation for an inapplicable scalar, and it preserves the meaningful distinction between free and nonexistent.

## 3. Question 2 — What schema represents non-token contexts and pricing units?

### The conflict

The current `context_tokens INTEGER NOT NULL` combines a value and an implicit type (“tokens”), while the public page separately hard-codes that all prices are per one million tokens. Seedream needs both “no numeric token context” and “output price is per image.” A field called only `context_type` can be made to drive both meanings, but that couples two concepts that may diverge for future models.

### Option A — One `context_type` field drives both context and price denominator

Add `context_type TEXT NOT NULL` with a closed vocabulary initially containing `tokens` and `image`; make `context_tokens` nullable. `tokens` means prices are per 1M tokens and requires positive `context_tokens`; `image` means price is per image and requires `context_tokens = null`.

Cost: smallest schema and UI, but the name “context type” silently also means “billing unit.” A future model with a token input context and per-image output pricing cannot be represented without redesign.

### Option B — Separate `context_type` and `pricing_unit` (recommended)

- `context_type TEXT NOT NULL`, closed vocabulary initially `tokens`, `image`.
- `context_tokens INTEGER NULL`.
- `pricing_unit TEXT NOT NULL`, closed vocabulary initially `million_tokens`, `image`.
- Database checks:
  - `context_type = 'tokens'` requires `context_tokens > 0`;
  - `context_type = 'image'` requires `context_tokens IS NULL`.
- `pricing_unit` controls the dashboard suffix (`/1M tokens` or `/image`) independently of what is shown in the Context column (`200K tokens` or `Image`).

Cost: two additive fields rather than one and one additional select in each create/edit form. It avoids semantic coupling and can represent a token-context multimodal model billed per generated image.

### Option C — Replace context with free-form text

Replace `context_tokens` with a string such as `"200K tokens"` or `"image"`.

Cost: destroys numeric querying and validation, creates spelling/case variants, and requires a breaking API type change for every existing model. Recommended against.

### Recommendation

Choose **B**. D-001 establishes the project convention for small, closed vocabularies: plain text values with CHECK constraints, not lookup tables. Separate type and billing unit are still only two constrained text columns, and they avoid encoding a false equivalence.

## 4. Question 3 — What compatibility and transition contract should writers follow?

### The conflict

The public model object currently has exactly eleven keys and always-numeric `price_in`/`context_tokens` (D-031 and `tests/test_api_models.py:21-33,105-111`). Existing create clients send no type/unit fields, and D-005 says all attributes are required. Requiring new fields immediately would break those clients; defaulting them changes whether the new attributes count as “required.” PATCH also needs a rule for transitions whose validity depends on the resulting row, not one submitted field in isolation.

### Option A — Backward-compatible defaults plus explicit transition pairs (recommended)

- Migration backfills every existing row to `context_type = 'tokens'`, `pricing_unit = 'million_tokens'`; all existing price and context values remain byte-for-byte unchanged.
- ORM/server defaults use the same values so direct legacy inserts remain token-based.
- `POST /admin/models` accepts omitted `context_type` and `pricing_unit` as those legacy defaults. All existing request bodies continue to work. `price_in` remains a required key but may be explicitly JSON `null`.
- `PATCH` keeps omission = unchanged. It accepts `price_in: null` explicitly.
- A PATCH that changes `context_type` must also include `context_tokens`, so the transition is explicit and atomic:
  - image: `{"context_type":"image","context_tokens":null}`;
  - tokens: `{"context_type":"tokens","context_tokens":<positive integer>}`.
- `pricing_unit` may change independently because it has no dependent numeric field.
- Validation checks the prospective complete row before assignment, then relies on matching DB CHECK constraints as the final guard.
- `GET /api/v1/models` retains every existing key, adds `context_type` and `pricing_unit`, and emits JSON null for inapplicable `price_in`/`context_tokens`. Existing token rows retain numeric values.

Cost: the create endpoint has two documented defaults, a narrow compatibility exception to “all attributes required.” Adding response keys is additive for normal JSON consumers, but strict clients that assert exactly eleven keys must update.

### Option B — Require all new fields immediately

Every POST must include both type/unit fields; PATCH transition rules remain explicit.

Cost: cleaner literal reading of D-005, but every existing create/import client breaks on deployment despite all old requests having unambiguous token semantics.

### Option C — Infer everything from nullability and modalities

Infer image context/unit when `context_tokens` is null or output modalities include Images.

Cost: brittle. Models can accept/output images while retaining token contexts and token billing. It makes modality edits unexpectedly alter pricing semantics. Recommended against.

### Recommendation

Choose **A**. Existing rows and request bodies have exactly one reasonable interpretation, so migration/defaulting is lossless. New non-token rows must state their semantics explicitly.

## 5. Concrete implementation plan once ruled

The implementation card `t_0500161d` already exists and is dependency-gated on this decision card. Once Erik rules, its body/comment should be amended with the selected contract and the following file-level plan.

1. **Migration and model**
   - Create one Alembic revision after `453c7603f37a` using SQLite batch alteration.
   - Modify `app/models/ai_model.py`: nullable typing for the ruled fields, new constrained text columns, named CHECK constraints for vocabulary and conditional context validity, constants for the allowed values/defaults.
   - Upgrade must preserve every existing row as token context / million-token pricing. Downgrade must fail clearly or document that non-token rows must be normalized first; silently inventing `context_tokens = 1` would recreate the defect this feature removes.

2. **Validation and persistence**
   - Modify `_EDITABLE_FIELDS`, `_validate_model_values`, `create_model`, and `update_model` in `app/routes/admin.py`.
   - Distinguish key absence from explicit JSON null. Reject null/empty `price_out`; allow null only for `price_in`. Validate finite non-negative numeric prices.
   - Validate closed type/unit strings exactly (no truthiness or implicit coercion). Validate the prospective row and atomic context transitions.
   - Assign the new fields on create/update. D-012 continues to allow updater edits because these are source-sync values on an existing row.

3. **Seed/import shape**
   - Modify `app/data/sample_models.py` documentation and records according to the compatibility ruling.
   - Modify `app/commands.py` to persist explicit/default type and unit values.
   - If Seedream is added to `SAMPLE_MODELS`, represent it with `price_in = null`, `price_out = 0.035`, image context, per-image pricing, and image output. Do not add an OpenRouter network importer in this card.

4. **Public API and docs**
   - Modify `app/routes/api.py` to add the ruled fields and serialize nullable values as JSON null without formatting.
   - Modify `README.md` examples and field documentation, explicitly distinguishing null (not applicable) from zero (free), and documenting defaults and PATCH transition rules.

5. **Dashboard and management UI**
   - Modify `app/utils/helpers.py` and `app/templates/index.html` so null input price renders `N/A`, price suffix comes from the ruled pricing-unit field, and Context visibly includes its type rather than treating every value as tokens.
   - Modify `app/templates/admin/models.html` to carry the new row data attributes, render clear type/unit labels, add create/edit selects, and permit blank input price/context only when semantically valid.
   - Modify `app/static/js/admin-models.js` to send JSON null rather than `Number('') === 0`, populate new controls from row attributes, and validate coherent combinations client-side while leaving the server authoritative.
   - Modify CSS only if needed for layout; no presentation redesign.

6. **Required tests**
   - `tests/test_models.py`: schema defaults; nullable input; valid image row; reject invalid vocabulary and all invalid type/context combinations at DB level; legacy ORM construction remains token-based.
   - `tests/test_admin_models.py`: create and PATCH output-only image model; null-vs-omitted semantics; zero remains valid and distinct; atomic context transitions; bad vocabulary/types; old request body still succeeds; updater authorization unchanged.
   - `tests/test_api_models.py`: additive fields; Seedream-like row emits `price_in: null`, `price_out: 0.035`, nullable context value and explicit type/unit; legacy rows remain numeric/default-token; hidden/filter/header behavior unchanged.
   - `tests/test_models_listing.py`: `N/A`, `$0.035/image`, visible image context type, unchanged legacy `$…/1M tokens` and `200K` behavior; sample-record shape updated.
   - Add migration verification (new test or documented command) on a populated pre-revision SQLite database: upgrade preserves all old values and defaults; downgrade behavior is exercised deliberately.
   - Full verification: `pytest -q`; `flask db upgrade`; inspect Alembic has one head; perform upgrade→downgrade→upgrade on a copied populated test database.

## What I need from Erik

**Resolved 2026-08-26.** Erik selected all three recommendations:

1. **1A:** nullable `price_in`.
2. **2B:** separate `context_type` and `pricing_unit`.
3. **3A:** legacy defaults plus explicit transition pairs.

The authoritative rulings are D-037, D-038, and D-039 in
`_research/DECISION.md`. The implementation plan in §5 is approved unchanged.

## §A — Assumptions taken

None. Each viable choice changes the schema, API contract, or pinned tests and is therefore blocking under `AGENTS.md` §2.

## §B — Decisions required (BLOCKING)

None. Erik ruled 1A, 2B, and 3A on 2026-08-26; the answers are transcribed as
D-037..D-039 in `_research/DECISION.md`. This plan is ready to hand off.
