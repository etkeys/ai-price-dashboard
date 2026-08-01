# Research: Authentication for the Web Interface — Gap Analysis and Plan

- **Task:** t_3eb0e09b — Research authentication mechanism for web interface
- **Author:** Chip (architect)
- **Date:** 2026-07-30
- **Repo state at time of writing:** `main` @ `6c2144e`
- **Supersedes nothing.** Extends `_research/2607301109_api-key-auth-design.md`
  (the API-key auth design, hereafter "the auth spec").
- **Downstream cards:** t_9a4f66f4 (Dale, implement), t_9cb478fc (Dale, admin
  add-model), t_fa175a0e (Kova, review), t_d3b3414f (Suki, root)

---

## 0. Executive summary — read this before anything else

**The authentication mechanism has already been researched, implemented,
reviewed, and merged.** It landed on `main` as commit `6c2144e` (PR #5,
merged 2026-07-31T00:04Z), roughly twelve hours before this card was created.
The card body's premise — "the README hints at authentication capability but no
visible way" — was accurate when the parent card `t_d3b3414f` was written, and
is now only *half* accurate.

What exists today, working and tested (98 tests passing):

- Opaque token authentication (`apdk` API keys, `apds` session tokens,
  `apdr` recovery keys), SHA-256 stored, `kid`+secret two-step lookup.
- Two roles, `updater` < `administrator`, with a `require_role` decorator.
- Four tables (`api_keys`, `auth_sessions`, `recovery_keys`, `auth_events`)
  behind Alembic migration `248f2949289c`.
- HTTP surface: `POST/DELETE /auth/session`, `GET /auth/whoami`,
  `POST /auth/recovery/claim`, and `/admin/keys` CRUD.
- CLI: `flask auth bootstrap | create-key | list-keys | revoke-key |
  recovery-key | reap-sessions`.
- README documentation of all of the above.

What does **not** exist, and is therefore the entire remaining scope of the
"authentication for the web interface" work:

> **There is no browser-facing UI.** Zero. `base.html` has a bare `<header>`
> with an `<h1>` and nothing else. `app/static/js/dashboard.js` is still the
> two-line `console.log` placeholder. A human opening `http://127.0.0.1:5000`
> has no button to click, no form to fill, and no way to discover that
> authentication exists at all. Every capability above is reachable only via
> `curl` or the CLI.

So the answer to "which authentication method fits the existing architecture"
is **already decided and already built** — Option C from the auth spec §3.2,
tab-scoped session tokens in `sessionStorage`, sent as `Authorization: Bearer`.
Re-litigating that choice would throw away merged, reviewed, working code.

**The recommendation of this note is therefore:** do not design a new
authentication mechanism. Build the missing client layer on top of the one
that is already there. Section 4 below is the concrete plan for Dale.

### 0.1 A terminology correction the implementer must internalize

The downstream card t_9a4f66f4 asks for "a login page, session management, and
an administrator role." Two of those three already exist. The third —
"login page" — needs its meaning pinned down, because the naive reading
conflicts with the merged design:

| Card says | What it must mean here | Why |
|---|---|---|
| "login page" | A page where you paste an **API key**, not a username+password form | There are no users and no passwords in the schema. `api_keys` has `name` and `role`; there is no `password_hash` column anywhere. |
| "session management" | Already built server-side (`auth_sessions`, absolute + idle bounds, revocation). Missing: the **client half** that stores the token and attaches it to requests. | See auth spec §3.3–3.4 |
| "administrator role" | Already built (`ROLE_ADMINISTRATOR`, `require_role`, rank-ordered). Missing: **UI that reflects it** — showing/hiding admin affordances. | See auth spec §4 |

If Dale builds a username/password login form, he will be adding a second,
parallel, unreviewed authentication system to a codebase that already has one.
That is the single largest risk on this card and it must be called out
explicitly in the implementation ticket.

---

## 1. Evidence: what is actually in the tree

Verified by direct inspection at `6c2144e`, not inferred.

### 1.1 Files that exist and are wired in

```
app/auth/__init__.py            exports auth_bp, require_role
app/auth/decorators.py    273L  require_role, get_principal, /auth/* views, throttling
app/services/auth_service.py 457L  token gen/parse, resolve_principal, key + session lifecycle
app/models/auth.py        195L  ApiKey, AuthSession, RecoveryKey, AuthEvent
app/routes/admin.py       202L  /admin/keys CRUD, administrator-gated
app/commands.py                 flask auth <subcommands>
migrations/versions/248f2949289c_add_auth_tables.py
tests/test_auth.py        611L
tests/test_recovery.py    178L
```

`create_app()` registers `main_bp`, `auth_bp`, and `admin_bp`. Confirmed by
enumerating `app.url_map`:

```
GET     /                            main.index
GET     /health                      main.health
POST    /auth/session                auth.create_session
DELETE  /auth/session                auth.delete_session
GET     /auth/whoami                 auth.whoami
POST    /auth/recovery/claim         auth.claim_recovery
GET     /admin/keys                  admin.list_keys
POST    /admin/keys                  admin.create_key
GET     /admin/keys/<kid>            admin.get_key
DELETE  /admin/keys/<kid>            admin.delete_key
POST    /admin/keys/<kid>/revoke     admin.revoke_key
```

Note what is absent from that map: **there is not a single HTML page route
other than `/`.** No `/login`, no `/admin` shell, nothing.

### 1.2 Config knobs already present

`app/config.py` carries, all env-overridable:

| Setting | Default | Meaning |
|---|---|---|
| `AUTH_SESSION_ABSOLUTE_LIFETIME` | 43200 (12h) | hard cap from creation |
| `AUTH_SESSION_IDLE_TIMEOUT` | 3600 (60m) | killed if unused this long |
| `AUTH_SESSION_TOUCH_INTERVAL` | 60 | `last_seen_at` write throttle |
| `AUTH_RECOVERY_KEY_LIFETIME` | 900 (15m) | recovery key validity |
| `AUTH_EXCHANGE_MAX_ATTEMPTS` | 10 | throttle bucket size |
| `AUTH_EXCHANGE_WINDOW_SECONDS` | 300 | throttle window |

The client layer needs no new config. It consumes `expires_at` from the
`POST /auth/session` response.

### 1.3 The client-side vacuum

`app/templates/base.html` in full is 21 lines: doctype, head with one
stylesheet, `<header><h1>AI Price Dashboard</h1></header>`, a content block, a
footer, and a `<script>` tag pulling `dashboard.js`.

`app/static/js/dashboard.js` in full:

```js
// Placeholder for dashboard interactivity.
console.log('AI Price Dashboard loaded.');
```

That is the whole of the frontend. The auth spec §5.4 anticipated exactly this
work and described it — it simply was not built, because the three
implementation cards (t_41ffd8b1, t_2543e6da, t_e03fda36) were all scoped to
the backend.

---

## 2. Why the existing mechanism is the right one to keep

Restating the auth spec's reasoning is not the job of this note, but the
implementer and reviewer need enough to avoid second-guessing it mid-build.
Short version, with the reasons that bear specifically on the UI work:

1. **No passwords means no password surface.** No reset flow, no hashing
   parameter tuning, no credential-stuffing target, no email dependency. For a
   single-operator internal dashboard this is the correct trade.
2. **The credential travels in a header, not a cookie.** It is therefore not
   ambient, so CSRF is *structurally* absent — a cross-site form post cannot
   carry it. This is the property that lets the admin add-model form
   (t_9cb478fc) ship without CSRF token machinery or a Flask-WTF dependency.
   **It is also the constraint Dale is most likely to break** — see §5.1.
3. **`sessionStorage` is genuinely tab-scoped**, delivering the
   "closing the tab logs me out" behaviour honestly. Flask's signed-cookie
   session cannot: browsers resurrect session cookies on session-restore.
4. **Agents and humans hit the same resolver.** A scraper presents `apdk`
   directly; a browser presents `apds`. One `resolve_principal`, one decorator,
   one set of tests.
5. **It is merged and Kova approved it twice** (t_4c8f0a5a on the
   implementation, t_489c77fe on the cleanup refactor). The marginal value of
   an alternative would have to exceed the cost of discarding that.

### 2.1 Alternatives, and why not now

| Alternative | Verdict |
|---|---|
| Username/password + Flask-Login | Rejected. Requires a `users` table, password hashing, a second auth path alongside the merged one, and reintroduces CSRF. Adds a dependency. Solves no problem the operator has stated. |
| OAuth / OIDC (Google, GitHub) | Rejected for now. Requires an external IdP, client secrets, callback URLs, and network egress from a container that currently needs none. Sensible *later* if the dashboard gains multiple human users; overkill for one operator. |
| Flask signed-cookie session as primary | Rejected in auth spec §3.2 Option A. Browser-scoped not tab-scoped, session-restore resurrects it, and it makes CSRF protection mandatory. |
| HTTP Basic auth at the reverse proxy | Not comparable — gives no role model, no per-key revocation, no audit trail, and cannot express "administrator vs updater". Fine as a *defence-in-depth* layer on top; not a substitute. |

The one open question from the auth spec §11.1 — tab-scoped vs browser-scoped —
was resolved by implementation. Reversing it now is expensive and there is no
stated reason to.

---

## 3. What the browser cannot do, and the consequence

This is the crux of the UI design and the part most likely to be got wrong.

**A top-level browser navigation cannot carry an `Authorization` header.** When
the user types a URL, clicks a link, or submits a `<form method="post">`, the
browser controls the request headers. There is no mechanism by which the
`sessionStorage` token can be attached to that request.

Three consequences follow, and all three are non-negotiable:

1. **Page routes cannot be role-gated server-side.** A `@require_role`
   decorator on an HTML page route would 401 every legitimate visitor, because
   the browser will never send the token on the navigation that fetches it.
2. **Protected pages must render as empty shells.** The HTML is public; the
   *data* is not. The shell loads, its JavaScript reads the token from
   `sessionStorage`, and `fetch`es the protected endpoint with the header. An
   anonymous visitor gets the shell and a 401 from the fetch — which leaks
   nothing, because the shell contains no data.
3. **Mutating actions must go through `fetch`, never `<form method="post">`.**
   A server-rendered form post cannot carry the token. This directly shapes
   t_9cb478fc's add-model form: it is a `<form>` element for layout and
   validation semantics, but its submit handler must `preventDefault()` and
   issue a `fetch` with the header.

The auth spec §5.4 states all three. They are repeated here because they are
the failure mode that will otherwise burn a review cycle.

---

## 4. The plan

Five work items. They are ordered by dependency. Items A–D constitute
t_9a4f66f4; item E is the handoff surface for t_9cb478fc.

### A. A shared auth client module — `app/static/js/auth.js` (new)

The single place that knows about the token. Everything else calls into it.

Responsibilities:

- `getToken()` / `setToken(token, meta)` / `clearToken()` — read and write
  `sessionStorage` under one key (suggest `apd.session`). Store the
  `{name, role, expires_at}` metadata alongside so the header can render
  without a `/auth/whoami` round trip on every page load.
- `authFetch(url, options)` — a `fetch` wrapper that injects
  `Authorization: Bearer <token>` when a token is present, sets
  `Content-Type: application/json` for bodies, and **centrally handles 401**
  by clearing the token and re-rendering the header as signed-out. Every
  protected call in the app goes through this function; no bare `fetch` to a
  protected endpoint anywhere.
- `signIn(apiKey)` — `POST /auth/session` with `{"key": …}`, store the returned
  token and metadata on 201, surface a uniform error otherwise.
- `signOut()` — `DELETE /auth/session` through `authFetch`, then `clearToken()`
  **regardless of the response**. Server-side revocation is the authority, but
  a network failure must not leave a token sitting in storage.
- `currentPrincipal()` — the cached `{name, role}` or `null`.
- `isAdministrator()` — role check for UI gating. **Cosmetic only.** The server
  is the authority; this exists so admin buttons do not appear for updaters.

Hard rules for this module:

- The API key is passed to `signIn()` and immediately discarded. It is **never**
  written to `sessionStorage`, `localStorage`, a cookie, a `window` property, or
  `console`. Only the exchanged `apds` session token is persisted.
- Never `console.log` a token, a key, or a response body that contains either.

### B. Header auth control — `app/templates/base.html`

Add a control region to the existing `<header>`, rendered by `auth.js` on
`DOMContentLoaded`:

- **Signed out:** an "Authenticate" button that reveals the sign-in affordance
  (item C).
- **Signed in:** the key `name`, its `role`, and a "Sign out" button.

Server-side this is inert — the template ships an empty container div and the
JS fills it. The server does not know whether the visitor is authenticated when
it renders the page (see §3), so it must not try to.

Also add a `{% block scripts %}` to `base.html` so per-page scripts can be
injected without every page loading every script. `auth.js` must load *before*
`dashboard.js` and before any page script that calls `authFetch`.

### C. The sign-in affordance — a page or a dialog

Two viable shapes; **recommend the modal dialog**, with the standalone page as
an acceptable alternative if Dale finds the dialog fiddly.

| | Modal dialog in `base.html` | Standalone `/login` page |
|---|---|---|
| Route needed | none | `GET /login` on `main_bp`, public |
| Redirect-after-login | not needed — you stay where you are | needs handling, and "where to go back to" is state to carry |
| Discoverability | good — one click from anywhere | good |
| Effort | lower | slightly higher |

Recommendation: a `<dialog>` element in `base.html` containing a single
password-type input for the API key and a submit button, opened by the
"Authenticate" control. Use `type="password"` so the key is not shoulder-surfed
and not captured by browser autofill history. Submit handler calls
`auth.signIn()`.

If a standalone page is chosen instead, it is a public route with no
`@require_role` — for the reasons in §3.

Error handling in either shape: on a 401 from `POST /auth/session`, display a
**uniform** "Invalid key" message. Do not distinguish "unknown kid" from "bad
secret" from "revoked" from "expired" — the server already returns a uniform
401 and the UI must not undo that. On 429, surface "Too many attempts, try
again later" and honour the `Retry-After` header by disabling the submit button
for that duration.

### D. Key management page — `GET /admin/keys` (HTML) + `app/static/js/admin-keys.js`

The auth spec §5.4 calls for this and it is the natural proof that the whole
mechanism works from a browser.

**Routing conflict to resolve first.** `/admin/keys` is currently taken by the
JSON API (`admin.list_keys`, GET). Three options, in order of preference:

1. **Content negotiation on the existing route** — return HTML when the
   `Accept` header prefers `text/html` (i.e. a browser navigation), JSON
   otherwise. Clean URL, no new route. Slight subtlety in that the view now has
   two shapes; the HTML branch must be **outside** the `@require_role`
   decorator's protection or it will 401 the navigation (§3). That makes the
   decorator placement awkward and is the reason this is only *narrowly*
   preferred.
2. **Separate page route** — `GET /admin/keys/manage` (public shell) rendering
   the page, with the existing JSON API untouched at `/admin/keys`. Simplest to
   reason about, cleanest separation of shell from data, and the decorator story
   stays trivial. **This is the pragmatic pick** if option 1's decorator
   gymnastics prove ugly in review.
3. Move the JSON API under `/admin/api/keys`. Rejected — it is a documented,
   merged, README-published surface and breaking it churns docs and any script
   already using it.

Dale should take option 2 unless he can make option 1 clean. Either way the
page shell is public and the data behind it is not.

Page contents, all driven through `authFetch`:

- A table of keys from `GET /admin/keys`: `name`, `role`, `status`
  (active/expired/revoked — the API already derives this), `created_at`,
  `last_used_at`, `expires_at`, `kid`.
- A create form → `POST /admin/keys` with `{name, role, expires_at?}`. On 201,
  display the returned plaintext token **once**, prominently, with an explicit
  "this will not be shown again" warning and a copy button. Do not persist it
  anywhere. Re-render the table afterwards.
- A revoke control per row → `DELETE /admin/keys/<kid>`. Confirm before firing.
  Handle 409 (self-revoke attempt) with the server's message rather than a
  generic failure.
- Anonymous or non-admin visitors get the shell plus a 401/403 from the fetch;
  render "Administrator access required" in place of the table. This is
  acceptable and leaks nothing.

Link this page from the header, visible only when `isAdministrator()` — again,
cosmetic gating only.

### E. Handoff surface for the add-model card (t_9cb478fc)

Not this card's work, but the contract must be stated so the next card does not
reinvent it:

- The add-model endpoint should be `POST /models` (or `/admin/models` if it
  belongs with the other admin surfaces — Dale's call, but be consistent) and
  must carry `@require_role(ROLE_UPDATER)`. Model editing is an *updater*
  capability; administrator inherits it via rank. Gating model creation at
  `administrator` would make the `updater` role vestigial and contradict the
  README, which already promises updaters "can perform mutating actions on
  model data (once those endpoints exist)."

  **Note the tension:** the parent card t_d3b3414f says "an administrator should
  have the ability to add a model." Under the rank model an administrator *does*
  have that ability if the gate is `updater`. Dale should gate at `updater` and
  Kova should accept that as satisfying the requirement. If the operator
  genuinely wants model-editing restricted to administrators only, that is a
  policy decision that should be raised rather than assumed.
- The form is a `<form>` for markup and native validation, but its submit
  handler calls `preventDefault()` and posts via `authFetch`. **Not** a
  server-rendered form post (§3).
- Its "all-or-nothing optional attributes" rule (name required; `price_in`,
  `price_out`, `context_tokens`, modalities either all present or all absent)
  must be enforced **server-side**. Client-side validation is a courtesy, not a
  control.

---

## 5. Pitfalls — the specific ways this goes wrong

### 5.1 The CSRF trap (highest risk)

If Dale reaches for `flask.session` or a cookie to hold auth state "because it
is easier for page routes", the entire CSRF-immunity property evaporates and
every mutating endpoint silently becomes vulnerable. The auth spec §3.5 is
explicit: *"Do not use `flask.session` for auth state at all. If a cookie
session exists for unrelated reasons (flash messages), it must carry no
authority."*

**Kova's check:** confirm no protected endpoint accepts a cookie as proof of
identity. `resolve_principal` must remain the only path to a `Principal`, and it
must read only the `Authorization` header.

### 5.2 Building a second auth system

Covered in §0.1. If a `users` table, a `password_hash` column, or a
`Flask-Login` import appears in the diff, the card has gone off the rails.

### 5.3 Leaking secrets to the client

- The API key must never land in `sessionStorage` — only the exchanged session
  token.
- The one-time plaintext token from `POST /admin/keys` must not be logged,
  stored, or re-fetchable. It is displayed once and then gone.
- No token in `console.log`, in a URL query string, or in an error message
  rendered to the page.

### 5.4 Trusting client-side role checks

`isAdministrator()` hides buttons. It does not protect anything. Every protected
endpoint keeps its `@require_role`. A reviewer should be able to delete
`auth.js` entirely and find the server still fully defended.

### 5.5 Session expiry handled only at sign-in

The session has both an absolute cap (12h) and an idle timeout (60m). A tab left
open overnight will hold a token that the server has already stopped honouring.
`authFetch`'s central 401 handler must clear the stale token and flip the header
to signed-out rather than leaving the UI claiming an authenticated state that
no longer exists.

### 5.6 Guarding the page shell instead of the data

Putting `@require_role` on an HTML page route produces a page that nobody can
ever load. See §3. Guard the endpoints; leave the shells public.

---

## 6. Files touched

New:

```
app/static/js/auth.js              shared token store + authFetch + sign-in/out
app/static/js/admin-keys.js        key management page behaviour
app/templates/admin/keys.html      key management shell (extends base.html)
tests/test_web_auth.py             route/shell tests for the new page routes
```

Modified:

```
app/templates/base.html            header auth control, sign-in dialog, {% block scripts %}
app/static/css/style.css           header control region, dialog, key table styling
app/routes/admin.py                page shell route (or Accept negotiation on /admin/keys)
README.md                          "Browser sessions" section: describe the actual UI
```

Explicitly **not** touched — this card adds no backend auth logic:

```
app/services/auth_service.py
app/models/auth.py
app/auth/decorators.py
app/config.py
migrations/
```

If Dale finds himself editing any file in that second list, he should stop and
say why, because the backend was reviewed and approved and this card was not
scoped to change it.

## 7. Libraries

**None.** No new dependency is required or wanted.

- No Flask-Login — there are no users or passwords.
- No Flask-WTF / CSRF — structurally unnecessary (§2.2), and adding it would
  imply cookie auth was in play.
- No frontend framework. This is a handful of `fetch` calls and some DOM
  manipulation against a table. Vanilla ES6 matches the existing
  zero-build-step, single-static-file frontend. Introducing a bundler here would
  cost more than the feature.

`pyproject.toml` and `requirements.txt` should come out of this card unchanged.

---

## 8. Acceptance criteria

For Dale to self-check and Kova to verify on t_fa175a0e.

**Sign-in flow**

1. An anonymous visitor to `/` sees an "Authenticate" control in the header.
2. Activating it presents an API-key input; the input is `type="password"`.
3. Submitting a valid `apdk.…` key results in a signed-in header showing the
   key's `name` and `role`.
4. Submitting an invalid, revoked, or expired key shows one uniform
   "Invalid key" message — no distinction between failure causes.
5. Exceeding the throttle shows a rate-limit message and disables submission for
   the `Retry-After` duration.
6. After sign-in, `sessionStorage` contains the `apds.…` session token and
   **not** the `apdk.…` API key. Verified in DevTools.
7. Nothing in `localStorage`; no auth cookie set.

**Session behaviour**

8. Opening a second tab to `/` shows signed-out. (Tab-scoped, by design.)
9. Closing the tab and reopening shows signed-out.
10. "Sign out" clears `sessionStorage` **and** the server-side row — a captured
    token replayed with `curl` after sign-out returns 401.
11. A stale/expired token triggers exactly one 401, after which the UI shows
    signed-out rather than a phantom authenticated state.

**Key management page**

12. Reachable from the header only when the principal is an administrator.
13. Loads for an anonymous visitor as a shell with an "Administrator access
    required" message and no key data. No 500, no traceback.
14. An `updater` principal gets 403 from the data fetch and the same message.
15. An administrator sees all keys with name, role, status, and timestamps.
16. Creating a key displays the plaintext token exactly once with an explicit
    warning; reloading the page does not show it again.
17. Revoking a key updates its status to revoked; the revoked key immediately
    fails authentication.
18. Attempting to revoke the key backing the current session returns 409 and the
    server's message is surfaced.

**Security invariants**

19. No new dependency in `pyproject.toml` or `requirements.txt`.
20. `git diff` shows no changes to `auth_service.py`, `models/auth.py`, or
    `decorators.py` beyond what a page-shell route requires.
21. No protected endpoint accepts a cookie as proof of identity.
22. No token or key appears in any `console.log`, URL, or rendered error.
23. No `<form method="post">` targets a protected endpoint.
24. Every protected page route is public; every protected *data* endpoint keeps
    its `@require_role`.

**Regression**

25. `.venv/bin/python -m pytest` passes — currently 98 tests, all green at
    `6c2144e`. New tests added for the page shells.
26. `GET /health` remains unauthenticated and returns `{"status": "ok"}`.
27. `GET /` still renders the model listing for anonymous visitors. The
    dashboard is public; only mutation is gated.

---

## 9. Open questions for the operator

Non-blocking — Dale can proceed with the stated defaults — but worth a decision.

1. **Should `/` stay public?** Currently anyone can read the model listing.
   That has been true since the project started and nothing in the cards asks
   to change it. Assumed: yes, stays public.
2. **Modal dialog or `/login` page?** §4C recommends the dialog. Either is
   defensible; the dialog avoids redirect-after-login state.
3. **Model editing gated at `updater` or `administrator`?** §4E recommends
   `updater` (administrator inherits). The parent card's wording could be read
   either way. If updaters should *not* be able to add models, the `updater`
   role has no purpose at all and should be reconsidered wholesale.
4. **Is 60 minutes of idle timeout right for the operator's habits?** It is a
   config value, trivially changed, but a dashboard left open on a second
   monitor will log itself out over lunch.
