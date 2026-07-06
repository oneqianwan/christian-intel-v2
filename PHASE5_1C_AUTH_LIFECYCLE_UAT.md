# Phase 5.1C Auth Lifecycle UAT

## Baseline

- ProjectDir: `C:\Users\baiwan\christian-intel-v2`
- Branch: `phase5/auth-rbac-admin-v1`
- BaselineCommit: `fb87c41`

## Scope

- Implemented
  - First `super_admin` bootstrap CLI (no default admin)
  - `POST /api/auth/change-password`
  - `POST /api/auth/logout-all`
  - Password policy + stable error codes
  - Session revocation and cookie clearing behavior
  - Lifecycle + regression tests
- Not implemented (explicitly out of scope)
  - Frontend login UI / AuthProvider
  - Public registration / forgot password / email verification
  - Admin CRUD / admin UI / RBAC admin endpoints
  - Chat user isolation / Watch-Alert user migration
  - Removal of legacy `x-session-id`

## Security Rules (Freeze) Compliance

- No default admin user is created automatically
- No default password is used
- CLI does not accept plaintext password via command line arguments
- Password is obtained only via:
  - `getpass.getpass()` interactive input; or
  - environment secret `CIO_BOOTSTRAP_ADMIN_PASSWORD` (+ optional confirm `CIO_BOOTSTRAP_ADMIN_PASSWORD_CONFIRM`)
- CLI does not print:
  - raw password
  - password hash
  - session token
- CLI never elevates an existing user to `super_admin`
- Creating a second `super_admin` is refused by default

## Password Policy

Implemented by `validate_new_password(password)`:

- Min length: 12
- Max length: 128
- Empty password rejected
- Whitespace-only password rejected
- Password is not auto-trimmed
- New password must differ from current password

Stable error codes:

- `PASSWORD_TOO_SHORT`
- `PASSWORD_TOO_LONG`
- `PASSWORD_WHITESPACE_ONLY`
- `PASSWORD_UNCHANGED`
- `PASSWORD_CONFIRMATION_MISMATCH`
- `CURRENT_PASSWORD_INVALID`

## Create First Super Admin CLI

### Actual command (single source of truth)

From `backend/`:

```bash
python scripts/create_admin.py --email <email> --display-name <name> --database <db_path_or_url>
```

### Database selection behavior

- `--database` is required
- If `--database` contains `://`, it is treated as a URL
- Otherwise it is treated as a SQLite path and converted to `sqlite:///ABS_PATH`
- Output includes only a safe database summary:
  - SQLite prints the file path
  - Non-SQLite hides credentials (`username@host:port`)

### Mis-operation prevention

- If any non-deleted `super_admin` exists: refuse with `SUPER_ADMIN_ALREADY_EXISTS`
- If any user exists with same `email_normalized`: refuse with `USER_EMAIL_EXISTS`
- Never creates an `AuthSession` and never logs in automatically

## Change Password API

- Endpoint: `POST /api/auth/change-password`
- Auth: HttpOnly cookie session (no `x-session-id`)
- Request:
  - `current_password`
  - `new_password`
  - `confirm_password`
- Behavior:
  - Feature flag gated (`AUTH_V1_ENABLED=false` returns `503 AUTH_DISABLED`)
  - Validates current password
  - Validates new password policy and confirmation
  - Rejects unchanged password (`PASSWORD_UNCHANGED`)
  - Updates `User.password_hash` (Argon2id)
  - Revokes all active sessions of current user in the same transaction
  - Clears auth cookie and returns `reauthentication_required=true`
- Response (non-sensitive):
  - `{"success": true, "reauthentication_required": true}`

## Logout All API

- Endpoint: `POST /api/auth/logout-all`
- Auth: HttpOnly cookie session (no `x-session-id`)
- Behavior:
  - Feature flag gated (`AUTH_V1_ENABLED=false` returns `503 AUTH_DISABLED`)
  - Revokes all active sessions of current user
  - Does not mutate expired sessions
  - Clears auth cookie
  - Returns real `revoked_count`
- Response:
  - `{"success": true, "revoked_count": <int>}`

## Cookie Clearing

- `change-password` and `logout-all` both clear the auth cookie using the same:
  - name: `settings.AUTH_COOKIE_NAME`
  - path: `settings.AUTH_COOKIE_PATH`
  - samesite + secure consistent with login

## Tests (Executed)

### Phase 5.1 Regression (Auth v1)

From `backend/`:

```bash
python -m pytest -q tests/test_auth_models.py tests/test_auth_migration.py tests/test_auth_service.py tests/test_auth_api.py tests/test_create_admin.py tests/test_auth_account_lifecycle.py
```

Result: PASS (48 tests)

### Phase 4 Regression (Watch/Alert)

From `backend/`:

```bash
python -m pytest -q tests/test_alert_engine.py tests/test_alerts_api.py tests/test_watch_runner.py tests/test_watch_scheduler.py tests/test_watch_targets_api.py tests/test_watch_signals_api.py
```

Result: PASS (98 tests)

## Boundary Check

- No frontend changes
- No changes to Chat / Conversations / Watch Targets / Alerts routers or services
- No changes to production DB files
- Working tree changes limited to the allowlist

## Known Limitations

- No admin management APIs (create additional `super_admin` is intentionally refused by CLI)
- No frontend login integration yet
- Chat and Watch/Alert remain on existing pre-migration identity flows until later phases

## Rollback

- Set:
  - `AUTH_V1_ENABLED=false`
  - `AUTH_COOKIE_REQUIRED=false`
- Keep `users` and `auth_sessions` tables (no need to delete)
- Do not run the bootstrap CLI during rollback

