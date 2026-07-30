# Spec: API-Key Authentication, Roles, Key Lifecycle and Container Recovery

Task: t_f278cbbd (chip). Parent feature: t_d9f5dc09 — "Add authentication for
protected actions".

Downstream consumers of this document:

| Card | Assignee | Scope |
|---|---|---|
| t_41ffd8b1 | dale | Auth core: token format, hashing, resolver, session binding, role decorators, migration |
| t_2543e6da | dale | Administrator key management (create / list / revoke) |
| t_e03fda36 | dale | Container recovery flow + first-run bootstrap |
| t_4c8f0a5a | kova | Security and correctness review |

Related prior specs (still binding where they overlap):
`_research/2607281844_sqlite-persistence-spec.md` (Alembic owns DDL; models
imported in `create_app`; `/health` stays DB-free),
`_research/2607230701_health-endpoint-contract.md`,
`_research/2607232020_containerization-spec.md`.

This spec closes open question §7.2 of the persistence spec ("Admin/CRUD UI …
there is no auth in the app, so anything mutating would be unauthenticated").

---

## 0. Objective and constraints

### 0.1 Objective

Provide authentication for future mutating actions using API-key tokens instead
of usernames and passwords. Three principals must be served:

1. **Anonymous viewers** — the majority. They read `/` and never authenticate.
   Nothing about this design may add a login wall, a redirect, or a cookie
   requirement to the read path.
2. **Human updaters/administrators** — a handful. They browse anonymously, and
   when they want to perform a protected action they paste one key. They stay
   authenticated for the life of that browser tab.
3. **Automated agents** — a handful. They are non-interactive HTTP clients that
   present a key on every request and never hold a session.

### 0.2 Hard constraints discovered in the repo

1. **No new runtime dependencies.** Everything below is implementable with the
   already-declared stack. Verified installed in `.venv` (Python 3.11.15):
   Flask 3.1.3, Flask-SQLAlchemy 3.1.1, SQLAlchemy 2.0.51, Alembic 1.18.5,
   itsdangerous 2.2.0, Werkzeug 3.1.8, plus stdlib `secrets`, `hashlib`, `hmac`.
   Verified **not** installed: `PyJWT`, `argon2-cffi`, `bcrypt`. The design
   deliberately requires none of them (see §1.1 and §2.4). Do not add entries to
   `pyproject.toml` or `requirements.txt`.
2. **Alembic owns DDL.** One new revision, `down_revision = '637848f507e4'`.
   `db.create_all()` is for the test fixture only
   (`tests/conftest.py:15-19`). `render_as_batch` is already on
   (`migrations/env.py:96-97`), which matters for any later SQLite `ALTER`.
3. **No current protected action exists.** The parent card says so explicitly.
   This work delivers the *mechanism* plus the key-management surface, which is
   itself the first protected action. Do not build model-editing endpoints here;
   that is a separate card.
4. **`/health` must remain DB-free and unauthenticated.** `app/routes/main.py:27-30`,
   `README.md:77-90`, `Dockerfile:41-42` and `docker-compose.yml:22` all depend
   on it. It must not gain an auth check — the container healthcheck holds no key.
5. **`/` must remain unauthenticated.** `app/routes/main.py:13-24`.
6. **The existing template contract is untouched.** `app/templates/index.html`
   and `app/utils/helpers.py` are out of scope. Any auth UI is *additive*
   (`base.html` may gain a small controls region; see §5.4).
7. **`SECRET_KEY` already exists and is already mandatory in production**
   (`app/config.py:36-43`, `docker-compose.yml:13`). Reuse it; do not introduce a
   second secret env var (see §2.5).
8. **SQLite, two Gunicorn workers, one file on a named volume.**
   `docker-compose.yml:17-19`, `Dockerfile:47`. Every design choice that writes
   on a read path has to justify itself (see §6.6).

### 0.3 Non-goals

Out of scope, and Kova should reject them if they appear in the diff:

- Usernames, passwords, password reset, email, OAuth, SSO, MFA.
- User accounts as first-class entities. A key *is* the principal. "Who did
  this" resolves to a key name, not a person record.
- Per-record or per-field authorization. Roles are coarse (§4).
- More than two roles, arbitrary scope strings, or a permissions admin UI.
- Rotating a key in place. Rotation = create new, revoke old.
- Rate limiting as a general middleware. Only the auth-exchange endpoints get a
  throttle, and it is deliberately crude (§6.3).
- Multi-tenancy, key sharing, key delegation, refresh tokens.

---

## 1. Token format decision

### 1.1 Opaque random tokens, not JWT

**Decision: opaque high-entropy random strings, validated against the database.
Reject JWT.**

Rationale, in order of weight:

1. **Immediate revocation is an explicit acceptance criterion** (t_2543e6da:
   "revocation immediately invalidates the token"). A self-contained JWT is valid
   until it expires; making it revocable requires a server-side denylist checked
   on every request — i.e. the database round-trip that JWT exists to avoid. You
   pay JWT's complexity and keep the lookup. Net loss.
2. **JWT's advantage is statelessness across services.** There is exactly one
   service, and it already opens a DB session per request for the listing page.
   There is no horizontal scale story to preserve.
3. **Long-lived keys must be human-pasteable.** A signed JWT with claims is
   200–400+ characters and visually indistinguishable from noise. A verified
   sample opaque key from this design is 61 characters (§2.1). Updaters paste
   these by hand.
4. **No new dependency.** `PyJWT` is not installed. Hand-rolling JWS with
   `hmac` to avoid the dependency would be strictly worse than not using JWT.
5. **No key-rotation coupling.** Opaque tokens are not signed, so their validity
   does not depend on `SECRET_KEY`. Rotating `SECRET_KEY` (which today only
   affects Flask's cookie signing) does not invalidate every issued key. With
   JWT it would.
6. **Claims would be stale by construction.** A role embedded in a JWT survives
   a role change; a role read from the row does not.

The only genuine cost is one indexed SELECT per authenticated request. Measured
cost of the hash step is 0.51 µs (§2.4); the SELECT is a primary-key-adjacent
unique-index hit on a table expected to hold single-digit rows. Irrelevant.

### 1.2 Three token kinds, one mechanism

All three are opaque `kid`+`secret` pairs with a type prefix, differing only in
which table they live in and what they permit.

| Kind | Prefix | Table | Lifetime | Presented as |
|---|---|---|---|---|
| API key | `apdk` | `api_keys` | Until revoked (optional expiry) | `Authorization: Bearer` (agents) or once via `POST /auth/session` (humans) |
| Session token | `apds` | `auth_sessions` | Tab lifetime, hard-capped | `Authorization: Bearer` on every mutating fetch |
| Recovery key | `apdr` | `recovery_keys` | 15 min, single use | `POST /auth/recovery/claim` body |

A single parse-and-dispatch function handles all three, keyed on prefix. One code
path, three tables — this is the main reason the design stays small.

---

## 2. Token construction, storage, and validation

### 2.1 Wire format

```
<prefix> "." <kid> "." <secret>
```

- `prefix` — `apdk` | `apds` | `apdr`. Literal ASCII.
- `kid` — `secrets.token_urlsafe(9)` → 12 chars, 72 bits. A *public* lookup
  handle. Safe to log, safe to show in the admin list, safe to put in a URL.
- `secret` — `secrets.token_urlsafe(32)` → 43 chars, **256 bits**. Never stored,
  never logged, shown to a human exactly once.

Total length 4 + 1 + 12 + 1 + 43 = **61 characters**. Verified by construction.

**Pitfall — the delimiter must be `.`, not `_` or `-`.** Empirically verified:
`secrets.token_urlsafe()` emits the base64url alphabet, which *includes* both
`_` and `-` and *excludes* `.`. Splitting on `_` or `-`, or using `rsplit`, is
ambiguous and will intermittently mis-parse roughly 1 token in 2. Parse with
`token.split(".")` and require exactly 3 parts. This is a real, silent,
low-frequency bug generator; Kova should check for it specifically.

Parsing rules (all failures return the same generic 401, see §6.2):

1. `value = raw.strip()` first — pasted keys carry whitespace and newlines.
2. Reject if length is not exactly 61, before any DB work.
3. `parts = value.split(".")`; reject unless `len(parts) == 3`.
4. Reject unless `parts[0]` is a known prefix.
5. Reject unless `len(parts[1]) == 12` and `len(parts[2]) == 43`.

Step 2 makes the overwhelming majority of garbage input cost zero queries.

### 2.2 What is stored

Store `kid` in cleartext and `sha256(secret)` as 64 lowercase hex chars. Never
store the secret, never store the assembled token.

```
lookup:  SELECT ... FROM api_keys WHERE kid = :kid
verify:  hmac.compare_digest(row.secret_hash, sha256_hex(secret))
```

`kid` carries a `UNIQUE` constraint, so lookup is a single index seek.
Verification is a constant-time comparison — `hmac.compare_digest`, never `==`.

### 2.3 Why kid + secret rather than hashing the whole token

Hashing the entire token and looking up by hash also works and is one column
lighter. It is rejected because:

- The `kid` gives you a stable, non-secret identifier for logs, audit rows, the
  admin list, and revocation URLs. Without it you either expose a hash prefix
  (confusing) or the row `id` (fine, but then the audit trail cannot be
  correlated to what a client presented).
- A failed lookup by `kid` distinguishes "no such key" from "wrong secret"
  *internally*, which makes the audit log useful, while the HTTP response stays
  identical (§6.2).

### 2.4 Why SHA-256 and not Argon2/bcrypt/PBKDF2

**Decision: single-round SHA-256. This is correct here and is not the usual
password-hashing mistake.**

Slow KDFs exist to make brute force of *low-entropy human-chosen* secrets
infeasible. The secret here is 256 bits from `secrets.token_urlsafe`. There is no
dictionary, no pattern, and no realistic offline search. Adding a KDF buys
nothing and costs a great deal on a hot path:

Measured in this repo's `.venv`:

- `sha256` — **0.51 µs** per operation.
- `pbkdf2_hmac('sha256', …, 600_000)` — **215 ms** per operation.

215 ms per authenticated request, on a 2-worker Gunicorn, is a trivially
self-inflicted denial of service: an unauthenticated attacker posting garbage to
`POST /auth/session` would saturate both workers with ~10 requests/second.
`argon2` and `bcrypt` are additionally not installed (§0.2).

Kova: "they used SHA-256 for a credential" is normally a valid finding. It is
**not** a finding here, provided all three of these hold. Check them instead:

1. The secret is generated by `secrets.token_urlsafe(32)` or `secrets.token_bytes(32)`
   — not `random`, not `uuid4`, not `os.urandom` with a short length, not
   time-seeded, not user-supplied.
2. Comparison uses `hmac.compare_digest`.
3. No code path ever accepts a user-chosen or short key.

If any of those is violated, the SHA-256 choice becomes unsafe and the fix is to
fix the generator, not to add a KDF.

### 2.5 Why no HMAC pepper keyed on SECRET_KEY

Considered: `hmac_sha256(SECRET_KEY, secret)` instead of `sha256(secret)`, so a
stolen database is useless without the env var.

Rejected. The threat it defends against — offline recovery of secrets from stolen
hashes — is already impossible at 256 bits of entropy; a pepper defends a
non-existent weakness. In exchange it couples every issued key to `SECRET_KEY`,
so rotating that variable silently invalidates every key in the system with no
migration path and a confusing failure mode (all keys 401 at once). The current
config already treats `SECRET_KEY` as rotatable
(`app/config.py:36-43` only asserts non-empty). Keep the hash independent of it.

---

## 3. Session binding — "authenticated until I close the tab"

This is the requirement most likely to be implemented wrongly, so the options are
spelled out.

### 3.1 What the browser actually offers

| Mechanism | Scope | Cleared when | Readable by JS |
|---|---|---|---|
| Cookie with `Max-Age`/`Expires` | Whole browser profile | At expiry | No, if `HttpOnly` |
| Cookie without `Max-Age` ("session cookie") | Whole browser profile, **all tabs** | Browser process exits | No, if `HttpOnly` |
| `localStorage` | Origin, all tabs | Explicitly | Yes |
| `sessionStorage` | **Origin + tab** | **Tab closes** | Yes |

Only `sessionStorage` is genuinely tab-scoped. Verified relevant Flask behaviour:
a default Flask session emits `session=…; HttpOnly; Path=/` with no `Expires`
(i.e. a browser-session cookie), and `PERMANENT_SESSION_LIFETIME` defaults to
31 days but is only applied when `session.permanent` is set.

### 3.2 Options considered

**Option A — Flask signed-cookie session, non-permanent.** Put `kid` in
`session`, never set `session.permanent`. Simplest possible change.
Rejected as the primary mechanism:

- It is **browser**-scoped, not tab-scoped. Every tab in the profile is
  authenticated, which is not what was asked for.
- Chrome and Firefox "continue where you left off" / session-restore **resurrect
  session cookies** after the browser is closed. The user's mental model
  ("closing the tab logs me out") is then simply false, silently, on the most
  common browser configuration. That is a security-relevant lie.
- An ambient cookie credential means every mutating endpoint now needs CSRF
  protection, which is new machinery and a new dependency temptation
  (Flask-WTF).

**Option B — raw API key in `sessionStorage`, sent as a header per request.**
Genuinely tab-scoped. Rejected: it parks a long-lived, non-expiring, admin-grade
credential in JS-readable storage. One XSS or one malicious third-party script
and the attacker holds a permanent admin key that outlives the tab and cannot be
detected. The blast radius is unbounded in time.

**Option C (chosen) — exchange the API key for a short-lived, server-side,
individually revocable *session token*; hold that in `sessionStorage`.**

The API key is transmitted exactly once and never stored client-side. The thing
in `sessionStorage` is a distinct credential that is (a) tab-scoped by the
storage mechanism, (b) hard-capped in absolute lifetime, (c) revocable
server-side per session, and (d) automatically killed when its parent key is
revoked. XSS yields at most one bounded, observable, killable session.

Because the credential travels in an `Authorization` header rather than a cookie,
it is **not** ambient: a cross-site form post or image tag cannot carry it. CSRF
is structurally absent, and no CSRF token machinery is needed. This is the second
strongest argument for Option C and Kova should confirm the property holds
(i.e. that no protected endpoint also accepts the cookie session as proof).

### 3.3 The chosen flow

**Human, browser:**

1. Browses `/` anonymously. No cookie, no key, no session row.
2. Clicks "Authenticate", pastes `apdk.…` into a form.
3. JS `POST /auth/session` with `{"key": "apdk.…"}`.
4. Server validates the key (§2), creates an `auth_sessions` row, returns
   `{"token": "apds.…", "name": …, "role": …, "expires_at": …}`.
5. JS stores the token in `sessionStorage` **only**. Never `localStorage`, never
   a cookie, never a global `window` property.
6. Every protected request sends `Authorization: Bearer apds.…`.
7. Tab closes → `sessionStorage` is gone → the session token is unreachable. Its
   row lingers until it expires or is reaped (§5.3); this is harmless because the
   secret is unrecoverable.
8. "Sign out" issues `DELETE /auth/session`, which marks the row revoked
   server-side, then clears `sessionStorage`. Do not rely on the client-side
   clear alone.

**Agent, non-interactive:** presents `Authorization: Bearer apdk.…` on every
request. No `/auth/session` call, no session row, no state. An agent MUST NOT be
required to hold a session — that would force cookie/token juggling into shell
scripts for no benefit.

Both cases arrive at the same resolver (§3.5), which is the point.

### 3.4 Session lifetime parameters

Config-driven, on `Config` in `app/config.py`, so tests can shorten them:

| Setting | Default | Meaning |
|---|---|---|
| `AUTH_SESSION_ABSOLUTE_LIFETIME` | 12 hours | Hard cap from creation. Non-negotiable ceiling. |
| `AUTH_SESSION_IDLE_TIMEOUT` | 60 minutes | Killed if unused this long. |
| `AUTH_RECOVERY_KEY_LIFETIME` | 15 minutes | §7. |

A session is valid iff `revoked_at IS NULL` **and** `now < created_at + absolute`
**and** `now < last_seen_at + idle`. Both bounds are enforced in the resolver, not
only by the reaper — a stopped reaper must never extend a session.

### 3.5 Unified request resolver

One function, called from a decorator, never from view bodies:

```
resolve_principal(request) -> Principal | None
```

`Principal` is a frozen dataclass: `kind` (`"key" | "session"`), `kid`,
`api_key_id`, `name`, `role`. Order of operations:

1. Read `Authorization`. Require the literal scheme `Bearer ` (case-insensitive
   scheme per RFC 7235, single space). Absent or malformed → `None`.
2. Parse per §2.1. Unknown prefix → `None`.
3. `apdk` → validate against `api_keys`: row exists, secret matches,
   `revoked_at IS NULL`, `expires_at IS NULL OR expires_at > now`.
4. `apds` → validate against `auth_sessions` per §3.4, then load the parent
   `api_keys` row and re-check *it* is still live. **A revoked key must not be
   usable through a session it previously created** — this is the single most
   important correctness property in the whole design, and it must hold even if
   the cascade revoke in §5.2 fails or is skipped. Belt and braces: cascade on
   revoke *and* re-check on use.
5. `apdr` → **not accepted here.** Recovery keys are only ever redeemed by the
   dedicated endpoint in §7. The resolver must return `None` for `apdr` so a
   recovery key can never be used as a general bearer credential.
6. Refresh `last_seen_at`, throttled (§6.6).
7. Stash on `flask.g.principal` for the request; never on a module global.

Do not use `flask.session` for auth state at all. If a cookie session exists for
unrelated reasons (flash messages), it must carry no authority.

---

## 4. Roles and permission representation

### 4.1 Two roles, closed enum, stored as TEXT

`role` is `VARCHAR(16) NOT NULL` with `CHECK (role IN ('administrator','updater'))`.
Lowercase on the wire and in the DB; display capitalization is a template
concern.

Rejected: a `roles` table with a `permissions` join table. With two roles and a
handful of actions it is three extra tables, three extra joins, and an admin UI
nobody asked for, to express a two-element set. It also makes the closed
vocabulary open, which invites drift. This mirrors the reasoning that produced
the `modalities` closed vocabulary as a plain list in `app/commands.py:17` rather
than a configurable table.

Follow the existing precedent for a check constraint name:
`ck_api_keys_role_valid` (cf. `ck_ai_models_price_in_non_negative`,
`app/models/ai_model.py:138-142`).

### 4.2 Ordered capability, not a permission matrix

Administrator strictly supersedes Updater. Express it once:

```
ROLE_RANK = {"updater": 10, "administrator": 20}   # module-level, frozen
def has_role(actual: str, required: str) -> bool:
    return ROLE_RANK[actual] >= ROLE_RANK[required]
```

Numeric gaps are deliberate so an intermediate role can be inserted later
without renumbering. A third *non-hierarchical* role would invalidate this
model — that is an acceptable, documented limitation, not a defect.

Unknown role string → `KeyError`. Do **not** default to a role on lookup
failure. Fail closed, loudly, with a 500 and a log line: an unrecognized role in
the database is data corruption, not a permission decision.

### 4.3 The decorator

```
@require_role("updater")        # administrator passes too, via rank
@require_role("administrator")  # updater does not
```

Behaviour:

- No principal → `401` with `WWW-Authenticate: Bearer`.
- Valid principal, insufficient rank → `403`. Distinguishing 401 from 403 here
  leaks nothing an authenticated caller does not already know, and makes agent
  debugging tractable.
- Content negotiation: JSON body for API-ish requests, a rendered error page for
  `text/html`. Pick one helper and use it in both branches; do not duplicate the
  decision per view.

Rules Kova must enforce:

1. Every mutating endpoint (anything not GET/HEAD/OPTIONS) outside `/auth/session`
   and `/auth/recovery/claim` carries a `@require_role`. Test this
   **structurally** by walking `app.url_map` and asserting each such rule's view
   function has the decorator marker attribute — not by enumerating routes in a
   list that will rot. This is the only defence against the next developer
   forgetting.
2. No view calls `resolve_principal` itself and then decides. One gate.
3. No endpoint accepts a role from the request (query param, header, body). The
   role comes from the row, always.

---

## 5. Key lifecycle

### 5.1 Creation

Administrator-only: `POST /admin/keys` with `{"name": …, "role": …,
"expires_at": … | null}`.

- `name` — 1–64 chars after strip, required, human-meaningful
  ("erik-laptop", "price-scraper-bot"). Used in audit output.
- Uniqueness: **unique among non-revoked keys only.** Verified compilable on
  SQLite 3.53.1 in this repo:
  `CREATE UNIQUE INDEX uq_api_keys_active_name ON api_keys (name) WHERE revoked_at IS NULL`
  (SQLAlchemy: `Index(..., unique=True, sqlite_where=text("revoked_at IS NULL"))`).
  Verified behaviour: many revoked rows may share a name; a second *active* row
  with the same name is rejected with `IntegrityError`. This is what allows
  "revoke and reissue under the same name" without either colliding or
  destroying history. A plain `UNIQUE(name)` would force operators to invent
  `erik-laptop-2`, and Kova should flag it if that is what lands.
- Server generates `kid` and `secret`; response contains the assembled 61-char
  token **exactly once**. There is no endpoint that can retrieve it again. Say so
  in the response payload and in the UI copy.
- `created_by_key_id` → the acting key's `id`, nullable (a CLI- or
  recovery-created key has no acting key). This is the provenance chain.
- Handle the `IntegrityError` on duplicate active name and return `409`, not a
  500.

### 5.2 Revocation

`POST /admin/keys/<kid>/revoke`, Administrator-only.

- Sets `revoked_at = now`. **Never delete the row** — deleting destroys the
  audit trail and frees the name and `kid` for reuse.
- In the same transaction, mark every `auth_sessions` row for that key revoked.
- Idempotent: revoking an already-revoked key returns `200`, not `409`. Retries
  and double-clicks must not error.
- Effective immediately, because validation reads the row on every request. No
  cache, no TTL, no in-process memo. If anyone adds a caching layer here, the
  "immediate" acceptance criterion is broken — Kova should look for exactly that.
- **An Administrator must not revoke the key they are currently authenticated
  with.** Reject with `409` and a clear message. Without this guard the last
  admin can lock everyone out with one click and the only way back is §7. Being
  able to lock yourself out is not a feature.
- There is no un-revoke. The forward path is: create a new key.

### 5.3 Listing, expiry, reaping

- `GET /admin/keys` returns `kid`, `name`, `role`, `created_at`, `created_by`
  (name of the creating key, or `null`), `last_used_at`, `expires_at`,
  `revoked_at`, and a derived `status` of `active | expired | revoked`. It
  **never** returns `secret_hash`. Kova: assert on the serialized payload keys,
  not on a hand-written response, so an added column cannot leak silently.
- Optional `expires_at` on a key supports "contractor gets 30 days". Enforced in
  the resolver (§3.5 step 3), not by a background job.
- Reaping expired `auth_sessions` rows: a `flask auth reap-sessions` command,
  safe to run from cron or by hand. Explicitly **not** wired into the request
  path and **not** required for correctness — expiry is enforced on read. It is
  hygiene only. Do not add a scheduler dependency for this.

### 5.4 UI surface

Minimal and additive. `base.html` gains a header control region: an
"Authenticate" affordance, and once authenticated the key name, role, and a
"Sign out" button. A `/admin/keys` page rendering the list plus a create form,
reachable only with an administrator session.

Because the credential lives in `sessionStorage` and travels as a header, these
pages must drive their calls through `fetch` from
`app/static/js/dashboard.js` (currently a 2-line placeholder). Server-rendered
`<form method="post">` will **not** carry the token and must not be used for
protected actions. This is a direct consequence of choosing Option C and Dale
should not fight it.

The `/admin/keys` page HTML itself may render for an anonymous visitor as an
empty shell whose `fetch` calls 401 — that is acceptable and leaks nothing.
Guard the data endpoints, not the shell. Do not attempt to guard page routes
with the header credential; the browser will not send it on a top-level
navigation.

---

## 6. Security properties, hardening, and pitfalls

### 6.1 Never log or echo a secret

- No raw token in logs, exception messages, audit rows, or error responses.
- Log `kid` only. That is what `kid` is for.
- Auth material must arrive in a header or a JSON body — **never** a query
  string. Query strings land in access logs, `Referer` headers, and browser
  history. Reject any implementation that accepts `?key=`.
- Set `Cache-Control: no-store` on every auth and admin response.

### 6.2 Uniform failure

Every authentication failure — bad length, bad parse, unknown `kid`, wrong
secret, revoked, expired — returns the identical `401` body and, ideally,
comparable timing. Do not distinguish "no such key" from "wrong secret" to the
caller. Internally, do record the distinction in the audit table; that is where
the operator gets signal.

### 6.3 Throttling the exchange endpoints

`POST /auth/session` and `POST /auth/recovery/claim` are the only
unauthenticated write endpoints, so they are the brute-force surface. At 256 bits
of entropy, guessing is not the threat; resource exhaustion is.

Minimum viable, no new dependency: an in-process, per-remote-address fixed-window
counter (e.g. 10 attempts / 5 minutes) → `429` with `Retry-After`.

Be honest about the limits, in a code comment: it is **per worker** (2 workers →
effectively 2× the limit) and resets on restart. That is acceptable because it
is defence-in-depth, not the primary control. Do **not** promote this to a
DB-backed limiter — that turns a flood into write contention on SQLite, which is
worse than the flood. If real rate limiting is ever needed it belongs at the
reverse proxy.

### 6.4 Transport

Bearer tokens in headers are only as safe as the channel. `docker-compose.yml`
publishes plain HTTP on `8000:8000`. The deployment therefore **must** sit behind
a TLS-terminating reverse proxy or on a trusted overlay network (the GHA workflow
already implies Tailscale — see `_research/2607272058_gha-build-publish-spec.md`).
State this in `README.md`. This design cannot enforce it, and pretending
otherwise would be dishonest: on plain HTTP over an untrusted network, every key
is sniffable and none of the above matters.

### 6.5 Audit trail

New table `auth_events`, append-only, no updates, no deletes:
`created_at`, `event` (`auth_success | auth_failure | key_created | key_revoked |
session_created | session_revoked | recovery_issued | recovery_claimed`),
`kid` (nullable), `actor_key_id` (nullable), `remote_addr`, `detail` (short
text, **no secrets**).

Cheap, and the only way to answer "was that key used before I revoked it".
`remote_addr` must come from `request.remote_addr`; if a proxy is in front,
either configure `ProxyFix` deliberately or record the direct peer and say so —
do **not** trust a raw `X-Forwarded-For` header.

### 6.6 SQLite write amplification on the read path — real, must be mitigated

Refreshing `last_seen_at` and `last_used_at` turns authenticated GETs into
writers. On a single SQLite file with 2 workers in the default rollback-journal
mode, writers take an exclusive lock and readers block. Two mitigations, both
required:

1. **Throttle the refresh.** Only write when the stored timestamp is older than
   `AUTH_TOUCH_INTERVAL` (default 60s). Idle timeout is 60 minutes; 60-second
   granularity is ample. This collapses per-request writes to at most one per
   minute per principal.
2. **Write `auth_events` for failures and lifecycle events, not for every
   success.** Logging `auth_success` on every request reintroduces exactly the
   problem. Recommended: record `auth_success` only when a session is created,
   and rely on the throttled `last_used_at` for ongoing activity.

Additionally note — `PRAGMA journal_mode=WAL` is **not** currently set; only
`foreign_keys=ON` is (`app/__init__.py:8-16`). WAL would materially improve
reader/writer concurrency now that writes appear on read paths. It is a
one-line, database-wide, persistent change with its own container/volume
implications (extra `-wal`/`-shm` files on the named volume), so it is called out
here as a **recommendation for a separate card**, not smuggled into this one.
Dale: do not add it as a drive-by.

### 6.7 Timestamp consistency

Existing columns use `server_default=func.now()`, and SQLite's
`CURRENT_TIMESTAMP` yields **naive UTC** (`app/models/ai_model.py:108-118`,
`migrations/versions/637848f507e4…:27-28`). Python-side writes must match:
`datetime.datetime.now(datetime.UTC).replace(tzinfo=None)`. Mixing an
aware-local `datetime.now()` with these columns produces comparisons that are
wrong by the UTC offset — which for expiry logic means sessions that live hours
too long or die instantly. Centralize this in one `_utcnow()` helper and use it
everywhere; do not scatter `datetime.now()` calls.

### 6.8 Threat model summary

| Threat | Mitigation | Residual |
|---|---|---|
| Guessing a key | 256-bit secret; uniform 401; throttle | None material |
| Offline attack on stolen DB | 256-bit entropy makes hashes useless | None material |
| Stolen long-lived key | Named keys + immediate revocation + audit | Detection is manual |
| XSS in the dashboard | Only a short-lived, revocable session token is in JS reach; API key never stored | Session-lifetime abuse |
| CSRF | Header credential, not ambient; no cookie authority | None, if §3.2 holds |
| Network sniffing | Out of scope; requires TLS/overlay (§6.4) | Real on plain HTTP |
| Privilege escalation | Role read from row; rank check in one gate; role never client-supplied | None, if §4.3 holds |
| Lockout | Recovery flow (§7) + self-revoke guard (§5.2) | Requires container access |
| Recovery abuse | Container-only issuance, 15 min, single use, single capability | Container access ⇒ game over anyway |

---

## 7. Container recovery and first-run bootstrap

Two distinct problems that share machinery. Both live in t_e03fda36.

### 7.1 Bootstrap: the very first Administrator key

A fresh volume has zero keys, so `POST /admin/keys` can never be called. Solve it
explicitly rather than with a hardcoded default (which would be the worst
possible outcome — a shipped default admin credential).

`flask auth bootstrap`:

- If any non-revoked `administrator` key exists → print a message, **exit 0**,
  change nothing. Idempotent, exactly like `flask seed`
  (`app/commands.py:42-44`).
- Otherwise create one named `bootstrap` and print the 61-char token to stdout,
  clearly framed as shown-once.

Wire it into `docker-entrypoint.sh` after `flask seed`, so a first boot leaves the
key in `docker compose logs`. This matches the established pattern of doing
single-process setup in the entrypoint before Gunicorn, and inherits the existing
`set -e` and `exec` semantics
(`docker-entrypoint.sh:7-11`, and see the persistence spec §5.5 — both are
load-bearing).

Document plainly in `README.md` that the bootstrap key is in the container logs,
that logs are not a secret store, and that the operator should create a personal
key and revoke `bootstrap`.

### 7.2 Recovery: short-lived key that mints an Administrator key

The requirement is specifically that someone with container access can produce a
key that lets *a user, in a browser* create a new Administrator key. That is why
a CLI that directly creates an admin key is insufficient — the two people may be
different, and the browser user should end up holding a key nobody had to paste
over a chat channel.

`flask auth recovery-key`:

- Creates a `recovery_keys` row: `kid`, `secret_hash`,
  `expires_at = now + 15 min`, `consumed_at = NULL`.
- Prints `apdr.<kid>.<secret>` once.
- Invalidates any outstanding unconsumed recovery key first, so at most one is
  live at a time. Two live recovery keys is two chances to leak one.
- Logs `recovery_issued` to `auth_events`.

`POST /auth/recovery/claim` with `{"recovery_key": "apdr.…", "name": …}`:

1. Parse and validate against `recovery_keys`: exists, secret matches,
   `consumed_at IS NULL`, `expires_at > now`.
2. In **one transaction**: set `consumed_at = now`, create an `administrator`
   key with the requested name and `created_by_key_id = NULL`, write
   `recovery_claimed`.
3. Return the new 61-char `apdk.…` token once.
4. Any failure → generic `401`, and the recovery key is **not** consumed
   (otherwise a typo burns it and the operator has to go back into the
   container).

Single-use must be enforced by the database, not by application ordering: mark
consumed with a conditional update (`UPDATE … SET consumed_at = :now WHERE id = :id
AND consumed_at IS NULL`) and require `rowcount == 1` before proceeding. Two
concurrent claims must yield exactly one new admin key. Kova should test this
concurrently, or at minimum assert the guarded-update shape — a read-then-write
here is a genuine race.

Constraints that make this safe:

- Recovery keys are **only** accepted by this one endpoint. The general resolver
  rejects the `apdr` prefix outright (§3.5 step 5). A recovery key can therefore
  do exactly one thing: mint one administrator key. It cannot read, cannot
  update models, cannot list or revoke keys.
- Issuance requires shell access to the running container — a capability that
  already implies full control of the database and the process, so this adds no
  new privilege. It is a *convenience over* an existing capability, which is the
  correct framing for the review.
- 15 minutes is short enough that a leaked recovery key is near-worthless and
  long enough to paste into a browser.

`POST /auth/recovery/claim` must be reachable from the browser, i.e. it is a
normal route on the normal port. Attempting to bind it to localhost-only inside
the container would defeat its purpose (the browser is not in the container).
The security boundary is *issuance* (container-only) plus the 15-minute
single-use window — **not** network reachability of the claim endpoint. t_e03fda36's
phrasing "an endpoint only exposed locally" should be read as applying to
issuance, which the CLI satisfies; Dale should not try to network-restrict the
claim route.

---

## 8. Schema

One Alembic revision, `down_revision = '637848f507e4'`. Naming follows the
existing conventions (`ck_<table>_<rule>`, `ix_<table>_<col>`, `uq_<table>_<rule>`).

```
api_keys
    id                  INTEGER PK autoincrement
    kid                 VARCHAR(12)  NOT NULL UNIQUE            -- ix_api_keys_kid (unique)
    secret_hash         VARCHAR(64)  NOT NULL                   -- sha256 hex
    name                VARCHAR(64)  NOT NULL
    role                VARCHAR(16)  NOT NULL                   -- ck_api_keys_role_valid
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
    created_by_key_id   INTEGER      NULL FK -> api_keys.id ON DELETE SET NULL
    last_used_at        DATETIME     NULL
    expires_at          DATETIME     NULL
    revoked_at          DATETIME     NULL
    CHECK (role IN ('administrator','updater'))                 -- ck_api_keys_role_valid
    CHECK (length(kid) = 12)                                    -- ck_api_keys_kid_length
    CHECK (length(secret_hash) = 64)                            -- ck_api_keys_secret_hash_length
    UNIQUE INDEX uq_api_keys_active_name ON (name) WHERE revoked_at IS NULL

auth_sessions
    id                  INTEGER PK autoincrement
    kid                 VARCHAR(12)  NOT NULL UNIQUE            -- ix_auth_sessions_kid (unique)
    secret_hash         VARCHAR(64)  NOT NULL
    api_key_id          INTEGER      NOT NULL FK -> api_keys.id ON DELETE CASCADE
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
    last_seen_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
    expires_at          DATETIME     NOT NULL                   -- created_at + absolute lifetime
    revoked_at          DATETIME     NULL
    INDEX ix_auth_sessions_api_key_id ON (api_key_id)

recovery_keys
    id                  INTEGER PK autoincrement
    kid                 VARCHAR(12)  NOT NULL UNIQUE            -- ix_recovery_keys_kid (unique)
    secret_hash         VARCHAR(64)  NOT NULL
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
    expires_at          DATETIME     NOT NULL
    consumed_at         DATETIME     NULL

auth_events
    id                  INTEGER PK autoincrement
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
    event               VARCHAR(32)  NOT NULL
    kid                 VARCHAR(12)  NULL
    actor_key_id        INTEGER      NULL FK -> api_keys.id ON DELETE SET NULL
    remote_addr         VARCHAR(64)  NULL
    detail              VARCHAR(255) NULL
    INDEX ix_auth_events_created_at ON (created_at)
```

Notes:

- `kid` is `UNIQUE` per table, not globally. The prefix disambiguates the table,
  so a collision across tables is not a collision. 72 bits makes within-table
  collision negligible; still, handle the `IntegrityError` by regenerating rather
  than 500-ing.
- `PRAGMA foreign_keys=ON` is already enforced for every connection
  (`app/__init__.py:8-16`), so `ON DELETE CASCADE` on `auth_sessions` is real.
  It is a safety net only — nothing in this design deletes `api_keys` rows (§5.2).
- `created_by_key_id` is a **self-referential FK**. Declare it carefully with
  SQLAlchemy 2.0 typed `Mapped` style to match `app/models/ai_model.py`, and
  expect `render_as_batch` to matter if it is ever altered.
- Place these in a new `app/models/auth.py` and export from
  `app/models/__init__.py` (currently `app/models/__init__.py:3-5`). The
  `create_app` import of `app.models` (`app/__init__.py:29`) then populates
  `db.metadata` for autogenerate — see the persistence spec §5.4 for why that
  ordering is load-bearing.
- Suggested module layout, mirroring existing structure:
  `app/models/auth.py`, `app/services/auth_service.py` (generation, hashing,
  validation, lifecycle — no Flask imports beyond `current_app` config reads),
  `app/auth/decorators.py` (`require_role`, resolver, `flask.g` wiring),
  `app/routes/auth.py` + `app/routes/admin.py` (blueprints registered in
  `create_app` next to `main_bp` at `app/__init__.py:48-50`),
  `app/commands.py` (extend `register_commands` with an `auth` command group).

---

## 9. HTTP surface

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/session` | none (throttled) | API key → session token |
| DELETE | `/auth/session` | session | Sign out; revoke this session row |
| GET | `/auth/whoami` | key or session | `{name, role, kind, expires_at}` |
| GET | `/admin/keys` | administrator | List keys (never hashes) |
| POST | `/admin/keys` | administrator | Create named key; returns token once |
| POST | `/admin/keys/<kid>/revoke` | administrator | Revoke; cascades sessions |
| POST | `/auth/recovery/claim` | recovery key (throttled) | Mint one administrator key |

CLI (`flask auth …`): `bootstrap`, `create-key --name --role [--expires-days]`,
`list-keys`, `revoke-key <kid>`, `recovery-key`, `reap-sessions`.

The CLI subcommands are not merely convenience — they are the break-glass path
when the HTTP surface is unreachable, and they are how t_e03fda36's acceptance
criteria are demonstrated. `list-keys` and `revoke-key` in particular let an
operator with container access recover without minting anything new.

Status codes: `200` success, `201` on key creation, `400` malformed body,
`401` auth failure (uniform), `403` insufficient role, `404` unknown `kid` on
revoke (administrator-only endpoint, so this leaks nothing), `409` duplicate
active name or self-revoke attempt, `429` throttled.

---

## 10. Acceptance criteria

Definition of done across the three implementation cards, and Kova's checklist
for t_4c8f0a5a.

**Token and storage**
1. Secrets come from `secrets.token_urlsafe(32)`; `kid` from
   `secrets.token_urlsafe(9)`. No `random`, no `uuid`, no user-supplied secrets.
2. No column, log line, audit row, or response body anywhere contains a raw
   secret. Grep the diff, and assert on serialized payload keys.
3. Verification uses `hmac.compare_digest`, never `==`.
4. Parsing splits on `.` and requires exactly 3 parts; a token containing `_` or
   `-` in either component round-trips correctly. **Include a regression test with
   a hardcoded token whose `kid` and `secret` both contain `_` and `-`.**
5. Length is checked before any DB query; malformed input costs zero queries.

**Resolver and roles**
6. `apdk` (agent) and `apds` (browser session) both authenticate; `apdr` is
   rejected by the general resolver.
7. A revoked key fails immediately — same request, no restart, no cache flush.
8. A session created by a key that is *later* revoked fails, **with the cascade
   revoke disabled in the test**, proving the resolver re-checks the parent.
9. An expired key, an absolutely-expired session, and an idle-expired session all
   fail via the resolver with the reaper never run.
10. `updater` gets `403` on every administrator endpoint; `administrator` passes
    `@require_role("updater")`.
11. A structural test walks `app.url_map` and asserts every non-GET/HEAD/OPTIONS
    rule outside the two unauthenticated exchange endpoints is role-gated.
12. Role is never read from request input. Verified by inspection and by a test
    that posts `{"role": "administrator"}` alongside an updater credential and
    still gets `403`.

**Unchanged behaviour**
13. `GET /` returns 200 with all 22 models for a client sending no credential.
14. `GET /health` returns 200 with no credential, touches no table, and remains
    byte-identical to `main`.
15. `app/templates/index.html`, `app/static/css/style.css`,
    `app/utils/helpers.py` unchanged.
16. No new entries in `pyproject.toml` or `requirements.txt`.
17. `create_app()` performs no DDL and no INSERT (persistence spec §6.8 still
    holds).

**Lifecycle**
18. Administrator creates a named key with a chosen role; the plaintext appears
    exactly once and is unrecoverable thereafter.
19. Two active keys cannot share a name (`409`); a revoked key's name is reusable;
    the revoked row survives.
20. Revoke is idempotent (`200` twice) and kills that key's sessions.
21. An administrator cannot revoke the key backing their own session (`409`).
22. `GET /admin/keys` payload contains no `secret_hash` and no `id`-only opacity
    problems — `kid`, `name`, `role`, `status` present.

**Recovery and bootstrap**
23. `flask auth bootstrap` on an empty DB prints one administrator token; run
    again it prints an already-bootstrapped message and **exits 0**.
24. The entrypoint runs bootstrap after `flask seed`; a first `docker compose up`
    leaves a usable admin token in the logs. Demonstrate against a fresh volume.
25. `flask auth recovery-key` prints an `apdr.…` token; issuing a second one
    invalidates the first.
26. Claiming it yields a working administrator key; claiming the *same* recovery
    key a second time fails; claiming after `expires_at` fails.
27. A failed claim (bad secret / wrong name validation) does **not** consume the
    recovery key.
28. Single-use is enforced by a guarded `UPDATE … WHERE consumed_at IS NULL` with
    a `rowcount` check, not read-then-write.
29. An `apdr` token presented as `Authorization: Bearer` to any other endpoint
    gets `401`.

**Migration and suite**
30. Exactly one new Alembic revision, `down_revision = '637848f507e4'`, creating
    the four tables with the constraints and indexes in §8, including the partial
    unique index. Verify with `sqlite3 <db> ".schema"`.
31. `flask db upgrade` then `flask db migrate` produces an **empty** diff, proving
    models and migration agree (the standing mitigation for the fixture using
    `create_all()` — persistence spec §6.11).
32. Full suite green via `.venv/bin/python -m pytest`. Baseline at the time of
    writing is **38 passed**. New tests are additive; no existing test may be
    deleted or weakened.
33. `README.md` documents: the two roles, obtaining the first key, creating and
    revoking keys, how an agent authenticates (`Authorization: Bearer`), the
    recovery procedure, the tab-scoped session model, and the TLS requirement
    from §6.4.

---

## 11. Open questions (non-blocking, flagged for the operator)

1. **Tab-scoped vs browser-scoped.** Option C is genuinely tab-scoped: a second
   tab must authenticate again. If Erik would rather authenticate once per
   browser, that is Option A's behaviour and it is a smaller build — but it
   loses the close-the-tab guarantee and reintroduces CSRF. Confirm the
   preference before t_41ffd8b1 starts; it is the one decision here that is
   expensive to reverse afterwards.
2. **12 hour / 60 minute session bounds.** Guesses. They are config values, so
   changing them is trivial, but the defaults should reflect the operator's
   habits.
3. **WAL mode** (§6.6) — recommended follow-up card, deliberately not bundled.
4. **Key expiry as policy.** The column and enforcement exist; no policy forces
   expiry. Consider a default `--expires-days` for agent keys later.
5. **Nothing is protected yet.** After this lands, the only role-gated actions
   are key management itself. The model-editing endpoints that motivated the
   parent card are a separate card and can now be written safely.
6. **No notification on suspicious auth.** `auth_events` records failures but
   nothing surfaces them. A "repeated 401s" alert is a future card.
7. **Backups now matter more.** The persistence spec's open question §7.4 is
   sharper once the DB holds credentials: losing the volume means losing every
   key, and recovery then requires container access (§7). Same recommendation,
   higher stakes.
