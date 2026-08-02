# Modality display ordering on `/` — scope and contract

- **Card:** t_14e7d6b3 (child of root t_e4e84960; implementation child t_b378287b)
- **Author:** Chip
- **Date:** 2026-08-02
- **Code state described:** commit `47bf79f`, branch `main`, working tree clean.
  Alembic revisions on disk: `637848f507e4` (ai_models / modalities /
  association tables), `248f2949289c` (auth tables).
- **Status:** complete. §B is empty — no operator ruling required.
- **Decisions read first:** `_research/DECISION.md`. Cited below: `D-001`,
  `D-004`, `D-005`, `D-007`.

> **Filename note.** AGENTS.md §1 names the log `_research/DECISIONS.md`. The
> file on disk is `_research/DECISION.md` (singular) and that is what every
> prior doc and card references. This spec uses the on-disk name. Renaming it is
> not in scope here and should not be done as a drive-by.

---

## 1. Operator intent, restated

The modality lists rendered on the root route must appear in alphabetical order,
case-insensitive, stable across reloads.

## 2. What the code actually does today

The parent card `t_e4e84960` was written by the auto-decomposer and described a
client-side `String.prototype.localeCompare` fix over a "modalities array before
rendering". There is no such array. Suki already corrected this on the card; the
correction is confirmed here against the code:

| Concern | Location | Behaviour |
|---|---|---|
| Route | `app/routes/main.py:16-23` | `select(AiModel)` with `selectinload` on both modality relationships, `.order_by(AiModel.name)`. Rows sorted by model name; modality lists untouched. |
| Render | `app/templates/index.html:28-29` | `{{ model.input_content \| join(', ') }}` and the `output_content` equivalent. |
| Relationships | `app/models/ai_model.py:121-136` | `order_by=AiModelInputModality.position.asc()` / `AiModelOutputModality.position.asc()`. |
| Properties | `app/models/ai_model.py:144-152` | `input_content` / `output_content`, read-only `list[str]` comprehensions over the ordered relationships. New list per call; nothing cached, nothing mutable. |
| Persistence | `app/routes/admin.py:285-300`, `app/commands.py:84-99` | `position` assigned by `enumerate()` over the caller-supplied list, i.e. request/seed order is persisted verbatim. |
| Vocabulary | `app/commands.py:37` | `ALLOWED_MODALITIES = ["Text", "Images", "Files", "Videos", "Audio"]` — five capitalised single-case values. Closed vocabulary per `D-001`. |

So today's order is a deliberate, persisted, per-model, author-defined order. The
request is to stop honouring it *on screen*. That is a display decision, and the
whole point of the analysis below is to keep it one.

The route is public per `D-004`, so there is no auth interaction in this change.

## 3. Question 1 — where the sort lives

### Decision: **option (a), sort in the Jinja template.**

`app/templates/index.html:28-29` becomes a `| sort` inserted ahead of the
existing `| join(', ')`. Nothing else in the application changes.

### Why, and the blast radius of each candidate

**(a) Template `| sort` — CHOSEN.**
Touched files: `app/templates/index.html` (2 lines).
Reaches: the rendered HTML of `/` and nothing else.
Leaves intact: the `position` column, both relationship `order_by` clauses, both
properties, every model-layer test, the admin POST contract.
Reversal cost: delete two filter tokens from one template.

Two properties of Jinja's `do_sort` make this the cheapest correct answer rather
than merely the laziest:

1. Its signature is
   `do_sort(environment, value, reverse=False, case_sensitive=False, attribute=None)`
   — **case-insensitivity is the default.** Verified against the installed
   Jinja 3.1.6 in `.venv`:
   `{{ ['Text','images','Audio','Files'] | sort | join(', ') }}`
   renders `Audio, Files, images, Text`. Requirement 3 is satisfied with zero
   additional code. See §5.
2. It returns a new list. The properties already return a fresh list per call,
   so there is no aliasing or mutation risk in either direction.

**(b) Sort inside `input_content` / `output_content`. REJECTED.**
Blast radius, enumerated exhaustively — these are every read of the two
properties in the repo:
- `app/templates/index.html:28-29` (the target)
- `tests/test_models.py:47-50` — would break; asserts `["Images", "Text"]` with
  position 0=Images, 1=Text
- `tests/test_admin_models.py:280-281` — single-element lists, would survive by
  luck
- `tests/test_admin_models.py:307-308` — **would break**; asserts
  `["Audio", "Text", "Images"]` under the docstring "Modality ordering is
  preserved in the database"

Note what the grep does *not* find: there is no JSON surface that returns
modality lists. `POST /admin/models` responds `{"id", "name"}` only
(`app/routes/admin.py:306`); `/health` returns `{"status": "ok"}`
(`app/routes/main.py:30`). The `input_content` / `output_content` hits in
`app/routes/admin.py:234-293`, `app/commands.py:84-92`,
`app/data/sample_models.py`, `app/static/js/admin-models.js:68-69` and
`tests/test_models_listing.py:102-118` are all *request-payload or seed-dict
keys*, not the ORM properties. They share a name and nothing else.

So option (b)'s cost is not an API break — it is that it moves a presentation
concern into the domain model and falsifies two tests whose stated purpose is to
pin persistence. It buys nothing over (a).

**(c) Change the relationship `order_by` to `Modality.name`. REJECTED.**
Widest blast radius: every read of `input_modalities` / `output_modalities`,
which is both properties plus the `selectinload` options at
`app/routes/main.py:19-20` plus the `input_models` / `output_models` backrefs
(`app/models/ai_model.py:124,132`). Breaks the same two tests as (b). Critically,
it makes `position` genuinely unreferenced on every read path — the column would
become write-only at the ORM level, converting §4 from a preference into a
migration question and dragging this card into §B for no functional gain over
(a). Rejected on that ground alone.

**(d) Sort at the route. REJECTED.**
`app/routes/main.py:16-23` hands `AiModel` entities straight to the template.
The properties are read-only, so the route cannot sort in place; it would have to
build a parallel view-model (list of dicts or tuples) and change the template's
attribute-access contract to match. That is strictly more code than (a),
introduces a second representation of a model row, and puts formatting logic in
a route in a codebase that consistently formats in templates and helpers
(`format_price` / `format_context`, `app/utils/helpers.py`, used at
`app/templates/index.html:25-27`). Rejected.

**Precedent supporting (a):** `_research/2607251644_models-listing-spec.md:167`
already ruled "Keep the default sort as the data's natural order... Do NOT
re-sort in the route." Option (a) honours that; option (d) contradicts it.

## 4. Question 2 — what `position` means afterwards

### Decision: **`position` stays. No migration. No retirement card.**

Under option (a) the column is not dead. It remains:

- the persisted record of author-supplied order, written at
  `app/routes/admin.py:290,298` and `app/commands.py:89,97`;
- the ORM read ordering for both relationships
  (`app/models/ai_model.py:126,134`);
- pinned behaviour at `tests/test_models.py:34-47` and
  `tests/test_admin_models.py:283-308`.

What it stops being is *observable on `/`*. That is a real and deliberate loss of
information from the UI, and it should be stated plainly rather than buried: after
this change, a reader of the dashboard cannot tell what order the author entered
the modalities in. The operator asked for alphabetical display, so that loss is
the requested outcome, not a side effect.

I am explicitly **not** proposing a retirement card, for three reasons:

1. It is a schema change (`ai_model_input_modalities.position` and
   `ai_model_output_modalities.position` are both `NOT NULL`,
   `migrations/versions/637848f507e4_...py:46,54`) and would need an Alembic
   revision. AGENTS.md §B puts that behind an operator ruling that nothing
   currently requires.
2. Its real cost is not the migration. It is the composite primary key: both
   association tables are `PK(ai_model_id, modality_id)`
   (`app/models/ai_model.py:60-68,76-84`), so dropping `position` leaves the
   association rows an unordered set with no tiebreaker at all. Restoring any
   notion of order later would then mean re-adding the column *and* backfilling
   it from data that no longer exists.
3. Nothing is harmed by the column continuing to exist. It costs one integer per
   association row.

**§A assumption with reversal cost:** `position` is retained as a write-mostly
column whose only remaining read is ORM-level ordering that no user-facing
surface consumes. Reversal cost if Erik later wants it gone: one Alembic
revision, edits to `app/routes/admin.py:285-300`, `app/commands.py:84-99`,
`app/models/ai_model.py:68,84,126,134`, and three test files — and permanent loss
of existing order data. Recorded as `D-008`.

## 5. Question 3 — case-insensitivity

### Decision: **case-folding is free here, so take it. Do not add a custom sort key.**

The card is right that the current vocabulary is untestable for this: all five
values in `app/commands.py:37` are capitalised single-case, the vocabulary is
closed (`D-001`), and `app/routes/admin.py:261` rejects anything outside it, so
no lowercase modality can enter the database through any supported path. A test
asserting case-insensitive order would have to construct a `Modality` row
directly, bypassing the vocabulary gate, to assert behaviour that production data
cannot produce.

But there is no complexity to weigh, because `| sort` is *already*
case-insensitive by default. The operator's stated requirement is met by writing
`| sort` and nothing more. There is no trade-off to make.

**Instruction to Dale, and this is a real trap:** do not "make the
case-insensitivity explicit" by moving the sort into Python. Python's `sorted()`
is case-*sensitive* and would need `key=str.casefold` to match the filter's
behaviour — so a well-intentioned refactor from Jinja to Python silently changes
semantics in the direction opposite to the requirement. Keep it in the template.
Do not write `| sort(case_sensitive=False)` either; it is the default and the
redundancy invites someone to "clean it up" later without knowing why it was
there.

Do not add a case-insensitivity test. Recorded as `D-010`.

## 6. Question 4 — existing pinned behaviour

Two tests are in play. They must be treated differently and the card conflated
them, so be precise.

### `tests/test_models.py:46-48` — **DOES NOT CHANGE.**

```
# Ordering is governed by the association position column.
assert model.input_content == ["Images", "Text"]
```

Under option (a) this test's subject — the `input_content` property — is
untouched. The comment stays true because `position` still governs the property.
The assertion continues to pass for the reason it always passed, not by
coincidence. Dale must leave this file alone. Suki's hard constraint on
t_b378287b stands unmodified.

The card's worry that its "comment and intent would become false" is correct for
options (b) and (c). Those are rejected, so the worry does not materialise. This
is a substantial part of why (a) was chosen.

### `tests/test_models_listing.py:64-71` — **MUST CHANGE. Authorised, exact shape specified below.**

This is the pinned test the change actually collides with, and the card did not
name it:

```python
def test_index_page_preserves_modality_ordering(seeded_client):
    """Modality ordering per model survives the round-trip from the database."""
    response = seeded_client.get("/")
    ...
    # google/gemini-3.5-flash input order is Text, Images, Videos, Files, Audio.
    assert "google/gemini-3.5-flash" in html
    assert "Text, Images, Videos, Files, Audio" in html
```

It asserts the rendered order on `/` is the persisted order, using
`google/gemini-3.5-flash` whose seed input order is
`["Text", "Images", "Videos", "Files", "Audio"]`
(`app/data/sample_models.py:91`). Under alphabetical rendering it becomes
`Audio, Files, Images, Text, Videos` and this test fails.

**This is not a §B question.** §B exists for questions where a different answer
is available. Here there is none: any implementation satisfying the operator's
request breaks this assertion. The operator's request *is* the ruling on this
test. Changing it is entailment, not a decision. It is authorised here
explicitly so that Dale is not silently inverting a pinned test — which is the
thing Suki's constraint was written to prevent, and which remains forbidden for
`tests/test_models.py`.

Required shape — **rename it, do not invert it in place.** A test called
`test_index_page_preserves_modality_ordering` that asserts modality ordering is
*not* preserved is a landmine for the next reader:

- Rename to `test_index_page_renders_modalities_alphabetically`.
- Docstring: modalities render alphabetically on `/` regardless of the persisted
  `position` order.
- Keep `google/gemini-3.5-flash` as the fixture. It is the ideal witness: its
  persisted order (`Text, Images, Videos, Files, Audio`) differs from
  alphabetical (`Audio, Files, Images, Text, Videos`) in every position, so the
  test cannot pass by coincidence.
- Assert `"Audio, Files, Images, Text, Videos" in html`.
- Assert the old string `"Text, Images, Videos, Files, Audio" not in html`. This
  is what makes it fail before the change and pass after, satisfying t_b378287b's
  red-then-green deliverable.
- Update the trailing comment to state the persisted order *and* the rendered
  order, so the divergence is documented at the point a future reader meets it.

Coverage is not lost. The assertion that `position` governs persistence moves
nowhere — it already lives at the layer that owns it,
`tests/test_models.py:46-48` and `tests/test_admin_models.py:283-308`, both
untouched. What changes is only the claim about what `/` displays.

Recorded as `D-009`.

`tests/test_models_listing.py:74-90` (`test_index_page_uses_bounded_query_count`,
`assert query_count == 3`) is unaffected: a template filter issues no SQL.

## 7. Question 5 — scope

### Decision: `/` only. The admin form is **out of scope and already correct** — do not card it.

`app/templates/admin/models.html:35,45` loops `modalities`, but that variable is
supplied by `app/routes/admin.py:217`:

```python
return render_template("admin/models.html", modalities=sorted(ALLOWED_MODALITIES))
```

It is **already sorted alphabetically**, and unlike `/` it is sorted with
Python's case-sensitive `sorted()` — harmless because the vocabulary is
single-case capitalised (§5). The form renders
`Audio, Files, Images, Text, Videos`. There is no work to do and no follow-up
card to create. Suki's offer to card it separately should be declined.

Two related surfaces, for completeness, both out of scope:

- `app/static/js/admin-models.js:68-69` posts `input_content` /
  `output_content` in DOM checkbox order, i.e. alphabetical, which is then
  persisted as `position`. Nothing to change; noting it so nobody "fixes" the
  submission order later thinking it is display.
- `app/templates/admin/models.html:8` still contains copy that D-005 flagged for
  correction. Unrelated to this card. Do not touch it here.

## 8. Implementation summary for t_b378287b

Exactly two files change.

1. `app/templates/index.html:28-29` — insert `| sort` before the existing
   `| join(', ')` on both the input and output cells.
2. `tests/test_models_listing.py:64-71` — rename and rewrite per §6.

Do not touch: `app/models/ai_model.py`, `app/routes/main.py`,
`app/routes/admin.py`, `app/commands.py`, `tests/test_models.py`,
`tests/test_admin_models.py`, `migrations/`.

No Alembic revision. No new dependency. No JavaScript.

Verification: the renamed test fails at `47bf79f` and passes after step 1; then
full `pytest` green. Per AGENTS.md §4 and workflow v2, commit on a dedicated
branch including this document, push, open a PR, comment findings on the ticket,
and complete it — do not block as review-required.

---

## §A — Assumptions taken

1. **The sort is presentation-only, implemented as a Jinja `| sort` filter in
   `app/templates/index.html`.** The domain model, the relationship ordering and
   the `position` column are all left as they are.
   *Reversal cost:* trivial. Delete two filter tokens from one template to
   restore persisted-order display. Moving the sort down into the properties or
   the relationship `order_by` later is a larger change and would then meet the
   §B test on its own; see §3(b)/(c) for the enumerated blast radius.
   → `D-008` (`ASSUMED`)

2. **`position` is retained despite becoming unobservable in the UI, and no
   retirement card is created.**
   *Reversal cost:* one Alembic revision dropping two `NOT NULL` columns, plus
   edits to `app/routes/admin.py:285-300`, `app/commands.py:84-99`,
   `app/models/ai_model.py:68,84,126,134` and three test files — plus permanent
   loss of the existing order data, since `PK(ai_model_id, modality_id)` leaves
   no tiebreaker once the column is gone. Needs an operator ruling before anyone
   starts.
   → `D-008` (`ASSUMED`)

3. **`tests/test_models_listing.py:64-71` is renamed to
   `test_index_page_renders_modalities_alphabetically` and re-pointed at the
   alphabetical string, per the exact shape in §6.** Persisted-order coverage is
   unaffected and stays at `tests/test_models.py:46-48` and
   `tests/test_admin_models.py:283-308`.
   *Reversal cost:* revert one test function alongside the template change. They
   move together.
   → `D-009` (`ASSUMED`)

4. **No case-folding sort key and no case-insensitivity test.** Jinja's `| sort`
   is case-insensitive by default; the closed capitalised vocabulary
   (`app/commands.py:37`, `D-001`) makes the behaviour unreachable in production
   data anyway.
   *Reversal cost:* nil for the behaviour — it is already correct. If the sort is
   ever moved to Python, `key=str.casefold` becomes mandatory to preserve it.
   → `D-010` (`ASSUMED`)

5. **`app/templates/admin/models.html` is out of scope; it is already
   alphabetical via `sorted(ALLOWED_MODALITIES)` at `app/routes/admin.py:217`.**
   *Reversal cost:* none. This is a statement of verified fact, not a choice.
   → `D-011` (`ASSUMED`, documentary)

## §B — Decisions required (BLOCKING)

**None.** This document hands off.

Recorded here because the absence is the load-bearing conclusion, not an
oversight. The §B triggers Suki flagged on the card were each checked and each
avoided by the choice in §3:

- *API request/response contract* — untouched. Option (a) does not modify the
  properties, and there is no JSON surface exposing modality lists in any case
  (§3(b)).
- *Schema / migration* — untouched. `position` stays (§4); a retirement proposal
  is deliberately withheld pending a ruling that nothing currently needs.
- *Role / permission model* — not in contact with this change. `/` is public per
  `D-004`; `updater` is unaffected per `D-007`.
- *Changing a pinned test* — one test changes (§6,
  `tests/test_models_listing.py:64-71`), and it is the one whose assertion the
  operator's request directly contradicts. No alternative answer exists, so it
  fails the §B test of "a different answer would change X". Authorised in §6
  with its replacement written out in full, and paired with an explicit
  do-not-touch on `tests/test_models.py:46-48`.
- *Shipped work with an open PR* — none of the two touched files is in flight.

Judgement call, stated so it can be overruled: had option (b) or (c) been chosen
this would have been a decision brief instead of a spec. Option (a) was chosen
partly *because* it keeps the change inside §A, and that is a legitimate reason
to prefer it — the alternatives cost an operator round-trip and buy no behaviour
the operator asked for.
