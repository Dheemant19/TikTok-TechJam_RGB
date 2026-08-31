# Plan_Workflow.md — Complete FlowState Implementation

## Context
Implement Architecture v3 as a local, reproducible research system: validate the KuaiRand contract, reproduce the official FM validation baseline, let two Bedrock-backed LangChain agents plan and code one bounded experiment at a time, run deterministic safety/training/evaluation stages, recover within fixed limits, stop by the organizer rule, and package the validation-best artifact. Integrate the Research Knowledge MCP from `Plan_MCP.md` and the observer-plus-safe-controls app from `Plan_UI.md` through one append-only event/ledger contract. The Data Profiler is expanded into **Data Profiler & Preprocessor**: it owns train-only preprocessing artifacts and the aggregate visualization outputs shown to users.

The repository currently has architecture documents, the official starter kit, and local KuaiRand CSVs, but no `src/`, `configs/`, `scripts/`, `tests/`, `pyproject.toml`, or frontend scaffold. Build a clean-cut implementation; do not alter `kuairand-starter-kit/evaluate.py`, its split definitions, or prior ledger history.

## Approach

### 1. Create one local-first project and lock the runtime
1. Add Python 3.12 project metadata at `pyproject.toml`, managed by `uv`, with a committed `uv.lock`. Use:
   - Pydantic v2 + PyYAML for locked contracts/configuration;
   - Typer for cross-platform CLI commands;
   - Polars lazy CSV scans + PyArrow Parquet for efficient profiling/materialized data;
   - NumPy for organizer-baseline compatibility;
   - PyTorch for experiment models and training;
   - LangGraph for the durable state machine, LangChain Core, and `langchain-aws` for `ChatBedrockConverse`;
   - FastAPI + Uvicorn for the loopback observer API and SSE;
   - standard-library SQLite in WAL mode for ledger/events;
   - psutil and optional NVIDIA NVML bindings for process/resource telemetry;
   - pytest for behavioral, contract, recovery, and replay checks.
2. Do not add LangSmith, a hosted database, Redis, Celery, Kubernetes, a cloud vector database, or paid monitoring. All durable state lives under local ignored directories; AWS Bedrock is the only planned metered service.
3. Create the package tree:
   ```text
   src/flowstate/
     cli/ contract/ integrity/ data/ features/ models/ training/
     evaluation/ agents/ orchestration/ recovery/ ledger/ reporting/
     api/ knowledge/ mcp/
   configs/challenge/ configs/baseline/ configs/experiments/
   configs/budgets/ configs/agents/
   data/manifests/ data/research/
   runs/ artifacts/ state/ tests/
   ui/
   ```
   Generated `runs/`, `artifacts/`, `state/`, worktrees, raw data, credentials, model caches, and large predictions are ignored; lightweight example configs and redacted test fixtures are versioned.
4. Expose one CLI at `python -m flowstate.cli` with commands:
   - `validate`
   - `profile`
   - `reproduce-baseline`
   - `run`
   - `pause`, `resume`, `cancel`
   - `replay`
   - `report`
   - `package-submission`
   - `serve-ui`
   - the `knowledge` subcommands from Plan_MCP.md.
5. Every command accepts relative config paths, supports Windows, returns nonzero on failure, emits a machine-readable final receipt, and refuses to overwrite immutable records.

### 2. Lock organizer rules into a typed challenge contract
1. Create `configs/challenge/kuairand_pure.yaml` containing paths—not copied numeric facts—to:
   - `kuairand-starter-kit/data.py`
   - `kuairand-starter-kit/evaluate.py`
   - `kuairand-starter-kit/submit.py`
   - `kuairand-starter-kit/baseline.py`
   - `kuairand-starter-kit/baseline_scores.json`
   - the dataset directory from `${KUAIRAND_DATA_DIR}`.
2. Implement `ChallengeContract` in `src/flowstate/contract/challenge.py`. On load, derive benchmark, `long_view`, date ranges, GAUC/nDCG@5/primary rule, FM baseline config, epsilon, patience, and submission schema from the official starter files/config. Record SHA-256 hashes and reject a run if those files change after session start.
3. Treat `kuairand-starter-kit/baseline_scores.json` as the current machine-readable baseline/convergence source. The Architecture v3 prose contains a different validation number; never hard-code either value. Display and compare the value loaded at runtime.
4. Add `configs/budgets/competition.yaml` with required owner-supplied limits: total wall seconds, GPU-hours, Bedrock input/output tokens, maximum experiments, per-run timeout, recovery attempts, MCP provider calls/documents/response characters, and proxy tier limits. Schema validation fails closed when a required competition limit is absent; the system does not invent one.
5. Add `configs/agents/bedrock.yaml` with environment-variable references for AWS region and Research/Coder model IDs, structured-output limits, temperature `0`, per-call timeout, and retry limit. Secrets use the normal AWS credential chain and never appear in YAML.
6. Define split-taint values `TRAIN_FEATURES`, `TRAIN_LABELS`, `VALIDATION_FEATURES`, `VALIDATION_LABELS`, `VALIDATION_FEEDBACK`, `TEST_FEATURES_ONLY`, and `TEST_LABELS_LOCKED`. Every dataset/artifact model carries taint, parent IDs, row count, schema fingerprint, source/code hashes, and creation receipt.
7. Project columns at read time. Development services can read train labels and validation labels only through the evaluator capability; test feature readers exclude `long_view` and every feedback label. Never call `submit.py --score --split test`.

### 3. Build the append-only ledger and event stream first
1. Create `state/flowstate.sqlite3` with transactional schema migrations and WAL mode. Use tables for sessions, run snapshots, append-only run events, experiment contracts, artifacts/lineage, metric receipts, resource samples/totals, claims, frontier entries, recovery attempts, manual interventions, and control requests.
2. Use immutable IDs generated as UTC timestamp plus random suffix. Every state change appends a `RunEvent` with:
   `event_id`, `session_id`, `run_id`, monotonic `sequence`, `component_id`, `execution_id`, `stage`, `event_type`, `status`, `occurred_at`, `plain_summary`, `payload_json`, `artifact_ids`, and `previous_event_hash`; compute `event_hash` over canonical JSON to form a tamper-evident chain.
3. Enforce uniqueness on `(session_id, sequence)` and artifact content hashes. Corrections append a new event referencing the incorrect event. No update/delete method exists for historical event payloads; mutable session/frontier snapshots are projections rebuilt from events.
4. Map `component_id` and status values exactly to Plan_UI.md. Redact event payloads before API exposure; the internal ledger may store safe artifact references, but not AWS secrets, raw data rows, or sealed test labels.
5. Implement an in-process event bus that writes SQLite before notifying SSE subscribers. UI reconnects from sequence; replay reads the same events and recomputes snapshots through the same reducer.

### 4. Implement the Data Profiler & Preprocessor as deterministic code
1. Create `ProfilerService.profile(DataArtifact, ProfileConfig) -> ProfileReceipt` and `PreprocessorService.fit_apply(train, validation, optional_test_features, TransformSpec) -> TransformReceipt`. Keep them in the same architecture component/event ID `data_profiler`, but separate pure functions for testing and reuse.
2. Read the actual KuaiRand columns already present in the repository: IDs/time, `long_view`, auxiliary feedback, `play_time_ms`, `duration_ms`, `tab`, plus video/user feature tables. Use Polars lazy scans and aggregations; never load raw rows into a Bedrock prompt or frontend response.
3. Produce versioned immutable artifacts:
   - `profile.json` — row/user counts, `long_view` rates, mixed/all-positive/all-negative users, per-user sequence summaries, missing/malformed/duplicate/constant fields, cardinalities, sparsity, unseen IDs, watch-time censoring, temporal drift, auxiliary-label correlations, throughput/memory summaries, and warnings.
   - `visualization.json` — pre-aggregated bins/series/table values for every chart required by Plan_UI.md; no raw rows.
   - `transform_spec.json` — approved transform operations and protected columns.
   - `transform_state.json` — train-fitted vocabularies/UNK IDs, duration bucket edges, imputation/scaling values, feature order, source hashes, code hash, and seed.
   - immutable Parquet/NumPy materializations plus `transform_receipt.json` with row counts, schema/hash lineage, join expansion ratio, missing/finite checks, and split taints.
4. Reproduce the official baseline encoder exactly for the baseline branch: five fields from starter `data.py`, train-fitted vocabularies, train duration quantiles, one UNK slot per field, and deterministic row order. Preserve the baseline transform immutably.
5. A new cleaning or feature transform is an experiment. The Research Agent names it in the contract, the Code Agent patches a transform implementation/config in the isolated worktree, and the profiler executes it. It cannot remove `row_id`, user/video IDs, dates/split keys, `long_view`, or submission identifiers.
6. Apply all fit operations to train only. Validation/test use the saved transform state without refit. Distribution drift creates diagnostics unless a declared safety bound is exceeded; leakage, row alignment, invalid joins, missing protected columns, NaN/Inf, or taint escalation fails closed.
7. Cache profile and transform artifacts by source hashes + transform code/config hash. Rerun only when an upstream artifact changes. Publish profiler inputs, outputs, charts, transform lineage, warnings, and failures to the ledger/UI.

### 5. Add integrity gates and meaningful sanity checks
1. Implement a phase-boundary validator used before and after load, transform, training, prediction, evaluation, and final packaging. It checks schema/types, required IDs, key coverage, permitted row-count change, join expansion, date exclusivity, taint, finite values, artifact hashes, and continuous zero-based `row_id` where required.
2. Hash the official evaluator at session start and before every evaluation. Reject any experiment patch touching starter evaluator, split, baseline score/config, prior runs, or finalizer policy.
3. Rename the diagram’s `Sanity Invariant Checks` in code/UI to `Pipeline Sanity Checks`. Implement the label-shuffle negative control after baseline setup and after any data/evaluator-wrapper change—not on every model experiment:
   - deterministically shuffle only training `long_view` with a recorded seed;
   - train the same baseline pipeline;
   - evaluate against untouched validation labels with the official evaluator;
   - require primary score no higher than `random.valid.primary + sanity_shuffle_tolerance`, where `sanity_shuffle_tolerance` is explicitly set to `0.02` in the challenge config;
   - preserve the receipt and halt novel experiments if this negative control remains suspicious after one deterministic rerun.
4. Add evaluator metamorphic checks: row order changes that preserve user/label/score triples do not change metrics; adding a constant to all scores does not change metrics; improving a positive item’s rank cannot reduce that user’s nDCG@5; all-negative users contribute nDCG 0; all-positive/single-class users do not contribute to GAUC denominator.

### 6. Reproduce the official FM baseline without using test feedback
1. Implement a baseline adapter that imports/reuses the organizer’s `FM`, `data.load`, `data.encode`, and official `evaluate` behavior but executes the development gate on train → validation only. Record exact starter hashes, FM configuration, seed, command, environment, transformed-data receipt, stdout/stderr, metrics, duration, and artifact location.
2. Run the organizer random and item-popularity validation references as harness checks, then FM with the configured seed policy. Compare observed validation metrics with `baseline_scores.json` using its published standard deviation and configured tolerance. Do not start novel experiments until the baseline passes.
3. The starter `baseline.py` evaluates both validation and local test; do not call that all-split path during development. The wrapper must not modify `baseline.py` or `evaluate.py`; it narrows access to the permitted validation path and documents the exact imported symbols/hashes.
4. Register the reproduced baseline as `B0`, `validation_best`, and `stable_fallback`. A failed reproduction triggers bounded diagnosis of environment, schema/order, preprocessing, split, label, seed, and evaluator; unresolved mismatch creates an integrity halt rather than a custom replacement baseline.

### 7. Implement the Research Knowledge MCP before agent planning
1. Execute `Plan_MCP.md` against the shared Python package and ledger. Ingest the validated 25-paper JSON, build local hybrid search, and expose the seven read-only tools over stdio.
2. Mirror MCP request receipts into the main ledger so Plan_UI.md can show cache/local/live source, evidence IDs, licenses, hashes, cap usage, and failures.
3. MCP remains optional to deterministic execution. Local curated evidence is the fallback; provider outages cannot corrupt or erase a run.

### 8. Implement the two Bedrock/LangChain agent roles with strict structured output
1. Build the durable outer workflow with LangGraph, but keep deterministic services as ordinary Python nodes. Use LangChain only for:
   - `ResearchAgent`: select one bounded hypothesis from the profile, comparable run history, frontier, budgets, and optional MCP evidence.
   - `CodeRecoveryAgent`: produce a minimal code patch/targeted tests or diagnose one complex failure from a traceback.
2. Configure `ChatBedrockConverse` from `AWS_REGION`, `BEDROCK_RESEARCH_MODEL_ID`, and `BEDROCK_CODE_MODEL_ID`. Use temperature `0`, Pydantic structured output, explicit maximum output tokens, per-call timeout, and at most two transient retries. Capture Bedrock usage metadata as actual input/output token receipts; never estimate missing provider telemetry as fact.
3. Compile bounded context: challenge invariants, current diagnostic digest, current best/stable fallback, top comparable positive/negative/failed runs, remaining budget, and at most configured MCP evidence records. Never pass whole CSVs, the entire ledger, arbitrary raw web text, secrets, or test labels.
4. Validate `ExperimentContract` before any code action. Required fields are immutable ID, parent run, one causal hypothesis, observed evidence IDs, one primary change, exact allowed/prohibited files, predicted GAUC/nDCG@5 directions, falsifiers, success/ambiguous/regression branches, comparator, epsilon, guardrails, budget, fallback, and recovery cap.
5. Store the plan event and immutable contract artifact before invoking the Coder. Reject contracts that attempt a blind sweep, change multiple unrelated factors, use an organizer-tested dead end without new measured evidence, touch protected files, exceed budget, or proceed before B0.

### 9. Apply agent code safely in isolated Git worktrees
1. Create `state/worktrees/{experiment_id}` from the chosen parent commit with the system Git executable. The workspace manager records parent commit and clean content hashes; one experiment owns one worktree.
2. Give the Code Agent read-only tools restricted to contract `allowed_files` and MCP pinned-code metadata. Its output is `PatchProposal {unified_diff, dependency_changes, tests, explanation}`; no arbitrary shell or direct ledger access.
3. Validate diff paths against traversal, symlinks, binary patches, size limits, protected files, and allowed scope. Run `git apply --check`, apply once, capture `diff.patch`, and hash it. A malformed patch gets one Coder repair using the apply error; after that the experiment fails and history is preserved.
4. Dependency changes require package, exact version, license evidence, and necessity in the contract. The workspace uses the locked base environment plus an experiment-specific lock delta; it cannot silently install at execution time.
5. Commit the isolated patch only after static/preflight gates pass. Stable branch pointers advance only after an accepted comparable result; rejected/failed worktree commits remain addressable in the ledger and are removed only from the active frontier, not history.

### 10. Implement the four-tier execution funnel
1. Tier 1 — zero-GPU checks: parse/import touched modules, validate configs/schemas/taint, verify protected-file hashes, check dependency policy, run targeted tests, and diff the official evaluator hash.
2. Tier 2 — deterministic tiny smoke: execute 100 batches or the smallest complete user groups required by the loss, verify shapes, forward/backward, finite loss/gradients/predictions, checkpoint write/read, and one official validation-evaluator call on a deterministic fixture.
3. Tier 3 — filter-only proxy: train both the experiment and its parent baseline on the same immutable stratified manifest. Reject crashes, OOM after recovery cap, NaN/divergence, failure to learn beyond proxy baseline, severe pre-registered regression, or projected budget overflow. Mark all proxy metrics `proxy/non_comparable`; never update convergence or validation-best from them.
4. Tier 4 — full train and official validation: run the exact immutable config on the full 1.14M-row training split, emit atomic checkpoint and validation predictions, validate predictions, and invoke the untouched official `evaluate.py` for GAUC/nDCG@5/primary.
5. Launch trainers through `asyncio.create_subprocess_exec` with explicit argv/cwd/env, captured stdout/stderr, timeout, and process-tree termination. Write checkpoints to a temporary sibling path, fsync, hash, then atomically rename.
6. Set Python/NumPy/PyTorch/CUDA seeds and deterministic flags; record effective batch size, accumulation, precision, device, epochs, early stopping, dataloader settings, dependency/CUDA versions, and model parameter count.
7. Resource monitor samples wall time, process status, RSS, and GPU memory/utilization where NVML exists. Compute GPU-hours from measured device-active process time; record `peak_gpu_memory_mb=null` when unavailable instead of inventing a value.

### 11. Wrap the official evaluator and decide outcomes deterministically
1. Write validation predictions with deterministic `row_id`, user/video IDs, and finite score. Validate length/order/IDs before scoring.
2. Invoke the organizer evaluator implementation unchanged, preserve raw output, parse into a signed `MetricReceipt` containing run/artifact/evaluator/config hashes, GAUC, nDCG@5, primary, users, rows, timestamp, and receipt hash.
3. Reject a result with no valid official receipt. Compare every comparable result with both parent and reproduced B0 using absolute primary deltas. Preserve each metric separately so a GAUC/nDCG tradeoff is visible.
4. Execute the pre-registered outcome branch without an LLM rewriting it after metrics are known. The Research Agent may propose the next contract from the receipt and diagnostics, but cannot change the recorded decision for the completed run.
5. Maintain frontier roles: `validation_best`, `stable_fallback`, accepted parent, pending candidate, rejected, and failed. Within seed noise, follow the contract’s confirmation policy before replacing validation-best.
6. Increment the no-improvement counter only for full comparable validation results. Stop after the organizer-configured epsilon is not exceeded for the configured consecutive count, or when any wall/GPU/token/experiment budget is exhausted. Select validation-best, never latest or proxy-best.

### 12. Implement bounded recovery and transactional rollback
1. Classify syntax/import/config, schema/data, OOM, timeout, NaN/divergence, evaluator/parser, transient provider/Bedrock, and infrastructure failures. Every recovery appends original error, diagnosis, action, attempt, and result.
2. Use fixed recipes:
   - syntax/import/config: one minimal repair, rerun Tier 1;
   - schema mismatch: expected/actual diff, validated adapter/config correction only when semantics are unambiguous;
   - OOM: halve micro-batch → enable supported AMP → preserve effective batch with accumulation → enable checkpointing, each once and recorded;
   - timeout: retain scope, reduce evaluation cadence/proxy breadth within contract, never silently shrink a full comparable run;
   - NaN/divergence: restore stable settings, check labels/LR/precision/normalization, allow one contract-approved repair;
   - transient external/Bedrock: bounded retry then local evidence/pause planning;
   - metric regression: no technical retry; reject and preserve as evidence.
3. After recovery cap, mark the run failed, reset active parent to `stable_fallback`, retain worktree commit/diff/logs/artifacts, remove only the failed node from active frontier, and continue with another valid hypothesis when budget allows.
4. Manual edits, decisions, command corrections, restarts, or recovery choices increment `manual_intervention_count`; UI start/pause/resume/cancel actions are recorded control events, with intervention classification set by explicit policy rather than hidden.

### 13. Add loopback API, observer UI, and replay
1. Implement the FastAPI/SSE contract in Plan_UI.md from ledger snapshots/events. API binds `127.0.0.1` by default and uses the same orchestration service methods as CLI controls; there is no second workflow engine in the web server.
2. Control transitions use optimistic concurrency with current event sequence. Allowed actions come from kernel state; invalid/stale requests return `409` and append no execution event.
3. Serve redacted artifact views, never raw datasets/checkpoints/secrets/protected labels. Expose profile visualization aggregates, experiment contracts, diffs, safe logs, metric receipts, evidence cards, resources, recoveries, lineage, and finalization receipts.
4. Execute `Plan_UI.md` after API schemas are stable. Generate and commit TypeScript clients from FastAPI OpenAPI; do not hand-maintain duplicate frontend models.
5. Replay reduces historical events through the same snapshot reducer. It can simulate timing for demonstration but labels itself replay and never creates scientific metrics or control events.

### 14. Finalize once and package the validation-best artifact
1. On convergence or budget stop, lock the frontier and require explicit package confirmation from CLI or UI. Create a one-way finalization event referencing validation-best checkpoint, code commit/diff, config, transform state, validation metric receipt, environment, and artifact hashes.
2. Recreate a clean worktree/environment from the winning revision and locked dependencies, verify all hashes, and replay its train/validation path within configured reproducibility tolerance before using test features.
3. Load the official test rows in deterministic order through the `TEST_FEATURES_ONLY` projection, apply the frozen train-fitted transform without refit, run exactly one prediction pass, and write `predictions.csv` with `row_id,user_id,video_id,score`.
4. Validate identifiers, row continuity, finite scores, and schema. Run `python kuairand-starter-kit/submit.py --check --split test predictions.csv` only in the sealed finalization subprocess; capture only exit status/stdout and never run `--score test`. The current official checker internally loads the source split, so keep this invocation inside the irreversible finalization capability and expose no test labels or rows to agents/UI.
5. Produce a cryptographic manifest linking dataset/evaluator/code/config/environment/transform/checkpoint/prediction hashes, validation-best receipt, clean replay, schema-check output, resources, manual interventions, and complete event-chain head. Hidden evaluation is terminal and cannot route back to research.

## Critical files & anchors
- `docs/architecture/ARCHITECTURE_v3_kuairand.md` — current four layers, 11-step flow, v3 metrics, convergence, and finalization responsibilities.
- `AGENTS.md` — authoritative competition integrity, baseline, logging, recovery, and submission requirements already loaded as repository policy.
- `kuairand-starter-kit/data.py` — official dates, five baseline fields, train-fitted encoding, and UNK behavior.
- `kuairand-starter-kit/evaluate.py` — sole GAUC/nDCG@5/primary implementation; never edit.
- `kuairand-starter-kit/baseline_scores.json` — runtime source for baseline, random reference, seed noise, and convergence values; it overrides conflicting prose values.

## Verification
1. Environment: from repository root run `uv sync --locked`, `uv run python -m flowstate.cli validate --challenge configs/challenge/kuairand_pure.yaml`, and expect hashes, schema/date/label checks, required-owner-setting checks, and no test-label access.
2. Profiler/preprocessor: run `uv run python -m flowstate.cli profile ...` on a deterministic small fixture and then local data. Expect all three profile/visualization/transform receipts, train-only fitted state, unchanged row order, valid lineage, and no raw rows in LLM/UI artifacts. Mutate a validation-only category and verify it maps to UNK without changing vocabulary.
3. Integrity: attempt train/validation overlap, protected-column removal, evaluator modification, NaN transform output, join expansion, noncontinuous row IDs, and test-label access. Expect fail-closed events before GPU work.
4. Baseline gate: run `uv run python -m flowstate.cli reproduce-baseline ...`. Expect organizer FM validation metrics within configured tolerance, B0/stable-fallback registration, exact command/environment/artifact receipts, and zero novel contracts before success.
5. Sanity control: run the deterministic shuffled-training-label check. Expect validation primary at or below configured random-valid bound; force a leaked feature fixture and expect the check to halt experimentation.
6. MCP/agents: with the curated JSON ingested, run one Research Agent call and one Code Agent patch in a disposable worktree. Expect bounded context, valid cited evidence IDs, contract written before patch, protected-file enforcement, exact Bedrock token receipts, and no arbitrary agent shell access.
7. Full smoke workflow: `uv run python -m flowstate.cli run --challenge ... --budget configs/budgets/smoke.yaml`. Expect ordered events through profile → research → patch → Tiers 1/2 → training → official validation → decision, a replayable final snapshot, and artifacts resolving by hash.
8. Recovery: inject syntax failure, schema mismatch, simulated OOM, timeout, NaN loss, transient MCP outage, and metric regression in separate fixture runs. Expect the fixed bounded recipe, preserved original failure, stable fallback, accurate retry/intervention/resource fields, and no deleted history.
9. Convergence: feed three deterministic comparable receipts that fail to exceed loaded epsilon. Expect stop exactly at configured patience and selection of validation-best rather than latest. Proxy receipts must not change the counter.
10. UI: run `uv run python -m flowstate.cli serve-ui` and browser-drive the actual surface using Plan_UI.md checks: live SSE, safe controls, every node’s input/output, profiler charts, replay, recovery, metrics, resources, and responsive/accessibility modes.
11. Finalization rehearsal uses a synthetic/test fixture only. Expect clean replay, one prediction pass, official schema check, manifest links, and rejection of a second package attempt. Do not perform the real test finalization during development verification.
12. Run focused contract/integration/recovery/reproducibility tests after the behavioral checks; they must defend event append-only behavior, official evaluator hashes/semantics, split taint, preprocessing fit boundary, baseline gate, proxy non-comparability, recovery limits, convergence, API redaction, and one-way finalization.

## Required from the project owner
- Set `KUAIRAND_DATA_DIR` to the local KuaiRand-Pure data directory. Raw data remains outside Git and is never uploaded by this system.
- Supply `configs/budgets/competition.yaml` values for total GPU-hours, wall time, Bedrock input/output tokens, experiment count, per-run timeout, and recovery limits from the organizer or team allocation. The system will not invent unresolved limits.
- Configure AWS credentials through `AWS_PROFILE` or the normal AWS environment/credential files; provide `AWS_REGION`, `BEDROCK_RESEARCH_MODEL_ID`, and `BEDROCK_CODE_MODEL_ID`. Enable model access in that Bedrock region. Bedrock usage is not free; every call is metered and capped by the supplied budget.
- Supply the curated paper JSON, `GITHUB_TOKEN`, and `OPENALEX_MAILTO` listed in Plan_MCP.md. No API key is required for the UI, SQLite, FastAPI, LangGraph/LangChain libraries, Polars, PyTorch, or local vector/keyword search.
- Ensure Python 3.12, `uv`, Node.js 22 LTS, pnpm, Git, and any intended NVIDIA driver/CUDA runtime are installed. CPU smoke/baseline paths remain available when no GPU exists.
- Provide deliberate confirmation only when generating the real final package. Do not provide or expose hidden-test labels to agents or the UI.

## Assumptions & contingencies
- Deployment is local and single-operator. If the API must later bind beyond loopback, add authentication/TLS before exposure; never tunnel this unauthenticated build.
- AWS Bedrock and LangChain are mandatory for the two reasoning roles. If Bedrock is unavailable, deterministic active runs finish, new planning pauses, and the ledger records the outage; no fake local LLM fallback is introduced.
- The UI has safe controls but cannot edit workflow topology or organizer rules. CLI and kernel state always win control conflicts.
- If no NVIDIA GPU is available, run the official NumPy FM baseline and smoke experiments on CPU; reject GPU-dependent full experiments through the budget/capability gate instead of pretending they ran.
- The official `submit.py --check` reads the source split through `data.load`; isolate it to the one-way finalization subprocess and never use its test scoring path. If organizers provide a feature-only checker later, replace the command/path in the challenge config and hash the newer official tool.

