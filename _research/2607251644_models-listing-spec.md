# Spec: AI Models Listing on "/" — Data Model & UI Approach

Task: t_b3dbbc7c (chip). Parent feature: t_86b34886 — "Navigating to `/` should show
a listing of AI models and various attributes. Use sample data for now."

Downstream: t_87b347e4 (Dale — sample data file), then implementation + Kova QA.

---

## 0. Source of truth: the mockup

The attached mockup (`home page initial mockup.png` on t_86b34886) is a
spreadsheet-style grid (looks like a Google Sheet). It shows a single flat table
of AI models, one row per model, with per-column filter affordances. There are no
cards, no logos, no charts, no pagination visible — just a dense sortable/filterable
table.

### Columns as drawn (left → right)

| # | Header (as shown) | Example values | Notes |
|---|-------------------|----------------|-------|
| A | **Model Name**    | `anthropic/claude-haiku-4.5`, `openai/gpt-5.5`, `z-ai/glm-5.2` | `vendor/model-slug` form. This is the natural unique key. |
| B | **Price In**      | `1.00`, `0.09`, `5.00` | Numeric, 2 decimals. Input token price. |
| C | **Price Out**     | `5.00`, `0.18`, `30.00` | Numeric, 2 decimals. Output token price. |
| D | **Context Size**  | `200K`, `1M`, `66K`, `262K` | Displayed as a human string (K/M suffix). |
| E | **Input Content** | `Text`, `Text, Images, Files`, `Text, Images, Files, Videos, Audio` | Multi-valued modality list. |
| F | **Output Cont[ent]** | `Text`, `Text, Images` | Multi-valued modality list. |

Every column header carries a **filter icon**, implying the design intent is a
filterable/sortable table. For this iteration ("use sample data for now") we implement
the table and leave client-side filter/sort as a documented follow-up (see §6) unless
Dale finds it cheap to include.

### Units — decided (mockup shows no unit label)

The mockup shows bare numbers for Price In / Price Out. Industry-standard convention
for this kind of table (and what these magnitudes match) is **USD per 1 million tokens**.
Adopt that: store the numeric value, render with a `$` prefix and a column subtitle /
tooltip "USD per 1M tokens". This must be stated once in the UI so the number is not
ambiguous. Confirm with operator if wrong, but do not block on it — the assumption is
documented and easily changed in one place.

---

## 1. Data model

### 1.1 This iteration uses SAMPLE DATA — no DB

The task explicitly says "use sample data for now". The app already wires up
SQLAlchemy (`app/extensions.py`, `app/models/`), but we deliberately DO NOT touch the
DB for this feature. No new SQLAlchemy model, no migration. The listing reads from a
static in-repo Python module. This keeps the change small and reversible and matches
the task constraint.

Rationale for a Python module over raw JSON: the app is server-rendered Flask/Jinja
(no JS build, no TypeScript — the sibling task's "TypeScript object" phrasing is
boilerplate from the auto-decomposer and does not apply here). A Python module is
import-time validated, needs no file IO in the request path, and is trivial to swap for
a DB query later.

### 1.2 The record shape (canonical field definitions)

Each model is a dict with these keys. Dale should treat this as the contract.

```
name            str    required. "vendor/model-slug", unique. Sort key A→Z default.
price_in        float  required. USD per 1M input tokens. >= 0. 2-decimal display.
price_out       float  required. USD per 1M output tokens. >= 0. 2-decimal display.
context_tokens  int    required. Raw context window in TOKENS (e.g. 200000, 1000000).
input_content   list[str]   required, non-empty. Ordered modality labels.
output_content  list[str]   required, non-empty. Ordered modality labels.
```

Key design decisions:

- **Store context as a raw int (`context_tokens`), not the display string.**
  `200K`/`1M` is a formatting concern. Storing the int keeps the data sortable and
  lets one helper own the humanization. `1M` = 1000000, `200K` = 200000,
  `66K` = 66000, `262K` = 262000.
- **Store modalities as lists, not comma strings.** The mockup renders them
  comma-joined, but the underlying data is a set of discrete modalities. Lists make
  future per-modality filtering (the filter icon in column E/F) trivial and let the
  template own the joining. Allowed modality vocabulary observed in the mockup:
  `Text`, `Images`, `Files`, `Videos`, `Audio`. Preserve mockup ordering per row.
- **No `id` field.** `name` is the unique key and there is no DB. Adding a synthetic id
  now would be dead weight.
- **`vendor` is derivable** from `name.split("/")[0]`. Do not store it separately; a
  Jinja/helper expression covers any grouping-by-vendor need later.

### 1.3 Display-formatting helpers

Formatting lives in the presentation layer, not the data. Provide two small pure
helpers (put them in `app/utils/helpers.py` alongside `safe_get`, or a new
`app/utils/formatting.py` — Dale's call, but keep them unit-testable and importable):

- `format_context(context_tokens: int) -> str`
  - `>= 1_000_000` → strip trailing `.0`, suffix `M` (1_000_000 → "1M",
    1_500_000 → "1.5M").
  - `>= 1_000` → suffix `K` (200_000 → "200K", 66_000 → "66K", 262_000 → "262K").
  - else → the bare int as a string.
- `format_price(value: float) -> str` → always 2 decimals, e.g. `f"{value:.2f}"`
  ("1.00", "0.09", "30.00"). The `$` and unit note are template concerns.

Modality lists are joined in the template with `{{ row.input_content | join(', ') }}`
— no helper needed.

---

## 2. Sample data file (contract for Dale's t_87b347e4)

- **Location:** `app/data/sample_models.py` (create `app/data/__init__.py` too).
  A dedicated `data` package signals "static seed data", separate from `models`
  (SQLAlchemy) and `services` (logic).
- **Public symbol:** `SAMPLE_MODELS: list[dict]` — a module-level constant, ordered
  the same as the mockup (alphabetical by `name`, which is how the mockup is sorted).
- **Contents:** transcribe ALL 22 rows from the mockup verbatim. Full list, with
  context stored as raw token ints:

  ```
  anthropic/claude-haiku-4.5      1.00   5.00   200000   [Text,Images,Files]                    [Text]
  anthropic/claude-opus-4.8       5.00  25.00  1000000   [Text,Images,Files]                    [Text]
  anthropic/claude-sonnet-5       2.00  10.00  1000000   [Text,Images,Files]                    [Text]
  deepseek/deepseek-v4-flash      0.09   0.18  1000000   [Text]                                 [Text]
  deepseek/deepseek-v4-pro        0.44   0.87  1000000   [Text]                                 [Text]
  google/gemini-2.5-flash-lite    0.10   0.40  1000000   [Text,Images,Files,Videos,Audio]       [Text]
  google/gemini-3.1-flash-lite    0.25   1.50  1000000   [Text,Images,Files,Videos,Audio]       [Text]
  google/gemini-3.1-flash-lite-image  0.25  1.50  66000  [Text,Images]                          [Text,Images]
  google/gemini-3.5-flash         1.50   9.00  1000000   [Text,Images,Videos,Files,Audio]       [Text]
  google/gemini-3.5-flash-lite    0.30   2.50  1000000   [Text,Images,Files,Videos,Audio]       [Text]
  google/gemini-3.6-flash         1.50   7.50  1000000   [Text,Images,Files,Videos,Audio]       [Text]
  minimax/minimax-m3              0.30   1.20  1000000   [Text,Images,Videos]                   [Text]
  moonshotai/kimi-k2.6            0.66   3.41   262000   [Text,Images]                          [Text]
  moonshotai/kimi-k2.7-code       0.72   3.50   262000   [Text,Images]                          [Text]
  moonshotai/kimi-k3              3.00  15.00  1000000   [Text,Images]                          [Text]
  openai/gpt-5.5                  5.00  30.00  1000000   [Text,Images,Files]                    [Text]
  openai/gpt-5.6-luna-pro         1.00   6.00  1000000   [Text,Images,Files]                    [Text]
  openai/gpt-5.6-sol-pro          5.00  30.00  1000000   [Text,Images,Files]                    [Text]
  openai/gpt-5.6-terra-pro        2.50  15.00  1000000   [Text,Images,Files]                    [Text]
  qwen/qwen3.7-max                1.48   4.43  1000000   [Text]                                 [Text]
  qwen/qwen3.7-plus               0.32   1.28  1000000   [Text,Images]                          [Text]
  z-ai/glm-5.2                    0.93   3.00  1000000   [Text]                                 [Text]
  ```

  This set already covers the "various cases" the sibling task asks for: cheapest
  (deepseek-v4-flash 0.09/0.18) and priciest (gpt-5.5 / gpt-5.6-sol-pro 5/30), the full
  modality range (Text-only through five-modality Gemini), non-1M context values
  (200K, 66K, 262K), and the only multi-modal-output row
  (gemini-3.1-flash-lite-image). No need to invent extra rows.

- **No logic in the data module** — pure data. Import-time it must be a plain list of
  dicts.

---

## 3. Route / context wiring

Modify the existing index route in `app/routes/main.py`:

```
from app.data.sample_models import SAMPLE_MODELS

@main_bp.route("/")
def index():
    return render_template("index.html", models=SAMPLE_MODELS)
```

- Keep the default sort as the data's natural order (alphabetical by name = mockup
  order). Do NOT re-sort in the route.
- `/health` is untouched.
- No new blueprint, no new route. The listing IS the home page per the parent task.
- No routing/navigation additions — the mockup is a single screen. Detail pages,
  vendor pages, etc. are out of scope.

---

## 4. UI component hierarchy (Jinja templates)

Server-rendered, extends existing `base.html`. `base.html` already provides the
`<header><h1>AI Price Dashboard</h1></header>` that the existing test asserts on —
do not remove it. Hierarchy:

```
base.html                         (unchanged: header, main block, footer, css/js hooks)
└── index.html                    (rewrite the content block)
    └── section.models-listing
        ├── h2  "Models"          (optional heading + one-line unit note:
        │                          "Prices in USD per 1M tokens")
        └── table.models-table
            ├── thead > tr
            │     Model Name | Price In | Price Out | Context Size |
            │     Input Content | Output Content
            └── tbody
                └── {% for m in models %} tr  (one row per model)
                      td.model-name      {{ m.name }}
                      td.price.num       ${{ format_price(m.price_in) }}
                      td.price.num       ${{ format_price(m.price_out) }}
                      td.context         {{ format_context(m.context_tokens) }}
                      td.modalities      {{ m.input_content | join(', ') }}
                      td.modalities      {{ m.output_content | join(', ') }}
```

Decisions:

- **One template, one partial macro optional.** A `_model_row.html` macro is nice-to-have
  but not required for 22 static rows; inline `for` loop is fine. Dale's discretion.
- **Making `format_context`/`format_price` callable in Jinja:** register them as
  template globals or a context processor in the app factory, OR pre-format in the
  route by mapping `SAMPLE_MODELS` into display dicts. Prefer a **context processor /
  Jinja global** so the raw data stays raw and the template owns display. Either is
  acceptable; do not pre-format inside the data module.
- **Numeric columns right-aligned** (Price In, Price Out, Context) to match the
  spreadsheet look; text columns left-aligned.
- **Empty state:** `{% if not models %}` → a "No models available." row. Cheap
  insurance; the sample set is never empty but the template should not assume it.

---

## 5. Styling (minimal, matches existing style.css)

Add a `.models-table` block to `app/static/css/style.css` (extend, don't rewrite the
existing `:root`/base rules):

- `width: 100%; border-collapse: collapse;`
- `th, td { padding: .5rem .75rem; border-bottom: 1px solid #dee2e6; text-align: left; }`
- `thead th { background: var(--header-bg); color: var(--header-text); position: sticky; top: 0; }`
  (sticky header optional — matches the frozen-header feel of the sheet).
- `.num { text-align: right; font-variant-numeric: tabular-nums; }`
- zebra striping `tbody tr:nth-child(even) { background:#fff; }` optional.
- Responsive: wrap the table in `.table-scroll { overflow-x: auto; }` so 6 columns
  don't break on narrow screens. Do NOT attempt a card reflow — out of scope.

No JS required for this iteration. `dashboard.js` stays the placeholder.

---

## 6. Explicitly OUT OF SCOPE (document, don't build)

The mockup's per-column filter icons imply future interactivity. For THIS task:

- **Filtering / sorting / search** — not built. Data is server-rendered in fixed
  (alphabetical) order. Follow-up: client-side sort+filter in `dashboard.js`, or
  query-param driven server sort. Flag as a separate card if the operator wants it.
- **Database persistence** — not built (sample data only, per task).
- **Vendor logos / grouping, detail pages, pagination, currency toggle** — none of
  these appear in the mockup; do not add.
- **Real price fetching** — `PriceService` remains a placeholder; not wired to this view.

---

## 7. Testing guidance (for Dale + Kova)

Existing `tests/test_main.py::test_index_page` asserts `/` is 200 and body contains
`AI Price Dashboard` — must keep passing (satisfied by `base.html` header). Add:

- `GET /` renders a `<table>` and contains a known model name
  (e.g. `anthropic/claude-opus-4.8`) and its formatted context (`1M`).
- Row count in `<tbody>` equals `len(SAMPLE_MODELS)` (22).
- Unit tests for `format_context` (1_000_000→"1M", 200_000→"200K", 66_000→"66K",
  1_500_000→"1.5M") and `format_price` (1→"1.00", 0.09→"0.09").
- `SAMPLE_MODELS` integrity: every record has all 6 keys, prices are numbers >= 0,
  `context_tokens` is a positive int, modality lists are non-empty and drawn only from
  the allowed vocabulary {Text, Images, Files, Videos, Audio}.

Run `pytest` (project verify command) — full suite must stay green.

---

## 8. Change summary for the implementer (t_87b347e4 → Dale)

New files:
- `app/data/__init__.py`
- `app/data/sample_models.py`      (the 22-row `SAMPLE_MODELS` list — Dale's card)

Modified files:
- `app/routes/main.py`             (pass `models=SAMPLE_MODELS` to the template)
- `app/templates/index.html`       (rewrite content block → table)
- `app/static/css/style.css`       (append `.models-table` styles)
- `app/utils/helpers.py` (or new `app/utils/formatting.py`)  (`format_context`, `format_price`)
- `app/__init__.py`                (register the two formatters as Jinja globals /
                                     context processor) — only if the template-global
                                     approach is chosen
- `tests/test_main.py` / new `tests/test_models_listing.py`  (tests per §7)

No DB migration. No new dependencies. No new routes.

Open question for operator (non-blocking): confirm price unit is "USD per 1M tokens".
Spec assumes yes and isolates the assumption to the unit-note text + `$` prefix.
