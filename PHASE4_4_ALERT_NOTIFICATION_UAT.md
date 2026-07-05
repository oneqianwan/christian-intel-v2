# PHASE4_4_ALERT_NOTIFICATION_UAT

## 1. Scope

- Phase: 4.4 Alert Engine and Notification API
- Worktree: `C:\Users\baiwan\christian-intel-v2-phase4`
- Branch: `phase4/watch-alert-v1`
- Constraint status:
  - No DB schema change
  - No frontend change
  - No `brain.py` / `pipeline_orchestrator.py` / `insight_*` / `answer_composer.py` / `workflow_executor.py` / `chat.py` / crawler changes
  - No prompt/tool changes

## 2. Actual Modified Files

- `backend/config.py`
- `backend/main.py`
- `backend/schemas/watch_alert.py`
- `backend/services/signal_service.py`
- `backend/services/watch_runner.py`
- `backend/services/alert_rule_service.py`
- `backend/services/alert_engine.py`
- `backend/services/alert_service.py`
- `backend/routers/alerts.py`
- `backend/tests/test_alert_engine.py`
- `backend/tests/test_alerts_api.py`
- `PHASE4_4_ALERT_NOTIFICATION_UAT.md`

## 3. Feature Flag Behavior

Added default in `backend/config.py`:

- `WATCH_ALERT_NOTIFICATIONS_ENABLED=false`

Effective enable condition:

- `WATCH_ALERT_V1_ENABLED=true`
- `WATCH_ALERT_NOTIFICATIONS_ENABLED=true`

Verified behavior:

- Notifications flag off -> Signal still generates normally: PASS
- Notifications flag off -> Alert Engine skips alert creation: PASS
- Notifications flag off -> Alerts API returns `HTTP 503`: PASS
- V1 flag off -> Alerts API returns `HTTP 503`: PASS
- Watchlist / Scheduler / WatchRun / Signals API remain functional: PASS

503 error contract:

- `error_code=WATCH_ALERT_NOTIFICATIONS_DISABLED`

## 4. Default Rules

Implemented explicit initialization through:

- `ensure_default_alert_rules()`

Initialization guardrails:

- No database write at module import time
- Called explicitly by Alert Engine entry path
- Idempotent creation only for missing system defaults
- Existing rules are not overwritten on repeated calls

System default rules use `user_id=NULL`:

| Signal Type | Minimum Severity |
| --- | --- |
| `leadership_change` | `high` |
| `score_change` | `medium` |
| `contact_change` | `medium` |
| `website_change` | `medium` |
| `relation_change` | `medium` |
| `new_news` | `low` |
| `new_video` | `low` |
| `new_intelligence` | `low` |

Verified result:

- Default rule creation is idempotent: PASS
- System default rules are not duplicated: PASS

## 5. User Rule Override Logic

Rule selection order during Signal processing:

1. Use user-specific rule by `user_id + signal_type`
2. Fallback to system default rule by `user_id IS NULL + signal_type`
3. No rule -> no Alert
4. `is_enabled=false` -> no Alert
5. `signal.severity < minimum_severity` -> no Alert

Verified result:

- User rule overrides system default when present: PASS
- Disabled rule blocks Alert generation: PASS

## 6. Severity Comparison

Severity order:

- `low < medium < high < critical`

Generation rule:

- Create Alert only when `Signal.severity >= AlertRule.minimum_severity`

Verified result:

- Below threshold does not generate Alert: PASS
- Equal threshold generates Alert: PASS
- Above threshold generates Alert: PASS
- `leadership_change` with `high` severity generates Alert: PASS
- `score_change` with `medium` severity generates Alert: PASS
- `new_news` with `low` severity generates Alert: PASS

## 7. Signal To Alert Flow

Implemented backend flow:

`Signal -> AlertRule -> Alert -> Notification API -> read/read-all/dismiss`

Alert creation copies:

- `user_id` from `WatchTarget.user_id`
- `watch_target_id`
- `signal_id`
- `title`
- `summary`
- `severity`
- `source_url`
- `status=unread`

Source URL rule:

- Stored only when empty or real `http://` / `https://` URL
- Invalid or synthetic URL is normalized to `NULL`

Verified result:

- Alert `user_id` always comes from `WatchTarget`: PASS
- `source_url` is empty or real URL only: PASS

## 8. Deduplication

Deduplication rule:

- One Signal can generate at most one Alert per user
- Reuses existing DB unique constraint on `signal_id + user_id`
- Integrity conflict is treated as already processed, not as WatchRun failure

Verified result:

- Same Signal does not generate duplicate Alert: PASS
- Signal deduplication also prevents Alert duplication in follow-up runs: PASS

## 9. WatchRunner Integration

Integrated path:

1. Detect changes
2. Persist only newly created Signals for the current run
3. Pass only new Signal IDs into `AlertEngine.process_signals(...)`
4. Write actual created count into `WatchRun.alerts_created`

Guardrails:

- Baseline run creates no Signal and therefore no Alert
- No-change run creates no Signal and therefore no Alert
- Notifications flag off skips Alert Engine directly
- Single-signal Alert Engine failure does not undo completed Snapshot or Signal work
- Batch-level unknown exception is logged and does not leave `WatchRun` in `running`

Verified result:

- First baseline run generates no Alert: PASS
- No-change follow-up run generates no Alert: PASS
- `WatchRun.alerts_created` equals actual new Alert count: PASS
- Alert Engine exception does not leave `WatchRun` stuck in `running`: PASS

## 10. Notification API Contracts

Base path:

- `/api/alerts`

Common rules for all endpoints:

- Current user identity only
- No `user_id` request parameter accepted
- Unauthorized request returns `401`
- Feature disabled returns `503`
- Ownership mismatch returns `404`
- Response never includes `user_id`

### 10.1 `GET /api/alerts`

Query params:

- `status`
- `severity`
- `watch_target_id`
- `page`
- `page_size`

Behavior:

- Ordered by `created_at DESC`
- Default `page=1`
- Default `page_size=20`
- Maximum `page_size=100`
- Default result includes all statuses unless a `status` filter is provided
- Pagination and filtering are executed in the DB layer

Response:

```json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 0
}
```

### 10.2 `GET /api/alerts/unread-count`

Behavior:

- Counts only current user's `status=unread`

Response:

```json
{
  "unread_count": 3
}
```

### 10.3 `PATCH /api/alerts/{id}/read`

Behavior:

- `unread -> read`
- `read -> read` is idempotent success
- `dismissed -> read` is rejected

Error codes:

- `ALERT_NOT_FOUND`
- `ALERT_DISMISSED`

### 10.4 `PATCH /api/alerts/{id}/dismiss`

Behavior:

- `unread -> dismissed`
- `read -> dismissed`
- `dismissed -> dismissed` is idempotent success

### 10.5 `POST /api/alerts/read-all`

Behavior:

- Updates only current user's `status=unread`
- Does not modify `dismissed`

Response:

```json
{
  "updated_count": 5
}
```

## 11. Multi-User Isolation

Verified result:

- User can list only own Alerts: PASS
- User can count only own unread Alerts: PASS
- User cannot modify another user's Alert: PASS
- Ownership mismatch consistently returns `404`: PASS
- API response does not expose `user_id`: PASS

## 12. State Transition Rules

Allowed and verified:

- `unread -> read`: PASS
- `unread -> dismissed`: PASS
- `read -> dismissed`: PASS
- `read -> read`: PASS
- `dismissed -> dismissed`: PASS

Blocked and verified:

- `dismissed -> read`: PASS
- `dismissed -> unread`: no API provided, PASS by contract
- `read -> unread`: no API provided, PASS by contract

## 13. Test Commands Executed

Executed for Phase 4.4 verification:

- `python -m pytest backend/tests/test_alert_engine.py -v`
- `python -m pytest backend/tests/test_alerts_api.py -v`
- `python -m pytest backend/tests/test_watch_scheduler.py -v`
- `python -m pytest backend/tests/test_watch_retry.py -v`
- `python -m pytest backend/tests/test_watch_runner.py -v`
- `python -m pytest backend/tests/test_watch_signals_api.py -v`
- `python -m pytest backend/tests/test_watch_targets_api.py -v`
- `python -m pytest backend/tests/test_watch_alert_models.py -v`

Observed result summary:

- `test_alert_engine.py`: 12 passed
- `test_alerts_api.py`: 17 passed
- `test_watch_scheduler.py`: 13 passed
- `test_watch_retry.py`: 15 passed
- `test_watch_runner.py`: 27 passed
- `test_watch_signals_api.py`: 4 passed
- `test_watch_targets_api.py`: 25 passed
- `test_watch_alert_models.py`: 19 passed

Total executed in phase-close verification:

- 132 passed

Core smoke/regression note:

- No separate `smoke`-named suite exists in `backend/tests`
- Existing core API, runner, model, and import/regression suites above were executed as the project smoke/regression baseline

## 14. 40-Item Test Matrix

1. Notification Flag disabled does not generate Alert: PASS
2. Notification Flag disabled returns API 503: PASS
3. V1 Flag disabled returns API 503: PASS
4. Unauthenticated Alerts API access returns 401: PASS
5. Default rules are idempotent: PASS
6. System default rules are not duplicated: PASS
7. User rule overrides system rule: PASS
8. Disabled rule does not generate Alert: PASS
9. Below minimum severity does not generate Alert: PASS
10. Equal minimum severity generates Alert: PASS
11. Above minimum severity generates Alert: PASS
12. `leadership_change` with `high` severity generates Alert: PASS
13. `score_change` with `medium` severity generates Alert: PASS
14. `new_news` with `low` severity generates Alert: PASS
15. Same Signal does not create duplicate Alert: PASS
16. Alert `user_id` comes from `WatchTarget`: PASS
17. Alert `source_url` is empty or real URL: PASS
18. First baseline run does not generate Alert: PASS
19. No-change run does not generate Alert: PASS
20. New Signal updates `WatchRun.alerts_created` correctly: PASS
21. Alert Engine exception does not leave `WatchRun` running: PASS
22. User can only view own Alerts: PASS
23. Alert list pagination works correctly: PASS
24. `status` filter works correctly: PASS
25. `severity` filter works correctly: PASS
26. `watch_target_id` filter works correctly: PASS
27. `unread-count` only counts current user: PASS
28. Unread Alert can be marked read: PASS
29. Repeated read is idempotent: PASS
30. Dismissed Alert cannot be marked read: PASS
31. Alert can be dismissed: PASS
32. Repeated dismiss is idempotent: PASS
33. `read-all` only updates current user unread Alerts: PASS
34. `read-all` does not modify dismissed Alerts: PASS
35. Other user modifying Alert returns 404: PASS
36. API response does not contain `user_id`: PASS
37. Deleting `WatchTarget` does not delete history Alert: PASS
38. Signal dedup also prevents duplicate Alert: PASS
39. Watchlist / Runner / Scheduler / Signals API regression passes: PASS
40. Insight / Chat / Database regression passes: PASS

## 15. Regression Result

Validated through executed suites:

- `backend/tests/test_watch_runner.py`
  - watch execution regression
  - `WatchRun.alerts_created` regression
- `backend/tests/test_watch_targets_api.py`
  - watchlist API regression
  - authentication and ownership regression
- `backend/tests/test_watch_signals_api.py`
  - signals API regression
- `backend/tests/test_watch_scheduler.py`
  - scheduler regression
- `backend/tests/test_watch_retry.py`
  - retry and auto-pause regression
- `backend/tests/test_watch_alert_models.py`
  - model integrity and import regression
- `backend/tests/test_alert_engine.py`
  - default rules, threshold, dedup, runner integration
- `backend/tests/test_alerts_api.py`
  - notification API contract and state transition regression

Result:

- No regression detected in Watchlist: PASS
- No regression detected in Runner: PASS
- No regression detected in Scheduler: PASS
- No regression detected in Signals API: PASS
- No regression detected in Insight imports: PASS
- No regression detected in Chat imports: PASS
- No regression detected in Database model integrity: PASS

## 16. Boundary Check

Commands executed:

- `git status --short`
- `git diff --stat`
- `git diff --name-only`

Result:

- Modified files are only within the allowed Phase 4.4 scope
- No forbidden changes detected in:
  - `brain.py`
  - `pipeline_orchestrator.py`
  - `insight_*`
  - `answer_composer.py`
  - `workflow_executor.py`
  - crawler files
  - frontend files
  - database schema/model structure files

Boundary snapshot:

- Modified: `backend/config.py`
- Modified: `backend/main.py`
- Modified: `backend/schemas/watch_alert.py`
- Modified: `backend/services/signal_service.py`
- Modified: `backend/services/watch_runner.py`
- New: `backend/services/alert_rule_service.py`
- New: `backend/services/alert_engine.py`
- New: `backend/services/alert_service.py`
- New: `backend/routers/alerts.py`
- New: `backend/tests/test_alert_engine.py`
- New: `backend/tests/test_alerts_api.py`
- New: `PHASE4_4_ALERT_NOTIFICATION_UAT.md`

## 17. Rollback Method

Rollback scope for Phase 4.4 only:

- Revert modified files listed in Section 2
- Remove newly added alert service/router/test/UAT files
- Redeploy with:
  - `WATCH_ALERT_NOTIFICATIONS_ENABLED=false`
  - or `WATCH_ALERT_V1_ENABLED=false`

No database rollback or migration rollback is required because no schema change was introduced.

## 18. Final UAT Verdict

- AlertEngine=PASS
- DefaultRules=PASS
- AlertDeduplication=PASS
- NotificationAPI=PASS
- UnreadCount=PASS
- AlertStateTransitions=PASS
- MultiUserIsolation=PASS
- Regression=PASS
- BoundaryCheck=PASS
- READY_FOR_PHASE4_5=true
