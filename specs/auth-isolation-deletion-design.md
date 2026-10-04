# Design: Authentication, Per-User Isolation, and Account Deletion

How the resume-conjurer web app moves from one local workspace to many signed-in users whose
data is isolated, deletable, and exportable. It builds on `PRODUCT.md`, `web/BACKEND.md`, and
`main` as of `e108c44` (PR #32 merged: onboarding, uploads, document history, finals, exports).

**Related:** #22 (release gate: "resolve per-user identity, storage, authorization, and isolation").

**Scope:** design only. Implementation follows in separate PRs, one per phase.

Line references are to `main` at `e108c44`, relative to `web/app/` unless stated.

---

## Contents

1. [Context and goals](#1-context-and-goals)
2. [What multi-tenancy actually touches](#2-what-multi-tenancy-actually-touches)
3. [Authentication](#3-authentication)
4. [Sessions and CSRF](#4-sessions-and-csrf)
5. [Per-user storage](#5-per-user-storage)
6. [Per-user runtime state](#6-per-user-runtime-state)
7. [Containing the agent](#7-containing-the-agent)
8. [Cost and abuse controls](#8-cost-and-abuse-controls)
9. [Account deletion](#9-account-deletion)
10. [Data export](#10-data-export)
11. [Adopting the existing local workspace](#11-adopting-the-existing-local-workspace)
12. [Deployment](#12-deployment)
13. [Threat model](#13-threat-model)
14. [Phased plan](#14-phased-plan)
15. [Decisions taken and questions left](#15-decisions-taken-and-questions-left)

---

## 1. Context and goals

Today the app is one user, one workspace, one application:

- No authentication or sessions.
- `SLUG = "globex-staff-platform"` is hardcoded at `main.py:40`.
- `CONJURER_WORKSPACE` names the single workspace (`deps.py:30-43`).
- Every adapter is built once, at import, against that workspace (`main.py:379-385`,
  `deps.py:46-84`).
- Mutations are guarded by an Origin/`Sec-Fetch-Site` allowlist (`main.py:73-82`, duplicated in
  `document_routes.py` and `onboarding_routes.py`), but not every mutating route calls it.

**Goals for a consumer launch:**

1. Users sign in before they see or change anything.
2. One user's career data is unreachable by any other user, through HTTP **or through the agent**.
3. A user can delete their account and every copy of their data the app controls.
4. A user can export all of their data.
5. Strangers cannot run up the model bill.

**Non-goals for this design:** multiple applications per user (the slug resolver), teams or
sharing, admin impersonation, horizontal scaling.

---

## 2. What multi-tenancy actually touches

Re-rooting the file stores is the easy part. These pieces of process-global state all assume one
user and all have to change:

| State | Where | Problem under many users |
|---|---|---|
| Adapters built at import | `main.py:379-385`, `deps.py:46-84` | One workspace for everyone |
| Persistent variant client | `adapters/generation_sdk.py:225-236` | One long conversation; user B's request runs in a context holding user A's grimoire and resume |
| `last_call` on the generation port | `adapters/generation_sdk.py:179` | Shared mutable metrics |
| `RunManager._status/_tasks/_metrics` | `runs.py:54-56` | Keyed by slug only; same slug = collision |
| `source_lock` | `main.py:69` | One user's edit blocks everyone |
| `preview_tokens`, `warning_revision` | `document_routes.py:60-61` | Shared across users |
| Onboarding `active` flag | `onboarding_routes.py:41` | Shared across users |
| Fake repository picks | `adapters/workspace_fake.py:31` | Keyed by slug only |
| Agent file tools | `adapters/generation_sdk.py:47,144-159` | `Read`/`Glob`/`Grep` allowed on any path |
| SDK session transcripts | `~/.claude/projects/<encoded-cwd>/*.jsonl` | Full resume/grimoire/JD text, outside the workspace |

Every one of these is addressed below. A design that only re-roots `DocumentStore`,
`FsWorkspaceRepository`, and `FinalDocuments` is not isolation.

---

## 3. Authentication

### Decision: OAuth with Google (OIDC) and GitHub, invite-gated

| Option | Verdict |
|---|---|
| OAuth (Google, GitHub) | **Chosen.** No password storage, one-click sign-in, fits "calm under pressure". |
| LinkedIn OAuth | Later. Sign-in with LinkedIn needs app review; no MVP value over Google. |
| Magic links | Rejected for MVP: needs email delivery infrastructure. |
| Username/password | Rejected: password storage, reset flows, breach liability. |
| Passkeys | Out of scope. Revisit only if users ask. |

Library: `authlib`'s Starlette client.

### Flow requirements

- **`state`** on every authorization request, checked on callback (login CSRF).
- **PKCE (S256)** on both providers.
- **Google:** OIDC with `nonce`; validate the ID token (issuer, audience, expiry, nonce). Use
  `sub` as the subject. Require `email_verified = true`.
- **GitHub:** not OIDC. Fetch `/user` for the numeric `id` (the subject; never the login name,
  which can change) and `/user/emails` for an address with `verified = true`. Scope:
  `read:user user:email`.
- **Redirect URIs** are exact matches registered with each provider and derived from
  `CONJURER_BASE_URL`, never from the request's `Host`.
- **Provider tokens are discarded** after the callback. Nothing is stored except subject and
  verified email.
- authlib keeps `state` and `nonce` in a short-lived signed pre-login cookie
  (`conjurer_oauth`, 10-minute max age), separate from the session cookie, deleted on callback.

### Identity model

- A user is keyed by `(provider, subject)`. Email is display-only and never used for lookup.
- **No account linking.** Signing in with Google and with GitHub creates two accounts even if the
  emails match. Linking by email is an account-takeover path and is not worth the complexity.
- **Invite gate.** A sign-in creates an account only if the verified email is on the allowlist
  (`invites` table, managed by CLI). Everyone else sees "not invited yet". The gate stays until
  the cost controls in §8 are proven.

### Routes

```
GET  /login                     sign-in page with provider buttons
GET  /auth/{provider}           start OAuth (provider in {"google", "github"})
GET  /auth/{provider}/callback  finish OAuth, create session, 303 to /
POST /logout                    revoke session, clear cookie, 303 to /login
```

---

## 4. Sessions and CSRF

### Decision: server-side sessions in SQLite

A stateless signed or encrypted cookie cannot be revoked, and logout and deletion both need
revocation. A cookie that outlives its account would also let the next request recreate the
deleted workspace. So sessions live in the database and the cookie carries only an opaque id.

- Cookie value: 32 random bytes, URL-safe base64. The database stores **its SHA-256**, so a
  database read does not yield usable cookies.
- Cookie: `__Host-conjurer_session`, `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, no
  `Domain`. Browsers treat `http://localhost` as secure, so `Secure` holds in development too.
- Expiry: **7 days idle, 30 days absolute.** `last_seen_at` is updated at most once an hour to
  avoid a write per request.
- **Rotation:** a new session id is issued at every login; any pre-login session is discarded
  (fixation).
- **Per-request check:** the session row must exist, be unexpired, and belong to a user whose
  `status = 'active'`. A deleted or deleting user's cookie fails this check.
- No session secret is needed, which keeps the offline `fake` suite free of auth configuration.
  (The pre-login OAuth cookie needs `CONJURER_OAUTH_STATE_SECRET`, required only when providers
  are configured.)

### Data model

SQLite via the stdlib `sqlite3` module, one file at `$CONJURER_WORKSPACE/conjurer.db`, WAL mode.
No ORM.

```sql
CREATE TABLE users (
    id          TEXT PRIMARY KEY,          -- UUID v4, also the workspace directory name
    email       TEXT NOT NULL,             -- verified, display only
    status      TEXT NOT NULL CHECK (status IN ('active', 'deleting')),
    created_at  TEXT NOT NULL
);

CREATE TABLE identities (
    provider    TEXT NOT NULL,             -- 'google' | 'github'
    subject     TEXT NOT NULL,             -- Google sub, GitHub numeric id
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (provider, subject)
);

CREATE TABLE sessions (
    token_hash   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at   TEXT NOT NULL              -- absolute cap
);

CREATE TABLE invites (
    email       TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL
);

CREATE TABLE usage (
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day         TEXT NOT NULL,             -- UTC date
    runs        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);
```

Access goes through an `AccountStore` Protocol in `ports.py` with one SQLite adapter, matching
how the other ports are declared. Routes never touch `sqlite3`.

### Unauthenticated requests

- Full-page request: `303` to `/login`.
- HTMX request (`HX-Request: true`): `401` with `HX-Redirect: /login`, so HTMX navigates instead
  of swapping the login page into a fragment.
- `/login`, `/auth/*`, and `/static/*` are the only public routes.

### CSRF

The existing check is an allowlist: it passes when `Sec-Fetch-Site` is `same-origin` or
`same-site`, or when that header is absent and `Origin` equals the request's own origin
(`main.py:73-82`). Changes:

1. **One dependency, every mutation.** Replace the three copies with a single
   `require_same_origin` FastAPI dependency, applied router-wide to every non-GET route. Today
   `POST /start` (`main.py:112`, writes `jd.txt` and starts a paid run) and `POST /reset`
   (`main.py:367`) have no check at all. Once a session cookie exists, `/start` becomes a
   cross-site way to plant a hostile job description and spend the user's quota.
2. **Accept only `same-origin`.** Drop `same-site`, which trusts sibling subdomains.
3. **Compare `Origin` to `CONJURER_BASE_URL`**, not to `request.url`. Behind a TLS-terminating
   proxy `request.url` is `http://` while the browser sends `https://`.
4. Keep rejecting when both headers are absent.

With `SameSite=Lax` plus this check, no token-based CSRF scheme is needed.

The run-state guard currently inside `require_mutation` (`runs.status(SLUG)`) moves out into its
own per-user dependency, since it is not a CSRF concern.

---

## 5. Per-user storage

### Layout

```
$CONJURER_WORKSPACE/
├── conjurer.db
└── users/
    └── <user_id>/                      # UUID v4
        ├── master-resume.md
        ├── grimoire.md
        ├── onboarding.json
        ├── .document-history/          # includes onboarding.json/ snapshots
        ├── .document-originals/<sha256>/<filename>
        ├── .agent-runtime/             # SDK config dir: transcripts land here (§7)
        └── applications/<slug>/        # unchanged from today
```

Everything a user owns lives under one directory, so deletion and export are both "this tree".

### Rules

- `user_id` is a server-generated UUID v4. Validate with `uuid.UUID(value)` and require the
  canonical string form; never accept a user id from the request.
- `user_workspace(user_id) -> Path` **resolves only**. It never creates the directory. The
  directory is created once, when the account is created. A request for a user whose directory
  is missing is an error, not a reason to recreate it. This is what stops a stale request from
  resurrecting a deleted account.
- `slug` stays validated by `validate_slug` (`domain.py:34-40`).
- `DocumentStore.store_original` already rejects empty, `.`, `..`, and any filename containing
  `/` or `\` (`document_store.py:122-128`). Phase 2 keeps that covered under the per-user root.

### Per-request adapters

The module-level singletons in `main.py:379-385` are replaced by a FastAPI dependency that
resolves the signed-in user and builds that user's adapters:

```python
@dataclass(frozen=True)
class UserWorkspace:
    user_id: str
    repository: WorkspaceRepository
    documents: DocumentStore
    onboarding: OnboardingStore
    finals: FinalDocuments
    composition: CompositionPort | None
```

These are cheap to construct (they hold a path), so per-request construction is fine. Routes
take `UserWorkspace` instead of closing over globals. The `fake` backend builds the same shape
from `FakeWorkspaceRepository`, with picks keyed by `(user_id, slug)`.

**Slug:** each user gets exactly one application in the MVP, still named by the `SLUG` constant
but always resolved under that user's tree. The per-user slug resolver noted in `AGENTS.md`
stays future work; nothing here bakes in one application per user beyond that constant.

Storage stays on the local filesystem. `DocumentStore` is a concrete class, not a port, and
there is no plan to make it one until a second storage backend is actually needed.

---

## 6. Per-user runtime state

| State | Change |
|---|---|
| `RunManager` | Key every dict by `(user_id, slug)`. Add `cancel(user_id)` that cancels and awaits that user's tasks. |
| `source_lock`, onboarding `active` | Per-user `asyncio.Lock` / flag held in a small registry keyed by `user_id`. |
| `preview_tokens`, `warning_revision` | Keyed by `user_id`. |
| Generation port | One `SdkGenerationPort` **per user**, held in a `GenerationPool`. |

### GenerationPool

The persistent variant client exists so per-unit calls share a warm prompt-cache prefix
(`AGENTS.md`: "a design rule, not an optimization"). That stays true per user and must never be
true across users.

- `pool.get(user_id)` returns that user's port, creating it with the user's workspace as `cwd`.
- **Idle eviction:** a port unused for 15 minutes is `aclose()`d (`generation_sdk.py:254-257`
  already disconnects the client).
- **Cap:** at most `CONJURER_MAX_LIVE_CLIENTS` (default 4) connected ports. When full, a new run
  waits in the run queue rather than evicting another user's in-flight client.
- `pool.release(user_id)` is called on logout and deletion.
- `RunManager.aclose()` on shutdown closes every pooled port.
- `last_call` moves onto the per-user port, so metrics stop being shared.

The prompt-cache benefit becomes per user: the first run in a session pays for the static
prefix. That is the correct trade.

---

## 7. Containing the agent

The variant client keeps the default toolset because a `tools` allowlist breaks plugin subagent
dispatch (`AGENTS.md`). Its `can_use_tool` guard allows `Read`, `Glob`, `Grep`, `Agent`, `Task`
**with no path check** (`generation_sdk.py:144-159`). Under multi-tenancy, a prompt injection in
a pasted job description can `Glob ../*/master-resume.md` and `Read` another user's resume into
the variants. The HTTP-side validators do nothing about this.

### Required before a second user is admitted

1. **Path guard.** For `Read`, `Glob`, and `Grep`, resolve every path argument (`file_path`,
   `path`, and the base of `pattern`) with `Path.resolve()` and allow it only if it is inside
   the user's workspace or inside the plugin directory (`DEFAULT_PLUGIN_DIR`,
   `generation_sdk.py:37`), which the subagent reads. A missing path argument defaults to `cwd`,
   which is the user's workspace. Everything else is denied.
2. **Prove the guard sees the calls that matter, including subagent calls.** The variant client
   already omits `allowed_tools` so whole-tool approvals cannot bypass the callback
   (`generation_sdk.py:225-236`). `can_use_tool` is consulted for calls that would otherwise
   prompt; reads inside `cwd` (the user's own workspace) are auto-approved, and reads outside it
   prompt and so reach the guard. That is the right split, but it is CLI behavior, not ours. If
   a live test shows any out-of-workspace read skipping the callback, enforce the rule with a
   `PreToolUse` hook instead. A live negative test must show a `Read` of a sibling user's file
   being denied **from inside the dispatched variant-generator subagent**, not just the
   top-level agent.
3. **No secrets in the app's environment.** The SDK starts the CLI with all of `os.environ`
   plus `options.env` (`claude_agent_sdk/_internal/transport/subprocess_cli.py:819-825`,
   SDK 0.2.163), and `options.env` can override but not remove variables. On Linux, a `Read` of
   `/proc/self/environ` would hand over OAuth secrets. So OAuth client secrets and the OAuth
   state secret are read from a file named by `CONJURER_SECRETS_FILE` (mode `0600`) into a
   config object, never exported. The path guard in (1) also denies `/proc`.
4. **Transcripts inside the user tree.** The CLI saves session transcripts under its config
   directory. Set `env={"CLAUDE_CONFIG_DIR": str(user_workspace / ".agent-runtime")}` for both
   SDK clients so transcripts land in the user's tree and are removed with it. (The CLI's
   `--no-session-persistence` flag documents itself as `--print`-only, and the SDK runs the CLI
   in stream-json mode, so it is not relied on.) This requires the deployment to authenticate
   the CLI with `ANTHROPIC_API_KEY`, not a stored login, since each config dir starts empty.
   The onboarding client (`onboarding_sdk.py:33-34`) runs with `tools=[]` in a temp directory,
   so it cannot read files, but it still writes a transcript; it gets the same `CLAUDE_CONFIG_DIR`.
5. **Agent writes stay impossible.** No change: the guard already denies `Write`, `Edit`,
   `Bash`, network tools and `mcp__*`. Keep the existing tests.

**Later hardening (not MVP):** run each user's CLI under a separate OS user or container so the
filesystem itself enforces isolation and the path guard becomes defense in depth.

---

## 8. Cost and abuse controls

Every run is an outline call plus one variant call per unit plus subagents, billed to the
operator. A reverse proxy cannot see per-user spend, so the app enforces this itself.

- **Invite gate** (§3) until the rest of this section is proven.
- **One active run per user.** `RunManager.start` refuses a second concurrent run for the same
  user (already true per slug; becomes per user).
- **Global cap** on connected clients (§6).
- **Daily run quota per user**, `CONJURER_DAILY_RUNS` (default 10), counted in `usage` at
  `RunManager.start`. Over quota returns a calm "come back tomorrow" page, not an error.
- **Commercial credentials.** Production uses an `ANTHROPIC_API_KEY` under commercial terms, not
  a personal Claude subscription login.
- Spend alerting is configured in the Anthropic console, not in the app.

---

## 9. Account deletion

### User experience

1. `GET /account` shows email, sign-in provider, created date, "Export my data", and "Delete my
   account".
2. Deleting asks the user to type `DELETE` and submit.
3. The server runs the sequence below, clears the cookie, and shows "Your account has been
   deleted".

### Sequence

Order matters: stop every writer before removing files, or an in-flight run recreates the tree.

```
1. UPDATE users SET status = 'deleting'      -- every session now fails the per-request check
2. DELETE FROM sessions WHERE user_id = ?
3. await run_manager.cancel(user_id)          -- cancel and await in-flight runs
4. await generation_pool.release(user_id)     -- disconnect the user's SDK client
5. shutil.rmtree(users/<user_id>)             -- includes .agent-runtime/ transcripts
6. DELETE FROM users WHERE id = ?             -- cascades identities, usage
7. append to deletion audit log
```

If any step fails, the user stays `deleting` (locked out) and a startup sweep retries every
`deleting` account. Deletion is therefore idempotent and eventually complete; it is not atomic,
and the design does not claim it is.

Writers must not recreate the tree: `save_jd` (`adapters/workspace_fs.py:161`) and the other
adapter writes use `mkdir(parents=True)` today. With `user_workspace` refusing a missing root
(§5), a write that slips past step 3 fails instead of resurrecting the directory.

### What deletion covers

| Data | Location | Removed by |
|---|---|---|
| Source documents, onboarding state | `users/<id>/*.md`, `onboarding.json` | step 5 |
| All revision history, including onboarding snapshots | `users/<id>/.document-history/` | step 5 |
| Uploaded originals | `users/<id>/.document-originals/` | step 5 |
| Applications, picks, finals, PDF/DOCX | `users/<id>/applications/` | step 5 |
| SDK transcripts | `users/<id>/.agent-runtime/` | step 5 (§7.4) |
| In-memory run status and metrics | `RunManager` | step 3 |
| Warm SDK conversation | `GenerationPool` | step 4 |
| Account, identities, sessions, usage | `conjurer.db` | steps 2, 6 |

### What deletion does not cover, stated to the user

- **Anthropic.** Resume, grimoire, job description and onboarding text are sent to Anthropic to
  generate output. Retention there follows the operator's commercial agreement. The privacy
  notice names Anthropic as a subprocessor.
- **TypeSafe (Jev).** With `CONJURER_VERIFIER=jev`, variant text and the evidence pool go to
  TypeSafe (`adapters/verification_jev.py`). Multi-user deployments keep the verifier off until
  that processor is reviewed (open question).
- **Backups.** If the host takes filesystem backups, they age out within 30 days, and the privacy
  notice says so.
- **Application logs.** Logs record slugs, user ids and exception types, never document content.
  Phase 2 adds a test that a run failure logs no document text. Logs are retained 30 days.

### Removing one source

`purge_original` (`document_store.py:131-145`) deletes `.document-originals/<hash>` but the
extracted text survives in `.document-history/onboarding.json/` snapshots. Phase 4 also prunes
onboarding history snapshots that contain the removed source, so "remove this source" means
what it says.

### Audit log

Append-only JSON lines at `$CONJURER_WORKSPACE/audit.log`: timestamp, user id, method
(`user` or `retry-sweep`). No content, no email. The user id is pseudonymous personal data, kept
for 90 days as the record that the deletion happened.

---

## 10. Data export

`GET /account/export` returns a ZIP of the user's tree:

- Includes everything under `users/<id>/`: documents, history, **uploaded originals (including
  their PDF/DOCX files)**, applications, and generated PDF/DOCX exports. Sizes are small; no
  suffix filtering.
- Excludes `.agent-runtime/` (SDK internals) and in-progress atomic-write temps (`.<name>.*`
  files and `.final-compose-*` directories left by a crash).
- Adds `account.json`: user id, email, provider, created date, and the list of applications.
- The archive is built in a `SpooledTemporaryFile` and streamed; nothing is left on disk after
  the response.
- Export takes the user's source lock so it never captures a half-written save.

ZIP of raw files is the format: the files are already the app's documented on-disk contracts.

---

## 11. Adopting the existing local workspace

There is exactly one legacy workspace and one owner, so this is a CLI command, not a feature:

```
uv run python -m app.accounts adopt-workspace --email <owner email> --from <legacy dir>
```

It requires an existing account for that email (sign in once first), refuses if the account's
workspace has any content, and **moves** the legacy tree into `users/<user_id>/`. There is no
web route for it: a web import of a shared legacy directory would hand the owner's resume to
whichever user clicked first.

---

## 12. Deployment

### Environment

| Variable | Required | Purpose |
|---|---|---|
| `CONJURER_BACKEND` | existing | `fake` (default) or `live` |
| `CONJURER_WORKSPACE` | existing, live | Root holding `conjurer.db`, `users/`, `audit.log` |
| `CONJURER_VERIFIER` | existing | Off for multi-user until reviewed (§9) |
| `TYPESAFE_API_KEY` | existing | Only with the Jev verifier |
| `CONJURER_BASE_URL` | live | Origin for CSRF and OAuth redirect URIs |
| `CONJURER_SECRETS_FILE` | live | `0600` file with OAuth client ids/secrets and the OAuth state secret |
| `ANTHROPIC_API_KEY` | live | Commercial API credential for the CLI |
| `CONJURER_DAILY_RUNS` | optional | Default 10 |
| `CONJURER_MAX_LIVE_CLIENTS` | optional | Default 4 |

`live` refuses to start if `CONJURER_BASE_URL`, `CONJURER_SECRETS_FILE`, or at least one
complete provider configuration is missing. The `fake` backend needs none of these; offline tests
create users and sessions directly through `AccountStore` against a temporary SQLite file.

### One process

Run state, the generation pool and the per-user locks live in process memory, so the app runs as
**one uvicorn worker**. A second worker would answer status polls with "idle". Scaling out is a
separate design.

### HTTPS

Required in production (the `__Host-` cookie needs `Secure`, and OAuth providers require HTTPS
callbacks). Add `Strict-Transport-Security: max-age=31536000`.

### Security headers

```
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
                         frame-ancestors 'none'; base-uri 'none'; form-action 'self'
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
```

The templates load only `static/vendor/htmx.min.js` and `app.js` and have no inline scripts
(`templates/base.html:10-11`), so `script-src 'self'` holds. `'unsafe-inline'` for styles is
needed by the existing inline `style=` attributes (progress bars in `curate.html` and
`_summon_progress.html`).

---

## 13. Threat model

| Threat | Mitigation |
|---|---|
| Prompt injection reads another user's files | Path guard on agent file tools, verified inside subagents (§7.1-7.2) |
| Prompt injection reads app secrets | No secrets in the environment; `/proc` denied (§7.3) |
| Cross-user leakage through a shared SDK conversation | One generation port per user (§6) |
| Session theft | `__Host-`, `HttpOnly`, `Secure`, `SameSite=Lax`; hashed at rest; revocable; 7-day idle cap |
| Session fixation | New session id at every login |
| Login CSRF | OAuth `state`; PKCE |
| CSRF on mutations | One same-origin dependency on every non-GET route, including `/start` and `/reset` |
| Account takeover via email | No lookup or linking by email; identity is `(provider, subject)` |
| Unverified GitHub email | Require `verified = true` from `/user/emails` |
| HTTP path traversal | `uuid.UUID` for user ids, `validate_slug`, safe original filenames |
| Deleted account comes back | `status='deleting'` lockout; runs cancelled first; `user_workspace` never creates |
| Stranger runs up cost | Invite gate, daily quota, one run per user, global client cap |
| XSS | Jinja2 autoescape (existing), CSP above, `HttpOnly` cookie |
| Data left after deletion | Single tree per user incl. transcripts; retry sweep; processors disclosed |

Out of scope: DDoS (infrastructure), penetration testing, compliance audits.

---

## 14. Phased plan

Each phase is one PR and keeps the 100% line and branch gate. **Gate:** the invite list holds
only the owner until Phases 2 and 3 are merged, and public sign-up waits for Phase 6.

### Phase 1: Accounts, sessions, and CSRF

- [ ] AC-1.1: `AccountStore` port and SQLite adapter create the schema in §4 at startup.
- [ ] AC-1.2: Google (OIDC) and GitHub sign-in work end to end with `state` and PKCE; a
  mismatched `state` and a replayed code are both rejected.
- [ ] AC-1.3: Returning `(provider, subject)` reuses its user id; the same email via the other
  provider creates a separate account.
- [ ] AC-1.4: A verified email not in `invites` gets "not invited yet" and no account; an
  unverified GitHub email is refused.
- [ ] AC-1.5: Session cookie is `__Host-conjurer_session` with the flags in §4; the database
  holds only its hash; a new id is issued at login.
- [ ] AC-1.6: Expired (idle or absolute) sessions and sessions of a non-`active` user are
  rejected.
- [ ] AC-1.7: Every route except `/login`, `/auth/*`, `/static/*` requires a session: full
  pages get `303 /login`, HTMX requests get `401` with `HX-Redirect`.
- [ ] AC-1.8: `require_same_origin` runs on every non-GET route; `POST /start` and
  `POST /reset` reject a cross-site request; `same-site` is rejected; `Origin` is compared to
  `CONJURER_BASE_URL`.
- [ ] AC-1.9: `POST /logout` deletes the session row and clears the cookie.
- [ ] AC-1.10: `live` refuses to start without the configuration in §12; `fake` starts without it.

### Phase 2: Per-user workspaces and runtime state

- [ ] AC-2.1: Account creation creates `users/<uuid>/`; `user_workspace` resolves without
  creating and rejects non-canonical UUIDs.
- [ ] AC-2.2: Routes take a per-request `UserWorkspace`; no adapter is built at import.
- [ ] AC-2.3: `RunManager`, source lock, preview tokens, onboarding flag, and fake picks are keyed
  by user.
- [ ] AC-2.4: `GenerationPool` gives each user their own `SdkGenerationPort`, evicts after 15
  idle minutes, and honors `CONJURER_MAX_LIVE_CLIENTS`.
- [ ] AC-2.5: Two users with the same slug have independent runs, picks, documents, and finals.
- [ ] AC-2.6: User B gets 404 for every user-A resource reachable by URL.
- [ ] AC-2.7: An uploaded original named `../x` is rejected and nothing is written outside the
  user's `.document-originals/`.
- [ ] AC-2.8: A failing run logs no document text.
- [ ] AC-2.9: `adopt-workspace` CLI moves the legacy tree into an empty account and refuses a
  non-empty one.

### Phase 3: Agent containment

- [ ] AC-3.1: Path guard denies `Read`/`Glob`/`Grep` outside the user workspace and the plugin
  directory, including `../`, absolute paths, symlinks that resolve outside, and `/proc`.
- [ ] AC-3.2: Live test: a prompt-injected `Read` of a sibling user's `master-resume.md` is
  denied from inside the dispatched variant-generator subagent, and variants still generate.
- [ ] AC-3.3: OAuth secrets are absent from `os.environ` at runtime.
- [ ] AC-3.4: Both SDK clients run with `CLAUDE_CONFIG_DIR` under the user's `.agent-runtime/`;
  a live run writes no transcript under `~/.claude/projects/`.

### Phase 4: Account deletion

- [ ] AC-4.1: `GET /account` and `POST /account/delete` (confirmation must equal `DELETE`).
- [ ] AC-4.2: The §9 sequence runs in order; afterwards `users/<id>/` and all the user's rows are
  gone.
- [ ] AC-4.3: Deleting during an in-flight run cancels it and leaves no directory behind.
- [ ] AC-4.4: The deleted user's old cookie is rejected on the next request.
- [ ] AC-4.5: A failure mid-sequence leaves the user `deleting`; the startup sweep completes it.
- [ ] AC-4.6: Audit log records timestamp, user id, method, and nothing else.
- [ ] AC-4.7: Removing an onboarding source also prunes history snapshots containing it.

### Phase 5: Data export

- [ ] AC-5.1: `GET /account/export` streams a ZIP of the user tree plus `account.json`.
- [ ] AC-5.2: Uploaded PDF/DOCX originals and generated exports are included; `.agent-runtime/`
  and atomic-write temps are not.
- [ ] AC-5.3: No archive remains on disk after the response.

### Phase 6: Cost controls and public sign-up

- [ ] AC-6.1: Daily run quota enforced per user with a calm over-quota page.
- [ ] AC-6.2: A second concurrent run for the same user is refused.
- [ ] AC-6.3: Privacy notice names Anthropic (and TypeSafe if enabled) as processors and states
  backup and log retention.
- [ ] AC-6.4: Invite gate can be switched off by configuration.

---

## 15. Decisions taken and questions left

### Decided in this revision

| Question | Decision |
|---|---|
| OAuth providers | Google + GitHub; LinkedIn later |
| Session duration | 7 days idle, 30 days absolute |
| Database or filesystem only | SQLite from Phase 1 (revocation requires it) |
| Account linking | None |
| Email verification | Trust Google `email_verified` and GitHub `verified`; email is display only |
| Export format | ZIP of raw files plus `account.json` |
| Rate limiting | In the app (per-user quota); a proxy cannot see per-user spend |
| Legacy migration | One-off CLI move, no web route |
| Deployment shape | One process, local filesystem, HTTPS |

### Still needs the owner

1. **Deletion grace period:** immediate purge (this design), or a recovery window?
2. **Inactive accounts:** retain indefinitely, or notify and delete after N months?
3. **Admin role:** none (this design), or a support role that can delete on request?
4. **Jev verifier for multi-user:** keep off, or review TypeSafe as a processor and enable it?
5. **Anthropic retention:** is standard commercial retention acceptable, or is zero data
   retention required before launch?
6. **Quota numbers:** are 10 runs per user per day and 4 live clients the right starting point?

---

## References

- `PRODUCT.md`: audience and design principles
- `web/BACKEND.md`: ports and adapters
- `AGENTS.md`: generation-port constraints and the slug seam
- `web/app/main.py`: composition, CSRF helper, routes
- `web/app/deps.py`: `workspace_root()`, adapter construction
- `web/app/runs.py`: `RunManager`
- `web/app/adapters/generation_sdk.py`: variant client, tool guard
- `web/app/onboarding_sdk.py`: onboarding client
- `web/app/document_store.py`: history, originals, `purge_original`
