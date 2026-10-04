# Design: Authentication, Per-User Isolation, and Account Deletion

This document designs the authentication, per-user storage isolation, and account data
deletion mechanisms for the resume-conjurer web app. It builds on the product constraints
in `PRODUCT.md`, the hexagonal architecture in `web/BACKEND.md`, and the current local
single-user implementation.

**Related work:**
- Parent issue: #22 (release gates: "resolve per-user identity, storage, authorization, and isolation")
- Draft PR #32 adds onboarding, uploads, document history, and exports

**Scope:** Design document only. Implementation will follow in separate PRs.

---

## Table of Contents

1. [Context and Goals](#context-and-goals)
2. [Authentication Options](#authentication-options)
3. [Recommendation: OAuth with Passkey Option](#recommendation-oauth-with-passkey-option)
4. [Session Model](#session-model)
5. [Per-User Storage Partitioning](#per-user-storage-partitioning)
6. [Migration of Existing Local Data](#migration-of-existing-local-data)
7. [Account Deletion Flow](#account-deletion-flow)
8. [Data Retention and Export](#data-retention-and-export)
9. [Deployment Implications](#deployment-implications)
10. [Threat Model](#threat-model)
11. [Phased Implementation Plan](#phased-implementation-plan)
12. [Open Questions](#open-questions)

---

## Context and Goals

The web app is currently a single-user, local-only tool:
- No authentication or sessions
- Hardcoded `SLUG = "globex-staff-platform"` at `web/app/main.py:25`
- `CONJURER_WORKSPACE` env var points to a single workspace directory
- CSRF protection via `Origin` / `Sec-Fetch-Site` header checking (no session tokens)

**Goals for consumer launch:**

1. **Login first:** Users authenticate before accessing their data
2. **Per-user isolation:** Each user's career documents are invisible to others
3. **Account deletion:** Users can delete all data tied to their account, including:
   - Source documents (`master-resume.md`, `grimoire.md`)
   - Document history (`.document-history/`)
   - Uploaded originals (`.document-originals/`)
   - Onboarding state (`onboarding.json`)
   - Applications (`applications/<slug>/`) with JD, evidence, outline, variants, picks, finals
   - Exports (PDFs, DOCX files)

---

## Authentication Options

### Option A: OAuth 2.0 (Recommended)

**Providers:** Google, GitHub, LinkedIn (most relevant for job seekers)

**Pros:**
- No password storage or reset flows
- Users already have accounts; reduces friction
- LinkedIn OAuth aligns with job-seeker audience
- Well-supported in FastAPI via `authlib` or `python-social-auth`

**Cons:**
- Dependency on external providers (availability, ToS changes)
- Requires provider app registration and callback handling
- Some users distrust third-party OAuth for privacy reasons

**Implementation sketch:**
```
GET /auth/login -> redirect to provider
GET /auth/callback -> validate code, create/lookup user, set session
POST /auth/logout -> clear session
```

### Option B: Magic Links (Email-Based)

**Flow:** User enters email, receives a signed link, clicks to log in.

**Pros:**
- No password to remember or store
- Simple UX for infrequent users (job search is episodic)
- Email is a natural identifier for job seekers

**Cons:**
- Requires email sending infrastructure (SMTP, SendGrid, SES)
- Latency: user waits for email delivery
- Email deliverability issues (spam filters, delays)
- Links can be forwarded or intercepted

### Option C: Username/Password

**Pros:**
- Self-contained, no external dependencies
- Familiar pattern

**Cons:**
- Password storage (bcrypt/argon2), reset flows, rate limiting
- Users reuse passwords; breach liability
- More UI to build (signup, forgot password, change password)

### Option D: Passkeys / WebAuthn

**Pros:**
- Phishing-resistant, no passwords
- Modern UX on supported devices
- No shared secrets to breach

**Cons:**
- Device-bound by default; recovery requires setup
- Not universally supported (older browsers, enterprise lockdowns)
- Requires a fallback auth method

---

## Recommendation: OAuth with Passkey Option

**Primary:** OAuth 2.0 with Google and GitHub (LinkedIn as a future option)

**Rationale:**
- Job seekers likely have Google or GitHub accounts
- No password infrastructure to maintain
- Fast onboarding (one click to sign in)
- Aligns with "calm under pressure" principle: low friction

**Secondary (Phase 2):** Passkey enrollment for returning users who want passwordless
sign-in without OAuth. Not required for MVP.

**Not recommended for MVP:** Magic links (email infra cost), username/password
(security burden), LinkedIn OAuth (requires company verification for API access).

---

## Session Model

### Current State

- No session management
- CSRF protection checks `Origin` and `Sec-Fetch-Site` headers:

```python
def require_mutation(request: Request) -> None:
    origin = request.headers.get("origin")
    expected = f"{request.url.scheme}://{request.url.netloc}"
    if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin != expected):
        raise HTTPException(403, "Document changes must come from this application.")
```

### Proposed Session Model

**Session storage:** Signed server-side sessions stored in a backend (Redis, PostgreSQL,
or encrypted cookies for stateless deployment). Recommended: **encrypted cookies** for
simplicity in early deployment, with a migration path to server-side sessions for
revocation.

**Session fields:**
```python
@dataclass
class Session:
    user_id: str           # Stable identifier (UUID or provider-scoped ID)
    email: str             # For display and communication
    provider: str          # "google", "github", etc.
    created_at: datetime
    expires_at: datetime
```

**Cookie configuration:**
- `HttpOnly`: Yes (no JS access)
- `Secure`: Yes (HTTPS only in production)
- `SameSite`: `Lax` (allow top-level GET navigations, block cross-origin POST)
- `Max-Age`: 7 days (rolling expiration on activity)

**CSRF handling:**

The existing `Origin` + `Sec-Fetch-Site` check remains valid and becomes stronger
with proper sessions:

1. `SameSite=Lax` cookies prevent most cross-origin POST attacks
2. `Origin` header check catches remaining cases
3. No separate CSRF tokens needed for browser-form POSTs if using `SameSite=Lax`

For defense-in-depth, add a double-submit cookie pattern:
- Server sets a non-HttpOnly `csrf_token` cookie
- Forms include `<input type="hidden" name="_csrf" value="...">` echoing the cookie
- Server validates the form value matches the cookie value

This is optional if `SameSite=Lax` + `Origin` checking is deemed sufficient.

### Session Middleware

```python
@app.middleware("http")
async def session_middleware(request: Request, call_next):
    session = decode_session_cookie(request.cookies.get("session"))
    if session and session.expires_at > utcnow():
        request.state.user = session
    else:
        request.state.user = None
    response = await call_next(request)
    return response
```

**Auth-required routes** check `request.state.user` and redirect to `/auth/login` if None.

---

## Per-User Storage Partitioning

### Current Layout (Single User)

```
$CONJURER_WORKSPACE/
├── master-resume.md
├── grimoire.md
├── .document-history/
│   ├── master-resume.md/
│   │   └── <sha256>.md
│   └── grimoire.md/
│       └── <sha256>.md
├── .document-originals/
│   └── <sha256>/
│       └── <filename>
├── onboarding.json
└── applications/
    └── <slug>/
        ├── jd.txt
        ├── evidence.md
        ├── outline.json
        ├── variants.md
        ├── metrics.json
        ├── support.json
        ├── cover_letter.md
        ├── resume.md
        ├── .document-history/
        ├── .final-composition.json
        ├── .final-exports.json
        ├── cover_letter.pdf
        ├── cover_letter.docx
        ├── resume.pdf
        └── resume.docx
```

### Proposed Multi-User Layout

Partition by user ID at the workspace root:

```
$CONJURER_WORKSPACE/
└── users/
    └── <user_id>/                    # UUID or stable provider-scoped ID
        ├── master-resume.md
        ├── grimoire.md
        ├── .document-history/
        ├── .document-originals/
        ├── onboarding.json
        └── applications/
            └── <slug>/
                └── ... (same structure as today)
```

**Key design decisions:**

1. **User ID format:** UUID v4, generated at first login. Provider-scoped IDs
   (e.g., Google sub) are stored in a user record but not used as filesystem paths
   (they may contain special characters or change on account linking).

2. **Slug scope:** Application slugs are user-scoped. Two users can both have a
   `globex-staff-platform` application independently.

3. **Path resolution:** The current `workspace_root()` function becomes `user_workspace(user_id)`:

   ```python
   def user_workspace(user_id: str) -> Path:
       validate_user_id(user_id)
       return workspace_root() / "users" / user_id
   ```

4. **DocumentStore changes:** Constructor takes `user_workspace(user_id)` as root
   instead of the global workspace root.

5. **FsWorkspaceRepository changes:** Constructor takes user workspace root.

### Storage Backend Options

**Option 1: Local filesystem (current)**
- Simple, no external dependencies
- Requires sticky sessions or shared filesystem for horizontal scaling
- Backup/restore is file-level

**Option 2: Object storage (S3, GCS, R2)**
- Scales horizontally without shared filesystem
- Requires adapter changes (Path operations → object operations)
- Higher latency for small reads/writes
- Natural fit for account deletion (delete by prefix)

**Recommendation:** Start with local filesystem for MVP (simplest path from current
code). Design the `DocumentStore` interface to allow a future object-storage adapter.

---

## Migration of Existing Local Data

### Scenario

A user has been running the local single-user app and has data in the old layout.
After deploying auth, they sign up and want their data migrated.

### Proposed Migration Flow

**One-time import, not automatic merge:**

1. Admin places the legacy workspace at a known path (e.g., `$CONJURER_WORKSPACE/legacy/`)
2. User signs up and reaches an empty workspace
3. User triggers "Import existing workspace" from account settings
4. Server copies legacy files into `users/<user_id>/`
5. Legacy files remain untouched (backup)
6. Import is idempotent: re-running overwrites with fresh copies

**Not supported:**
- Merging two users' data (conflict resolution is out of scope)
- Automatic detection of legacy data (explicit user action only)

**Implementation:**

```python
def import_legacy_workspace(user_id: str, legacy_root: Path) -> None:
    validate_user_id(user_id)
    target = user_workspace(user_id)
    if any(target.iterdir()):
        raise ValueError("Target workspace is not empty; clear it first.")
    shutil.copytree(legacy_root, target, dirs_exist_ok=False)
```

---

## Account Deletion Flow

### User Experience

1. User navigates to Account Settings
2. User clicks "Delete my account"
3. Confirmation dialog: "This will permanently delete all your documents, history,
   and exports. This cannot be undone. Type DELETE to confirm."
4. User types "DELETE" and clicks "Confirm deletion"
5. Server purges all user data and session
6. User is redirected to a "Your account has been deleted" page
7. Session cookie is cleared

### Data to Delete

| Category | Location | Notes |
|----------|----------|-------|
| Source documents | `users/<user_id>/master-resume.md`, `grimoire.md` | |
| Document history | `users/<user_id>/.document-history/**` | All revisions |
| Uploaded originals | `users/<user_id>/.document-originals/**` | All uploads |
| Onboarding state | `users/<user_id>/onboarding.json` | |
| Applications | `users/<user_id>/applications/**` | All JDs, variants, finals, exports |
| User record | Database (if using one) | Provider ID, email, created_at |
| Sessions | Session store | All sessions for this user |

### Implementation

```python
def delete_user_account(user_id: str) -> None:
    validate_user_id(user_id)
    user_dir = user_workspace(user_id)

    # 1. Delete all files (shutil.rmtree is not atomic; acceptable for MVP)
    if user_dir.exists():
        shutil.rmtree(user_dir)

    # 2. Delete user record from database (if any)
    db.execute("DELETE FROM users WHERE id = ?", [user_id])

    # 3. Invalidate all sessions for this user
    session_store.delete_all(user_id)
```

### Audit Log

For compliance (GDPR Article 17), log deletion events:
- Timestamp
- User ID (not PII)
- Deletion method (user-initiated, admin, retention policy)
- Operator (user, admin ID)

Logs do NOT include deleted content, only the fact of deletion.

### Asynchronous Deletion (Optional)

For large workspaces, deletion could be queued:
1. Mark user as `deletion_pending` in database
2. Block login for this user
3. Background job purges files
4. Job marks user as `deleted` or removes record

MVP can use synchronous deletion; async is a scaling optimization.

---

## Data Retention and Export

### Data Export (GDPR Article 20)

**User-initiated export:**

1. User clicks "Export my data" in Account Settings
2. Server creates a ZIP archive of:
   - `master-resume.md`, `grimoire.md`
   - `.document-history/**` (all history revisions)
   - `.document-originals/**` (all uploaded files)
   - `applications/**/` (all applications, excluding generated PDFs/DOCX for size)
   - `metadata.json`: user ID, email, created_at, list of applications
3. User downloads the ZIP

**Implementation:**

```python
def export_user_data(user_id: str) -> Path:
    user_dir = user_workspace(user_id)
    archive = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in user_dir.rglob("*"):
            if path.suffix in {".pdf", ".docx"}:
                continue  # Skip large exports; user can re-generate
            if path.is_file():
                zf.write(path, path.relative_to(user_dir))
        zf.writestr("metadata.json", json.dumps({
            "user_id": user_id,
            "exported_at": utcnow().isoformat(),
        }))
    return Path(archive.name)
```

### Retention Policy

**Active accounts:** Data retained indefinitely while account exists.

**Deleted accounts:** Data purged immediately (no soft-delete grace period for MVP).

**Inactive accounts (future):** Define an inactivity threshold (e.g., 24 months) and
notify users before purging. Not required for MVP.

---

## Deployment Implications

### Environment Variables

New variables for auth:
```
CONJURER_AUTH_PROVIDER=google,github       # Enabled OAuth providers
CONJURER_GOOGLE_CLIENT_ID=...
CONJURER_GOOGLE_CLIENT_SECRET=...
CONJURER_GITHUB_CLIENT_ID=...
CONJURER_GITHUB_CLIENT_SECRET=...
CONJURER_SESSION_SECRET=...                # For signing session cookies
CONJURER_BASE_URL=https://example.com      # For OAuth callbacks
```

### Database (Optional for MVP)

If using encrypted cookies for sessions and filesystem for user data, no database is
strictly required. A database becomes necessary for:
- Session revocation (server-side sessions)
- User lookup by email (for account linking)
- Usage metrics

**Minimal schema if using a database:**

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_id)
);

CREATE TABLE sessions (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);
```

### HTTPS Requirement

Production deployment MUST use HTTPS:
- `Secure` cookie attribute requires it
- OAuth callback URLs require it
- Without HTTPS, session cookies can be intercepted

### Horizontal Scaling

**Stateless sessions (encrypted cookies):** Any instance can validate sessions.

**Filesystem storage:** Requires shared storage (NFS, EFS) or sticky sessions.

**Object storage (future):** Enables fully stateless app instances.

---

## Threat Model

### Assets

| Asset | Sensitivity | Protection |
|-------|-------------|------------|
| Resume content | High (PII, employment history) | Per-user isolation, auth required |
| Evidence/grimoire | High (skills, accomplishments) | Per-user isolation, auth required |
| Job descriptions | Medium (reveals job search) | Per-user isolation, auth required |
| Document history | High (full edit trail) | Per-user isolation, auth required |
| Session tokens | High (bearer credential) | HttpOnly, Secure, SameSite=Lax |
| OAuth tokens | High (if stored) | Not stored; only used to fetch email/ID at login |

### Threats and Mitigations

| Threat | Impact | Mitigation |
|--------|--------|------------|
| Session hijacking | Account takeover | HttpOnly + Secure + SameSite=Lax cookies; short expiry |
| CSRF | Unauthorized mutations | SameSite=Lax + Origin header check (existing) |
| Path traversal | Access other users' files | `validate_user_id()` + `validate_slug()` (existing) |
| OAuth token theft | Account takeover | Tokens not stored; only ID/email extracted at login |
| Brute-force login | Account enumeration | OAuth delegates rate limiting to provider |
| XSS | Session theft, data exfil | HttpOnly cookies; CSP headers (to add) |
| Insider threat | Data breach | Filesystem permissions; audit logging |
| Account deletion bypass | Data remains after deletion | Atomic deletion; audit log; periodic orphan scan |

### Security Headers to Add

```python
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"
    return response
```

### Out of Scope

- DDoS protection (handled at infrastructure layer)
- Key management / HSM (use cloud KMS if needed)
- Penetration testing (separate engagement)
- SOC 2 / compliance audit (separate scope)

---

## Phased Implementation Plan

### Phase 1: Session Infrastructure

**Goal:** Add session management without changing user-visible features.

**Scope:**
- Session middleware (encrypted cookie)
- Session dataclass and encode/decode
- `/auth/login` and `/auth/logout` stubs (redirect to home for now)
- All existing routes work for unauthenticated users (no enforcement yet)

**Acceptance Criteria:**
- [ ] AC-1.1: `Session` dataclass with `user_id`, `email`, `provider`, `created_at`, `expires_at`
- [ ] AC-1.2: `encode_session()` and `decode_session()` use `itsdangerous` signed cookies
- [ ] AC-1.3: Session middleware attaches `request.state.user` (or None)
- [ ] AC-1.4: `GET /auth/login` renders a "Sign in" page (no providers yet)
- [ ] AC-1.5: `POST /auth/logout` clears session cookie, redirects to `/`
- [ ] AC-1.6: All existing routes still work (100% test coverage maintained)
- [ ] AC-1.7: `CONJURER_SESSION_SECRET` env var required; startup fails if missing

### Phase 2: OAuth Integration

**Goal:** Users can sign in with Google or GitHub.

**Scope:**
- OAuth flow with `authlib`
- User record creation (first login)
- Session creation on successful OAuth

**Acceptance Criteria:**
- [ ] AC-2.1: `GET /auth/google` redirects to Google OAuth
- [ ] AC-2.2: `GET /auth/google/callback` validates code, creates user record, sets session
- [ ] AC-2.3: `GET /auth/github` redirects to GitHub OAuth
- [ ] AC-2.4: `GET /auth/github/callback` validates code, creates user record, sets session
- [ ] AC-2.5: User record stored in database or `users/<user_id>/user.json`
- [ ] AC-2.6: Login page shows "Sign in with Google" and "Sign in with GitHub" buttons
- [ ] AC-2.7: Returning user (same provider+provider_id) reuses existing user_id
- [ ] AC-2.8: OAuth credentials configured via env vars; startup fails if incomplete

### Phase 3: Per-User Storage

**Goal:** Each user's data is isolated in `users/<user_id>/`.

**Scope:**
- `user_workspace(user_id)` replaces `workspace_root()` in adapters
- `DocumentStore`, `FsWorkspaceRepository`, `FinalDocuments` take user workspace
- Routes resolve user_id from session and inject user-scoped adapters
- Auth required for all document routes

**Acceptance Criteria:**
- [ ] AC-3.1: `deps.py` exports `user_workspace(user_id)` creating `users/<user_id>/`
- [ ] AC-3.2: `DocumentStore` root is user workspace, not global workspace
- [ ] AC-3.3: `FsWorkspaceRepository` root is user workspace
- [ ] AC-3.4: `FinalDocuments` root is user workspace
- [ ] AC-3.5: All document routes require authentication (return 401 if not logged in)
- [ ] AC-3.6: Unauthenticated `/` shows login prompt; authenticated `/` shows entry
- [ ] AC-3.7: Two test users with same slug have independent applications
- [ ] AC-3.8: `validate_user_id()` rejects path traversal attempts

### Phase 4: Account Deletion

**Goal:** Users can permanently delete all their data.

**Scope:**
- Account settings page
- Deletion confirmation flow
- `delete_user_account()` function
- Audit logging

**Acceptance Criteria:**
- [ ] AC-4.1: `GET /account` shows account settings with "Delete my account" button
- [ ] AC-4.2: `POST /account/delete` requires confirmation input matching "DELETE"
- [ ] AC-4.3: `delete_user_account()` removes `users/<user_id>/` directory tree
- [ ] AC-4.4: Deletion clears session and redirects to "Account deleted" page
- [ ] AC-4.5: Deleted user cannot log in (user record removed)
- [ ] AC-4.6: Deletion is logged with timestamp, user_id, method
- [ ] AC-4.7: Deletion endpoint requires authentication
- [ ] AC-4.8: Deletion endpoint requires CSRF protection

### Phase 5: Data Export

**Goal:** Users can download all their data.

**Scope:**
- Export ZIP generation
- Download endpoint

**Acceptance Criteria:**
- [ ] AC-5.1: `GET /account/export` returns a ZIP of user data
- [ ] AC-5.2: ZIP contains `master-resume.md`, `grimoire.md`, `.document-history/`, `.document-originals/`, `applications/`
- [ ] AC-5.3: ZIP excludes large generated files (`.pdf`, `.docx`)
- [ ] AC-5.4: ZIP includes `metadata.json` with user_id and export timestamp
- [ ] AC-5.5: Export endpoint requires authentication
- [ ] AC-5.6: Export is generated synchronously (async queuing is a future optimization)

### Phase 6: Migration Tooling

**Goal:** Existing local users can import their data.

**Scope:**
- Import legacy workspace feature
- Admin CLI or account settings UI

**Acceptance Criteria:**
- [ ] AC-6.1: `import_legacy_workspace(user_id, legacy_root)` copies files
- [ ] AC-6.2: Import fails if target workspace is not empty
- [ ] AC-6.3: Import is idempotent (re-running overwrites)
- [ ] AC-6.4: Import accessible via CLI (`python -m app.cli import-workspace ...`)
- [ ] AC-6.5: Optional: Import accessible via account settings for logged-in users

---

## Open Questions

These require owner decision before implementation:

1. **OAuth providers:** Google + GitHub, or should LinkedIn be prioritized despite
   its API access requirements?

2. **Session duration:** 7-day rolling expiry, or longer (30 days)?

3. **Database vs. filesystem-only:** Accept the operational simplicity of filesystem-only
   for MVP, or require a database from day one for user records?

4. **Account linking:** Can a user link multiple OAuth providers to one account, or is
   each provider a separate account?

5. **Email verification:** OAuth provides email; should we verify it separately, or trust
   the provider's verification?

6. **Deletion grace period:** Immediate purge, or soft-delete with a 30-day recovery
   window?

7. **Export format:** ZIP of raw files, or a structured JSON export with metadata?

8. **Inactive account policy:** Notify and delete after N months of inactivity, or retain
   indefinitely?

9. **Admin tooling:** Is there an admin role that can view/delete other users' data for
   support purposes?

10. **Rate limiting:** Should the app itself enforce rate limits, or rely on a reverse
    proxy (nginx, Cloudflare)?

---

## References

- `PRODUCT.md` — Audience and design principles
- `web/BACKEND.md` — Hexagonal architecture, port/adapter structure
- `web/app/main.py` — Current CSRF handling
- `web/app/document_store.py` — DocumentStore implementation
- `web/app/adapters/workspace_fs.py` — Filesystem workspace adapter
- `web/app/deps.py` — Composition root with `workspace_root()`
- Draft PR #32 — Onboarding, document history, originals, exports
