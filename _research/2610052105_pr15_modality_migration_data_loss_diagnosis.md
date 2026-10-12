# PR 15 modality migration data-loss diagnosis

- Card: `t_c445e6d3`
- Author: Chip
- Date: 2026-10-05
- Code state: branch `feat/output-context-pricing`, commit `8593d5e897d3be8d49e356aa89cc9abc2671ca23`, Alembic head `a1f2b3c4d5e6`
- Pre-PR comparison state: commit `727b56f`, Alembic head `453c7603f37a`
- Status: diagnosis complete; implementation required on `t_f9360722`

## 1. Finding

Migration `a1f2b3c4d5e6` is not lossless. Its SQLite batch rebuild of
`ai_models` deletes every row in `ai_model_input_modalities` and
`ai_model_output_modalities` through the existing `ON DELETE CASCADE` foreign
keys.

The migration does preserve the `ai_models` rows and correctly backfills the two
new columns. The loss is confined to the two child association tables, which is
why the model names/prices remain visible while Input Content and Output Content
become blank.

## 2. Reproduction against the two Docker images

I built two images from the repository states above and ran them through one
isolated Docker Compose project and one persistent named volume. The container
startup path used the real `flask db upgrade` and `flask seed` commands; auth
bootstrap was omitted so the diagnostic output could not expose a generated
credential.

Before the upgrade, using the pre-PR image:

- Alembic revision: `453c7603f37a`
- `ai_models`: 22 rows
- `ai_model_input_modalities`: 63 rows
- `ai_model_output_modalities`: 23 rows
- Example: `anthropic/claude-haiku-4.5` had inputs
  `Text,Images,Files` and output `Text`.

After switching the same volume to the PR-15 image:

- Alembic logged upgrade `453c7603f37a -> a1f2b3c4d5e6` with no error.
- Seeding reported `Database already seeded (22 models); nothing to do.`
- Alembic revision: `a1f2b3c4d5e6`
- `ai_models`: still 22 rows
- `ai_model_input_modalities`: **0 rows**
- `ai_model_output_modalities`: **0 rows**
- The same example model returned `NULL` for both aggregated modality lists.
- `ai_models` had the expected new nullable columns and defaults:
  `context_type='tokens'`, `pricing_unit='million_tokens'`.

This reproduces the operator's exact upgrade symptom and rules out the templates,
ORM relationship loading, and seed vocabulary as the primary cause. The rows no
longer exist in the database.

## 3. Root cause, with file and line references

Three independently reasonable pieces combine into the defect:

1. `migrations/versions/a1f2b3c4d5e6_output_only_pricing_context_types.py:27-60`
   performs all `ai_models` changes inside `op.batch_alter_table`. The migration
   itself acknowledges at lines 38-40 that SQLite batch mode rebuilds the table.
   Altering nullability and replacing CHECK constraints requires Alembic's
   create/copy/drop/rename sequence rather than a native additive ALTER.
2. `migrations/versions/637848f507e4_add_ai_models_modalities_and_modality_.py:43-57`
   defines both association-table foreign keys to `ai_models.id` with
   `ondelete='CASCADE'`.
3. `app/__init__.py:8-16` enables `PRAGMA foreign_keys=ON` on every SQLite
   connection, including the Flask/Alembic connection used by container startup.

During the batch operation Alembic copies all `ai_models` rows into its temporary
replacement table, then drops the original `ai_models` table. With foreign-key
enforcement active, that drop is a deletion of every referenced parent row for
cascade purposes. SQLite therefore deletes all rows in both association tables.
Alembic then renames the replacement table to `ai_models`, but the cascaded child
rows are already gone.

The source location responsible is therefore the batch rebuild beginning at
`a1f2b3c4d5e6...py:27`, specifically the rebuild-inducing operations through line
60, in combination with the cascade definitions above. This is not a missing
backfill of `context_type` or `pricing_unit`; those values are preserved and
backfilled correctly. It is a missing preservation strategy for dependent rows
while rebuilding their parent table.

The downgrade at `a1f2b3c4d5e6...py:88-102` uses the same batch-rebuild pattern and
has the same modality-loss risk when downgrading otherwise legacy-compatible
rows.

## 4. Why the migration tests passed

`tests/test_migration_roundtrip.py:72-94` inserts and checks only `ai_models`
rows. It never inserts a modality vocabulary row or either kind of association
row. The test therefore proves that parent-row values and new defaults survive,
but cannot detect cascading loss from the child tables.

The existing migration test file still passes unchanged: `4 passed` in 0.19s.
That green result is compatible with the production defect because the omitted
relationships are exactly the data being destroyed.

## 5. Recommended fix

Because PR 15 is not merged, correct migration `a1f2b3c4d5e6` before release
rather than relying on a later corrective migration.

Recommended implementation:

1. Before either the upgrade or downgrade batch rebuild, copy all columns from
   both association tables into dedicated temporary backup tables.
2. Run the `ai_models` batch alteration.
3. Restore both association tables from the backups after the replacement
   `ai_models` table exists.
4. Drop the temporary backup tables only after row-count and referential restore
   operations succeed.
5. Keep the existing parent-row backfills and CHECK constraints unchanged.

This explicit backup/restore is preferred over toggling
`PRAGMA foreign_keys=OFF`: changing that pragma inside Alembic's transaction is
SQLite-transaction-sensitive, weakens integrity enforcement for the whole
connection, and is easy to make a no-op accidentally. Preserving the two known
dependent tables is local, auditable, and testable.

A new post-loss migration cannot reconstruct arbitrary user assignments from the
remaining database. At most it could reapply current seed defaults to known seed
model names, which would still lose operator edits and custom models. Any database
already upgraded by the defective image needs restoration from a pre-upgrade
backup (or explicit manual reconstruction). The generic fix must prevent the
loss in the original migration.

Required regression coverage:

- Migrate a pre-revision database containing multiple input and output
  associations with nontrivial `position` values.
- Assert exact association tuples and ordering before versus after upgrade.
- Assert the same data survives downgrade and re-upgrade for legacy-compatible
  models.
- Assert `PRAGMA foreign_keys=1` during the test so the production condition is
  pinned.
- Retain the existing assertions for parent values, defaults, new image-context
  rows, and downgrade refusal.

## A — Assumptions taken

None. This diagnosis changes no product, schema, permission, or API decision.
The recommendation preserves the already-confirmed D-037 through D-039 contract
and the existing modality assignments byte-for-byte.

## B — Decisions required (BLOCKING)

None. The defect has one data-preserving outcome: existing modality assignments
must survive both directions of the parent-table rebuild.
