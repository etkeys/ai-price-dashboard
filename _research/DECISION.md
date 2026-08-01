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
