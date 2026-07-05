# PHASE4_3B_WATCH_SCHEDULER_UAT

## 1. Scope

- Phase: 4.3B Watch auto scheduling and retry
- Worktree: `C:\Users\baiwan\christian-intel-v2-phase4`
- Branch: `phase4/watch-alert-v1`
- Constraint status:
  - No DB schema change
  - No frontend change
  - No `brain.py` / `pipeline_orchestrator.py` / `insight_*` / `answer_composer.py` / `workflow_executor.py` / `chat.py` / crawler changes

## 2. Actual Modified Files

- `backend/config.py`
- `backend/queue_client.py`
- `backend/services/watch_runner.py`
- `backend/services/watch_target_service.py`
- `backend/services/watch_scheduler.py`
- `backend/workers/watch_tasks.py`
- `backend/scripts/run_watch_scheduler.py`
- `backend/tests/test_watch_scheduler.py`
- `backend/tests/test_watch_retry.py`
- `PHASE4_3B_WATCH_SCHEDULER_UAT.md`

## 3. Scheduler Execution Mode

- One-shot entry:
  - `python -m backend.scripts.run_watch_scheduler`
- Behavior:
  - Runs one scan round
  - Enqueues due watch targets
  - Prints structured scan stats
  - Exits normally
- No resident loop in FastAPI import path
- No second queue system
- No Celery
- No web-process scheduler thread

## 4. RQ Reuse

- Reused existing Redis + RQ connection via `backend/queue_client.py`
- Reused existing `collection` queue through `get_collection_queue()`
- Scheduler enqueues `workers.watch_tasks.execute_watch_target_job`
- Worker reuses existing `services.watch_runner.run_watch_target(...)`
- No duplicated snapshot builder / change detector / signal creation pipeline

## 5. schtasks Reuse

- Phase 4.3B provides the one-shot scheduler entry required by current project scheduling style
- Intended invocation pattern remains the same as existing Windows Task Scheduler flow: trigger every 5 minutes and execute the one-shot Python entry
- No new long-running scheduler service was introduced
- No additional queue runtime was introduced
- No existing schtasks install script was modified in this phase

## 6. Feature Flags

Added defaults in `backend/config.py`:

- `WATCH_ALERT_SCHEDULER_ENABLED=false`
- `WATCH_ALERT_SCHEDULER_INTERVAL_SECONDS=300`
- `WATCH_ALERT_MAX_RETRIES=3`
- `WATCH_ALERT_RETRY_BASE_SECONDS=300`
- `WATCH_ALERT_MAX_CONSECUTIVE_FAILURES=5`

Effective behavior:

- Scheduler disabled -> no scan / no enqueue / no auto execution
- `WATCH_ALERT_V1_ENABLED=false` -> scheduler also inactive
- Manual run path remains available

## 7. Due Target Scan Conditions

Implemented by `scan_due_watch_targets(now=None, limit=100)` with ORM filters:

- `WatchTarget.deleted_at.is_(None)`
- `WatchTarget.status == "active"`
- `WatchTarget.frequency.in_(("daily", "weekly"))`
- `WatchTarget.next_check_at.is_not(None)`
- `WatchTarget.next_check_at <= now`
- `WatchTarget.consecutive_failures < WATCH_ALERT_MAX_CONSECUTIVE_FAILURES`
- `~exists(running WatchRun for same watch_target_id)`

Ordering and limit:

- `ORDER BY next_check_at ASC`
- Max per round: `min(limit, 100)`

Excluded by rule:

- `manual`
- `paused`
- `disabled`
- soft deleted targets
- not due targets
- targets with existing running `WatchRun`
- targets at or above consecutive failure threshold

## 8. Job ID Deduplication

Scheduled job ID:

- `watch-target:{watch_target_id}:{scheduled_timestamp}`

Retry job ID:

- `watch-target:{watch_target_id}:retry:{watch_run_id}:{retry_number}`

Dedup checks before enqueue:

- target still `active`
- `next_check_at` still due
- no running `WatchRun`
- queue has no existing identical `job_id`

Duplicate handling:

- create skipped `WatchRun`
- `status=skipped`
- `error_code=WATCH_RUN_DUPLICATE`
- no extra execution
- no `consecutive_failures` increment

## 9. next_check_at Rules

Create or restore active target:

- `daily -> now + 24h`
- `weekly -> now + 7d`
- `manual -> NULL`

Update frequency or status:

- recalculated through `compute_next_check_at_for_state(...)`
- `paused` / `disabled` -> `NULL`

Automatic success:

- computed with `advance_next_check_at(...)`
- advances from original scheduled time, not actual delayed execution time
- catches up to first future slot only
- `manual` remains `NULL`

Success state updates:

- `consecutive_failures = 0`
- `last_success_at = now`
- `last_checked_at = now`
- `next_check_at = next cycle`

## 10. Retry Backoff Rules

Retry delay formula:

- `WATCH_ALERT_RETRY_BASE_SECONDS * 2^(retry_number - 1)`

With default config:

- retry 1 -> 5 minutes
- retry 2 -> 10 minutes
- retry 3 -> 20 minutes

Retry scheduling behavior:

- worker failure on retryable error schedules next retry job
- current `WatchRun` stays `pending`
- target `next_check_at` moves to retry time

Stop condition:

- when `retry_number >= WATCH_ALERT_MAX_RETRIES`, current run becomes `failed`
- no retry 4 is enqueued
- normal periodic `next_check_at` is resumed unless auto-pause threshold is hit

## 11. Retryable vs Non-Retryable Classification

Non-retryable:

- `WATCH_TARGET_ENTITY_NOT_FOUND`
- `WATCH_TARGET_DISABLED`
- `WATCH_TARGET_NOT_FOUND`
- `WATCH_RUN_DUPLICATE`
- lookup / invalid-reference style errors

Retryable:

- `TimeoutError`
- `ConnectionError`
- `sqlalchemy.exc.OperationalError`
- temporary/timeout/database locked/connection reset style transient messages

Guardrail:

- programming/config errors do not loop forever
- non-retryable failures stop without re-enqueue

## 12. Auto Pause Rule

When `consecutive_failures >= WATCH_ALERT_MAX_CONSECUTIVE_FAILURES`:

- `WatchTarget.status = "paused"`
- `WatchTarget.next_check_at = NULL`
- `WatchRun.error_code = WATCH_TARGET_AUTO_PAUSED`
- target is preserved, not deleted

## 13. Logging and Structured Stats

Scheduler one-round stats output:

- `scan_started_at`
- `due_count`
- `enqueued_count`
- `duplicate_count`
- `skipped_count`
- `failed_count`
- `scan_finished_at`
- `duration_ms`

Worker log payload:

- `watch_target_id`
- `watch_run_id`
- `rq_job_id`
- `retry_number`
- `status`

## 14. Test Commands Executed

Executed exactly for Phase 4.3B verification:

- `python -m pytest backend/tests/test_watch_scheduler.py -v`
- `python -m pytest backend/tests/test_watch_retry.py -v`
- `python -m pytest backend/tests/test_watch_runner.py -v`
- `python -m pytest backend/tests/test_watch_targets_api.py -v`
- `python -m pytest backend/tests/test_watch_signals_api.py -v`
- `python -m pytest backend/tests/test_watch_alert_models.py -v`

Observed result summary:

- `test_watch_scheduler.py`: 13 passed
- `test_watch_retry.py`: 15 passed
- `test_watch_runner.py`: 27 passed
- `test_watch_targets_api.py`: 25 passed
- `test_watch_signals_api.py`: 4 passed
- `test_watch_alert_models.py`: 19 passed

Total executed in this phase-close pass:

- 103 passed

## 15. 35-Item Test Matrix

1. Scheduler Flag off does not scan: PASS
2. V1 Flag off does not scan: PASS
3. Daily due target enqueued: PASS
4. Weekly due target enqueued: PASS
5. Manual target not enqueued: PASS
6. Paused target not enqueued: PASS
7. Disabled target not enqueued: PASS
8. Soft-deleted target not enqueued: PASS
9. Future target not enqueued: PASS
10. Existing running `WatchRun` not re-enqueued: PASS
11. Same scheduled `job_id` not duplicated: PASS
12. Per-round limit enforced: PASS
13. Due targets ordered by `next_check_at ASC`: PASS
14. Worker reuses `WatchRunner.run_watch_target(...)`: PASS
15. Automatic run creates normal `WatchRun`: PASS
16. Automatic success computes next daily cycle: PASS
17. Automatic success computes next weekly cycle: PASS
18. Delayed execution does not create permanent drift: PASS
19. Frequency change recalculates `next_check_at`: PASS
20. `paused` / `disabled` sets `next_check_at=NULL`: PASS
21. Restore `active` recalculates `next_check_at`: PASS
22. First retry scheduled at 5 minutes: PASS
23. Second retry scheduled at 10 minutes: PASS
24. Third retry scheduled at 20 minutes: PASS
25. Retry stops after max retries: PASS
26. Non-retryable error does not schedule retry: PASS
27. Duplicate task does not increment `consecutive_failures`: PASS
28. Success clears `consecutive_failures`: PASS
29. Failure increments `consecutive_failures`: PASS
30. Five consecutive failures auto-pause target: PASS
31. Auto-paused target clears `next_check_at`: PASS
32. Scheduler single round exits normally: PASS
33. Worker exception leaves no running `WatchRun`: PASS
34. Manual run path remains operational: PASS
35. Watchlist / Signals / Insight / Chat / Database regression pass: PASS

## 16. Regression Result

Validated through existing regression/import coverage already present in executed suites:

- `backend/tests/test_watch_runner.py`
  - watch execution core regression
  - import regression
- `backend/tests/test_watch_targets_api.py`
  - watchlist API regression
  - insight/database/chat import regression
- `backend/tests/test_watch_signals_api.py`
  - signals API regression
- `backend/tests/test_watch_alert_models.py`
  - model integrity and import regression

Result:

- No regression detected in Watchlist
- No regression detected in Signals
- No regression detected in Insight imports
- No regression detected in Chat imports
- No regression detected in database model integrity

## 17. Boundary Check

Commands executed:

- `git status --short`
- `git diff --stat`
- `git diff --name-only`

Result:

- Only allowed watch scheduler / retry files are modified or newly added
- No forbidden changes detected in:
  - `brain.py`
  - `pipeline_orchestrator.py`
  - `insight_*`
  - `answer_composer.py`
  - `workflow_executor.py`
  - `chat.py`
  - crawler files
  - frontend files
  - database schema/model structure files

Current boundary snapshot:

- Modified: `backend/config.py`
- Modified: `backend/queue_client.py`
- Modified: `backend/services/watch_runner.py`
- Modified: `backend/services/watch_target_service.py`
- New: `backend/scripts/run_watch_scheduler.py`
- New: `backend/services/watch_scheduler.py`
- New: `backend/tests/test_watch_retry.py`
- New: `backend/tests/test_watch_scheduler.py`
- New: `backend/workers/watch_tasks.py`

## 18. Stop Scheduler Method

Because the scheduler is one-shot, there is no resident scheduler process to kill.

Stop methods:

- Set `WATCH_ALERT_SCHEDULER_ENABLED=false`
- Or set `WATCH_ALERT_V1_ENABLED=false`
- Or disable/remove the Windows Task Scheduler trigger that invokes the one-shot command

## 19. Rollback Method

Rollback scope for Phase 4.3B only:

- revert the modified files listed in Section 2
- remove newly added scheduler/worker/test files
- redeploy with:
  - `WATCH_ALERT_SCHEDULER_ENABLED=false`
  - optionally `WATCH_ALERT_V1_ENABLED=false`

No database rollback or migration rollback is required because no schema change was introduced.

## 20. Final UAT Verdict

- DueScheduler=PASS
- QueueDeduplication=PASS
- NextCheckCalculation=PASS
- RetryBackoff=PASS
- AutoPause=PASS
- WorkerIntegration=PASS
- Regression=PASS
- BoundaryCheck=PASS
- READY_FOR_PHASE4_4=true
