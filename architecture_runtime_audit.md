# Architecture Runtime Audit V1

## Scope

- Audit date: 2026-07-02
- Target: Runtime validation only, no business feature changes
- Runtime method:
  - 5 synthetic requests executed through `Brain.think()`
  - `ServiceContainer` resolution and instantiation counted at runtime
  - `MemoryLayer` and `KnowledgeLayer` validated with direct runtime micro-tests
  - Compatibility smoke tests executed for all major `*_ENABLED` flags in both `ON` and `OFF` paths
- Runtime constraints:
  - External LLM and tool side effects were stubbed at runtime only
  - No business code path was modified during the audit

## Service Tree

Observed runtime service resolution tree:

```text
Brain
└── architecture_governor
    ├── pipeline_service
    │   ├── answer_composer
    │   ├── capability_planner
    │   ├── knowledge_layer
    │   ├── memory_layer
    │   ├── reasoning_engine
    │   ├── retrieval_loop_controller
    │   └── tool_registry
    └── trace_center

retrieval_loop_controller
├── capability_planner
├── tool_registry
└── trace_center
```

Observed facts:

- `Brain -> architecture_governor` was hit in all 5 audited requests.
- `architecture_governor -> pipeline_service` was hit in all 5 audited requests.
- `pipeline_service` successfully resolved `reasoning_engine`, `knowledge_layer`, `memory_layer`, `answer_composer`, `tool_registry`, `capability_planner`, `retrieval_loop_controller`.
- `trace_center` was resolved at Governor and loop-related runtime.

## Container Statistics

| Event | Count |
| --- | ---: |
| Container Initialized | 1 |
| Service Registered | 10 |
| Service Resolved | 114 |
| Singleton Created | 5 |
| Dependency Resolved | 32 |
| SERVICE_CONTAINER Stage Ended | 5 |

### Singleton Validation

| Service | Singleton | Actual Instance Count |
| --- | --- | ---: |
| answer_composer | Yes | 1 |
| architecture_governor | No | 5 |
| capability_planner | Yes | 1 |
| knowledge_layer | No | 11 |
| memory_layer | No | 5 |
| pipeline_service | No | 5 |
| reasoning_engine | Yes | 1 |
| retrieval_loop_controller | No | 16 |
| tool_registry | Yes | 1 |
| trace_center | Yes | 1 |

Verdict:

- No singleton violation was observed.
- All services marked `singleton=Yes` were instantiated exactly once in the audited container lifecycle.
- `knowledge_layer`, `memory_layer`, `pipeline_service`, `architecture_governor`, `retrieval_loop_controller` are intentionally non-singleton today, so their multiple instances are not runtime defects, but they are an architectural cost point.

## Governor Statistics

### Headline

- Governor hits: 5
- Pipeline execute hits: 5
- Fallback hits: 0

### Pipeline Selection Matrix

| Question | Selected Pipeline | Fallback Pipeline |
| --- | --- | --- |
| OpenAI organization profile and leadership | StandardPipeline | StandardPipeline |
| What is the relationship graph of OpenAI and Microsoft? | StandardPipeline | StandardPipeline |
| What are OpenAI investment activities? | StandardPipeline | ResearchPipeline |
| OpenAI timeline and latest news | ResearchPipeline | StandardPipeline |
| OpenAI organization profile and leadership | StandardPipeline | StandardPipeline |

### Selection Distribution

| Pipeline | Hit Count |
| --- | ---: |
| StandardPipeline | 4 |
| ResearchPipeline | 1 |

Governor runtime verdict:

- Governor is not dead code. It was entered and completed for every audited request.
- Pipeline selection is real runtime behavior, not just static wiring.
- Current selection is conservative: `StandardPipeline` dominates, and specialized pipelines are under-hit in this audit suite.

## Pipeline Runtime

### Stage Statistics

| Stage | Enter | Exit | Avg ms | Failures |
| --- | ---: | ---: | ---: | ---: |
| QUESTION | 0 | 0 | 0.00 | 0 |
| QUESTION_CONTEXT | 0 | 0 | 0.00 | 0 |
| MEMORY_LOAD | 5 | 5 | 0.22 | 0 |
| REQUIREMENT | 5 | 5 | 4.58 | 0 |
| RETRIEVAL | 8 | 8 | 12.91 | 0 |
| KNOWLEDGE_LAYER | 11 | 11 | 2.61 | 0 |
| MEMORY_UPDATE | 8 | 8 | 7.10 | 0 |
| REASONING | 11 | 11 | 4.97 | 0 |
| COMPOSER | 8 | 8 | 7.62 | 0 |
| VERIFICATION | 8 | 8 | 7.24 | 0 |
| RETRIEVAL_LOOP | 10 | 5 | 7.73 | 0 |
| MEMORY_SNAPSHOT | 10 | 10 | 0.10 | 0 |
| LLM | 5 | 5 | 0.02 | 0 |
| DELIVERY | 0 | 0 | 0.00 | 0 |

### Runtime Findings

- `MEMORY_LOAD`, `REQUIREMENT`, `RETRIEVAL`, `KNOWLEDGE_LAYER`, `MEMORY_UPDATE`, `REASONING`, `COMPOSER`, `VERIFICATION`, `RETRIEVAL_LOOP`, `MEMORY_SNAPSHOT`, `LLM` are all live runtime stages.
- `QUESTION`, `QUESTION_CONTEXT`, `DELIVERY` are declared in the enum but were not entered at runtime in the audited path.
- `RETRIEVAL_LOOP` has an enter/exit mismatch: entered 10 times, exited 5 times. This is a runtime observability defect even though no failure was thrown.

## Memory Statistics

### Runtime Result

| Metric | Value |
| --- | ---: |
| SessionMemory created | 1 |
| SessionMemory restored | 1 |
| EntityMemory created | 1 |
| EntityMemory restored | 1 |
| RetrievalCache entries created | 1 |
| KnowledgeSnapshot created | 1 |
| KnowledgeSnapshot restored | 1 |
| Cache hit | 1 |
| Cache miss | 1 |
| TTL expired | 1 |
| Duplicate query avoided | 1 |
| Cache hit rate | 0.50 |
| TTL hit rate | 0.50 |

### Runtime Verdict

- `SessionMemory`, `EntityMemory`, `RetrievalCache`, `KnowledgeSnapshot` are all live runtime objects.
- Snapshot restore works.
- Retrieval cache hit and TTL expiry paths both work.
- Duplicate query avoidance exists at runtime, not just by design.

## Retrieval Cache Statistics

| Metric | Value |
| --- | ---: |
| Cache Hit | 1 |
| Cache Miss | 1 |
| TTL Expired | 1 |
| Duplicate Query Avoided | 1 |

Runtime verdict:

- Retrieval cache is operational.
- Cache hit path and TTL expiry path are both executable.
- Current audit only proves functionality, not production-grade hit quality.

## Knowledge Statistics

| Metric | Value |
| --- | ---: |
| Nodes | 5 |
| Relations | 2 |
| Merge Count | 5 |
| Node Merge Success | 3 |
| Relation Merge Success | 2 |
| Conflict Count | 1 |
| Conflict Merge | 1 |

Runtime verdict:

- Knowledge graph ingestion is live.
- Node merge and relation merge both happen at runtime.
- Conflict tracking is live through `_conflicts`.

## Trace Coverage

| Domain | Covered | Missing |
| --- | --- | --- |
| Governor | Yes | No |
| Pipeline | Yes | No |
| Knowledge | Yes | No |
| Memory | Yes | No |
| Reasoning | Yes | No |
| Composer | Yes | No |
| Verification | Yes | No |
| Loop | Yes | No |
| LLM | Yes | No |
| Container | Yes | No |

Trace verdict:

- Coverage is complete for the requested domains.
- However, stage taxonomy is inconsistent: enum uses `ANSWER_COMPOSER`, runtime trace uses `COMPOSER`.

## Dead Code Report

High-confidence dead or effectively unused paths observed in this audit window:

1. `PipelineStage.QUESTION`
   - Declared, but no runtime enter/exit observed.
2. `PipelineStage.QUESTION_CONTEXT`
   - Declared, but no runtime enter/exit observed.
3. `PipelineStage.DELIVERY`
   - Declared, but no runtime enter/exit observed.
4. `PipelineStage.ANSWER_COMPOSER`
   - Declared in enum, but runtime trace emits `COMPOSER`, so the enum value is disconnected from actual stage telemetry.
5. `ArchitectureGovernor.should_switch_pipeline()`
   - Only definition found in scan; no runtime use observed.
6. `ServiceContainer.unregister()`
   - No runtime call site observed in the scanned codebase path.
7. `ServiceContainer.initialize_singletons()`
   - No runtime call site observed in the scanned codebase path.
8. `ServiceContainer.shutdown()`
   - No runtime call site observed in the scanned codebase path.
9. Module-level `think()` adapter in `brain.py`
   - Present as a legacy wrapper; not part of the audited primary runtime path.

## Compatibility Matrix

| Flag | ON Path | OFF Path | Notes |
| --- | --- | --- | --- |
| SERVICE_CONTAINER_ENABLED | Pass | Pass | Container and legacy path both executable |
| ARCHITECTURE_GOVERNOR_ENABLED | Pass | Pass | Governor path and direct pipeline path both executable |
| PIPELINE_ORCHESTRATOR_ENABLED | Pass | Pass | OFF path runs legacy `Brain` flow; output shape diverges strongly |
| TRACE_CENTER_ENABLED | Pass | Pass | Trace-free path still runs |
| KNOWLEDGE_LAYER_ENABLED | Pass | Pass | Fallback path still answers |
| MEMORY_LAYER_ENABLED | Pass | Pass | Stateless path still answers |
| RETRIEVAL_LOOP_ENABLED | Pass | Pass | Loop optionality works |
| TOOL_REGISTRY_ENABLED | Pass | Pass | Legacy tool planning path still works |
| CAPABILITY_PLANNER_ENABLED | Pass | Pass | Fallback planning path still works |
| ANSWER_COMPOSER_ENABLED | Pass | Pass | Composer optionality works |
| REASONING_ENGINE_V1_ENABLED | Pass | Pass | Legacy fallback path still works |

Compatibility verdict:

- All audited flag `ON/OFF` paths were runnable.
- The biggest behavioral divergence is `PIPELINE_ORCHESTRATOR_ENABLED=0`: the legacy path returned a much larger answer payload in the audit, which indicates output behavior drift between new and old paths.

## Architecture Smell Report

1. God Object
   - `brain.py` remains the dominant god object and legacy adapter.
2. Long Function
   - `Brain.think()`, `Brain.think_stream()`, `PipelineOrchestrator._execute_selected_pipeline()`, `PipelineOrchestrator._final_generate_from_tool_results()` are runtime-heavy long functions.
3. Duplicate Logic
   - `think()` and `think_stream()` still duplicate large chunks of orchestration logic.
4. Legacy Divergence
   - `PIPELINE_ORCHESTRATOR_ENABLED=0` produces materially different behavior from the orchestrated path.
5. Stage Naming Drift
   - Enum defines `ANSWER_COMPOSER`, runtime trace emits `COMPOSER`.
6. Partial Stage Instrumentation
   - `QUESTION`, `QUESTION_CONTEXT`, `DELIVERY` exist in design but are absent in runtime telemetry.
7. Loop Trace Imbalance
   - `RETRIEVAL_LOOP` enter count is double exit count in the audit run.
8. Too Many Flags
   - 11 `*_ENABLED` flags are now participating in control flow across 6 service files.
9. High Non-Singleton Churn
   - `knowledge_layer`, `memory_layer`, `pipeline_service`, `architecture_governor`, `retrieval_loop_controller` are instantiated repeatedly in the same audit lifecycle.
10. Lazy Container Without Shutdown Use
    - `shutdown()` exists in the container contract but is not exercised in the live request path.

## Overall Score

- Overall Score: **81 / 100**

Scoring rationale:

- + Strong runtime proof that Container, Governor, Pipeline, Memory, Knowledge, Trace all execute.
- + Singleton behavior is correct for all services declared as singleton.
- + Compatibility matrix is healthy: every audited `ON/OFF` path was runnable.
- - Runtime telemetry is incomplete for `QUESTION`, `QUESTION_CONTEXT`, `DELIVERY`.
- - Stage naming inconsistency and loop enter/exit mismatch reduce observability quality.
- - Legacy path divergence remains significant.
- - `Brain` is still too large and branch-heavy.

## Top 20 Improvement List

1. Add real runtime instrumentation for `QUESTION`.
2. Add real runtime instrumentation for `QUESTION_CONTEXT`.
3. Add real runtime instrumentation for `DELIVERY`.
4. Unify `ANSWER_COMPOSER` vs `COMPOSER` stage naming.
5. Fix `RETRIEVAL_LOOP` enter/exit imbalance.
6. Add explicit runtime counters for cache miss and TTL expiry instead of inferring them externally.
7. Add explicit container shutdown invocation in app lifecycle.
8. Add explicit container startup / singleton warmup strategy if desired.
9. Decide whether `knowledge_layer` should remain non-singleton.
10. Decide whether `memory_layer` should remain non-singleton.
11. Decide whether `retrieval_loop_controller` should remain per-call or be pooled.
12. Reduce `Brain` responsibilities further and keep only adapter concerns.
13. Deduplicate `think()` and `think_stream()` shared orchestration logic.
14. Add runtime metric for actual pipeline fallback execution, not just configured fallback candidate.
15. Add runtime metric for specialized pipeline hit rate by question family.
16. Add runtime metric for container resolution latency per service.
17. Add runtime metric for singleton cache hit ratio.
18. Add runtime metric for Knowledge conflict resolution outcomes.
19. Add runtime metric for Governor confidence distribution.
20. Add regression audit to compare legacy path output and orchestrated path output continuously.

