# PHASE5_3A_WATCH_ALERT_USER_OWNERSHIP_UAT

## Metadata

- Branch: `phase5/auth-rbac-admin-v1`
- Baseline Commit: `ccfe22a49d277f98411c222f99890a04b65bd117`
- Working Directory: `C:\Users\baiwan\christian-intel-v2`
- Scope: backend only
- Frontend Watch/Alert UI: remains disabled for this phase

## Executive Summary

- Result: `PASS`
- Default mode remains Phase 4 compatible.
- New mode requires formal Cookie auth and ignores `x-session-id`.
- Watch, Signal, Alert formal ownership is implemented with `owner_user_id -> users.id`.
- Legacy anonymous rows are preserved and hidden in new mode by default.
- Legacy ownership migration is explicit, dry-run-first, and CLI-only.
- No frontend files were modified.

## Architecture Audit

### Real Model And Table Names

1. Watch Target model/table: `WatchTarget` / `watch_targets`
2. Signal model/table: `Signal` / `signals`
3. Alert model/table: `Alert` / `alerts`

### Legacy Identity Reality

- There is no legacy `session_id` column on Watch/Signal/Alert.
- Phase 4 legacy isolation uses request header `x-session-id`.
- In legacy mode, router dependency resolves `x-session-id` into the service-layer `user_id` string.
- Legacy storage fields are:
  - `watch_targets.user_id`
  - `alerts.user_id`
- `signals` historically had no direct user/session ownership column and belonged indirectly through `watch_target_id`.

### Formal Ownership Design

- `watch_targets.owner_user_id` added, nullable during migration, FK to `users.id`
- `signals.owner_user_id` added, nullable during migration, FK to `users.id`
- `alerts.owner_user_id` added, nullable during migration, FK to `users.id`
- Internal owner id is never exposed in API responses.
- Legacy `user_id` fields remain in place for rollback compatibility.

### Relationship Conclusions

- Signal ownership is now direct in new mode and still linked by `watch_target_id`.
- Alert ownership is now direct in new mode and still linked by `watch_target_id` and `signal_id`.
- Worker and scheduler ownership propagation is:
  - `WatchTarget.owner_user_id -> Signal.owner_user_id -> Alert.owner_user_id`
- Owner propagation is enforced in backend services, not taken from client body/query/header.

### Real API Endpoints

#### Watch Target

- `POST /api/watch-targets`
- `GET /api/watch-targets`
- `PATCH /api/watch-targets/{watch_target_id}`
- `DELETE /api/watch-targets/{watch_target_id}`
- `POST /api/watch-targets/{watch_target_id}/run`
- `GET /api/watch-targets/{watch_target_id}/signals`

#### Alerts

- `GET /api/alerts`
- `GET /api/alerts/unread-count`
- `PATCH /api/alerts/{alert_id}/read`
- `PATCH /api/alerts/{alert_id}/dismiss`
- `POST /api/alerts/read-all`

### Worker / Scheduler / Generation Entry Points

- Scheduler scan/enqueue: `backend/services/watch_scheduler.py`
- Automatic execution entry: `backend/workers/watch_tasks.py`
- Watch run execution: `backend/services/watch_runner.py`
- Signal generation: `backend/services/signal_service.py`
- Alert generation: `backend/services/alert_engine.py`

### Unique Constraints And Indexes

#### Before

- `watch_targets` legacy partial unique key on `(user_id, entity_id, entity_type)` for active rows
- `alerts` legacy uniqueness on `(signal_id, user_id)`

#### After

- `watch_targets`
  - `ix_watch_targets_owner_user_id`
  - `ux_watch_targets_owner_entity_type_active`
- `signals`
  - `ix_signals_owner_user_id_detected_at`
- `alerts`
  - `ix_alerts_owner_user_id_status_created_at`
  - `ux_alerts_signal_id_owner_user_id`

### Response Privacy Audit

- Watch/Signal/Alert responses do not expose:
  - `owner_user_id`
  - internal `users.id`
  - `session_id`
  - `x-session-id`
  - `token_hash`
  - cookie contents
  - `password_hash`

### Current Missing / Empty / Forged x-session-id Behavior

#### Flag=false

- Missing or empty `x-session-id` -> `401 AUTH_REQUIRED`
- Any non-empty `x-session-id` preserves Phase 4 legacy compatibility

#### Flag=true

- `x-session-id` is ignored for authorization
- Unauthenticated requests return `401 AUTH_REQUIRED`
- Auth disabled while ownership enabled returns `503 AUTH_DISABLED`
- Cookie user identity cannot be overridden by `x-session-id`

## Feature Flag Audit

- Added backend flag: `WATCH_ALERT_USER_OWNERSHIP_ENABLED`
- Default: `false`

### Flag=false

- Preserves Phase 4 legacy behavior
- Preserves `x-session-id` compatibility
- Does not require login
- Does not force owner migration
- Existing Phase 4 tests continue passing

### Flag=true

- Requires formal Cookie session auth
- Uses only trusted auth dependency
- Ignores `x-session-id`
- Filters Watch/Signal/Alert strictly by `owner_user_id`
- Hides legacy `owner_user_id IS NULL` rows
- Does not auto-claim anonymous data
- Fails closed when auth is disabled

## Database Migration Audit

### Real Migration Mechanism

- Project uses `init_db()` plus `_ensure_schema_compatibility()` in `backend/models/database.py`
- This phase does not use Alembic
- Compatibility migration is additive and idempotent

### Migration Behavior

- Adds nullable `owner_user_id` columns to `watch_targets`, `signals`, `alerts`
- Adds FK-aware column definitions in compatibility path
- Adds required indexes and partial unique indexes
- Preserves legacy data
- Preserves legacy `user_id`
- Does not rebuild tables in the current implementation path
- Does not delete data

### Before / After Summary

- Before:
  - no `owner_user_id` on `watch_targets`
  - no `owner_user_id` on `signals`
  - no `owner_user_id` on `alerts`
- After:
  - `watch_targets.owner_user_id`
  - `signals.owner_user_id`
  - `alerts.owner_user_id`
  - owner-aware indexes and uniqueness

### Upgrade Validation

- Existing DB upgrade test: `PASS`
- Empty DB init test: `PASS`
- Repeat startup / idempotency test: `PASS`
- Legacy row retention: `PASS`
- Table rebuild required: `NO`

### Rollback Strategy

- Set `WATCH_ALERT_USER_OWNERSHIP_ENABLED=false`
- Keep `owner_user_id` columns in place
- Keep formal ownership data in place
- Keep legacy `user_id` data in place
- No schema deletion required

## Ownership Enforcement

### Current User Dependency

- New mode reuses existing formal auth dependency from Phase 5.1
- No second Cookie parser was introduced
- Watch/Alert routers now share centralized Watch/Alert auth dependency

### No Client Identity Trust

- No owner comes from request body
- No owner comes from query params
- No owner comes from `x-session-id`
- No owner comes from `public_id`
- No owner comes from email

### Watch Ownership

- Create writes `owner_user_id=current_user.id` in new mode
- List filters by owner
- Detail/update/delete/run/signals all resolve through owner-aware lookup
- Cross-user resource access returns `404`
- Same entity can be watched by different users concurrently
- Same user duplicate watch remains blocked

### Signal Ownership Propagation

- Signal creation copies owner from Watch Target in new mode
- Missing owner in new mode raises `SIGNAL_OWNER_REQUIRED`
- Signal listing in new mode filters by exact `owner_user_id`
- Legacy `NULL owner` Signal rows remain hidden

### Alert Ownership Propagation

- Alert engine resolves owner from `signal.owner_user_id` or `watch_target.owner_user_id`
- Missing owner in new mode does not silently create ownerless Alert
- Alert list/unread/read/dismiss/read-all are owner-filtered
- Bulk read-all remains owner-scoped

## Legacy Migration CLI

- File: `backend/scripts/migrate_legacy_watch_alert_owner.py`
- Required args:
  - `--email`
  - `--legacy-session-id`
  - `--database`
  - `--dry-run` or explicit `--apply`
- Default mode: dry-run
- Refuses default backend DB path
- Does not accept password
- Does not create user
- Does not modify `AuthSession`
- Only updates rows where `owner_user_id IS NULL`
- Reports matched / updated / skipped / conflicts per table
- Apply mode runs consistency verification
- Repeated apply is idempotent

## Static Security Check

- Script: `backend/scripts/verify_watch_alert_user_ownership.py`
- Result: `WATCH_ALERT_USER_OWNERSHIP_CHECK=PASS`

## Automated Validation

### Full Regression Batch

- Command:
  - `python -m pytest -q tests/test_auth_models.py tests/test_auth_service.py tests/test_auth_api.py tests/test_create_admin.py tests/test_auth_account_lifecycle.py tests/test_watch_alert_models.py tests/test_watch_targets_api.py tests/test_watch_signals_api.py tests/test_alerts_api.py tests/test_alert_engine.py tests/test_watch_runner.py tests/test_watch_scheduler.py tests/test_watch_retry.py tests/test_watch_alert_user_ownership.py tests/test_watch_alert_owner_migration.py`
- Result:
  - `197 passed`
  - `0 failed`

### Ownership / Migration Focus Batch

- Command:
  - `python -m pytest -q tests/test_watch_runner.py tests/test_watch_signals_api.py tests/test_alerts_api.py tests/test_alert_engine.py tests/test_watch_alert_user_ownership.py tests/test_watch_alert_owner_migration.py tests/test_watch_scheduler.py tests/test_watch_retry.py`
- Result:
  - `108 passed`
  - `0 failed`

### Auth Regression Batch

- Command:
  - `python -m pytest -q tests/test_create_admin.py tests/test_auth_models.py tests/test_auth_service.py tests/test_auth_api.py tests/test_auth_account_lifecycle.py`
- Result:
  - `45 passed`
  - `0 failed`

## Required Result Mapping

- Architecture audit: `PASS`
- Feature flag default off: `PASS`
- Database migration: `PASS`
- Watch owner field: `PASS`
- Signal owner propagation: `PASS`
- Alert owner propagation: `PASS`
- Current user dependency reuse: `PASS`
- No client identity trust: `PASS`
- `x-session-id` ignored in new mode: `PASS`
- Unauthenticated rejected in new mode: `PASS`
- Cross-user Watch isolation: `PASS`
- Cross-user Signal isolation: `PASS`
- Cross-user Alert isolation: `PASS`
- Unread count isolation: `PASS`
- Bulk operation isolation: `PASS`
- Cross-user returns 404: `PASS`
- Legacy `NULL owner` hidden in new mode: `PASS`
- Legacy migration CLI: `PASS`
- Migration dry-run default: `PASS`
- Migration idempotent: `PASS`
- Auth regression: `PASS`
- Phase 4 Watch/Alert regression: `PASS`
- Security check: `PASS`

## Boundary Check

- Verified with:
  - `git status --short`
  - `git diff --name-only`
  - `git diff --stat`
- Result: `PASS`
- No frontend files changed
- No Chat / Conversation / Brain / dashboard unrelated business files changed
- No cookie dump files remain
- No Phase 5.3A temp DB files remain
- No test `_db_backups` created by this phase remain

## Temporary File Cleanup

- Removed test DB backup artifacts under `backend/data/_db_backups`
- Removed temporary probe DB `backend/data/auth_disabled_probe.db`
- Removed accidental terminal dump file `tian-intel-v2`
- Remaining historical backups under repository root `_db_backups` were pre-existing and untouched

## Actual Modified Files

- `backend/config.py`
- `backend/dependencies/auth.py`
- `backend/dependencies/watch_alert_auth.py`
- `backend/models/database.py`
- `backend/models/watch_alert.py`
- `backend/routers/alerts.py`
- `backend/routers/watch_targets.py`
- `backend/scripts/create_admin.py`
- `backend/scripts/migrate_legacy_watch_alert_owner.py`
- `backend/scripts/verify_watch_alert_user_ownership.py`
- `backend/services/alert_engine.py`
- `backend/services/alert_service.py`
- `backend/services/signal_service.py`
- `backend/services/watch_alert_ownership.py`
- `backend/services/watch_runner.py`
- `backend/services/watch_scheduler.py`
- `backend/services/watch_target_service.py`
- `backend/tests/test_alert_engine.py`
- `backend/tests/test_alerts_api.py`
- `backend/tests/test_create_admin.py`
- `backend/tests/test_watch_alert_models.py`
- `backend/tests/test_watch_alert_owner_migration.py`
- `backend/tests/test_watch_alert_user_ownership.py`
- `backend/tests/test_watch_retry.py`
- `backend/tests/test_watch_runner.py`
- `backend/tests/test_watch_scheduler.py`
- `backend/tests/test_watch_signals_api.py`
- `backend/tests/test_watch_targets_api.py`
- `PHASE5_3A_WATCH_ALERT_USER_OWNERSHIP_UAT.md`

## Explicit Non-Goals Still True

- New mode does not auto-claim anonymous data
- New mode does not trust `x-session-id`
- Legacy `user_id` fields remain and are not deleted in this phase
- Feature flag default remains off
- Frontend Watch/Alert identity migration is not done yet
- Frontend Watch/Alert UI should remain disabled
- Production must not enable this by default before Phase 5.3B
- Chat is still not migrated to formal user ownership
- Frontend guards are not backend authorization boundaries
- Legacy data can only be claimed via explicit CLI

## Known Limitations

- This phase does not migrate Chat / Conversation ownership
- Legacy anonymous data remains invisible in new mode until explicit CLI migration
- Deprecation warnings from FastAPI `on_event` and SQLAlchemy `declarative_base()` remain outside this phase scope

## Release / Next Phase Decision

- `READY_FOR_EXTERNAL_COMMIT=true`
- `READY_FOR_PHASE5_3B=true`
