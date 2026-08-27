# TikTok TechJam 2026 — Track #2 Agent Guide

## Mission

Build an **Autonomous ML Research Agent for recommender systems**. Given a benchmark, its fixed data splits, metrics, official baseline, evaluation script, and output schema, the agent must autonomously run an ML research loop:

1. Read and operationalize the problem specification.
2. Inspect data and validate the pipeline.
3. Reproduce the organizer-provided official baseline.
4. Form an evidence-based improvement hypothesis.
5. Change the pipeline in code.
6. Train and evaluate using only permitted data.
7. Interpret the result, retain or reject the change, and select the next experiment.
8. Recover from expected failures without a human fixing the run.
9. Stop at the supplied convergence condition or resource limit.
10. Designate the validation-best artifact as the final submission.

The goal is not to build a static recommender or a hyperparameter-search wrapper. The goal is to demonstrate an auditable, robust, low-intervention agent that improves a recommender-system pipeline.

---

## Non-Negotiable Constraints

### Data and evaluation integrity

- **MUST** use only the challenge datasets for training: KuaiRand and, if attempted, AliCCP.
- **MUST NOT** use external training data, join external datasets, or pretrain on other data.
- **MUST NOT** access, inspect, infer from, tune on, or otherwise use hidden-test labels during development.
- **MUST** develop only with the training split and permitted validation feedback.
- **MUST NOT** use a pretrained model whose weights were trained on these benchmarks’ hidden test labels.
- **MUST** preserve the organizer-defined train/validation/test split and output schema.
- **MUST** treat the organizer’s evaluation script as the source of truth.
- **MUST NOT** replace the official baseline with a self-created starter baseline when reporting improvement.

External open-source libraries, papers, public solutions, and otherwise permissible pretrained weights are allowed.

### Baseline and final-result rules

- **MUST** reproduce the organizer’s official baseline before claiming an improvement.
- **MUST** record the baseline version, command, data split, seed, environment, metrics, and artifact location.
- **MUST** compare every final result to the official baseline, not only to intermediate experiments.
- **MUST** retain the validation-best checkpoint or prediction artifact for final submission.
- **MUST NOT** select an intermediate-test or hidden-test best model.
- The final hidden-test evaluation happens once. Treat final-artifact selection as irreversible.

### Autonomy and robustness

- **MUST** make experiment decisions from observed evidence: metrics, data diagnostics, training behavior, runtime, and prior hypotheses.
- **MUST** modify real pipeline code as part of experiments; merely narrating possible changes is not an experiment.
- **MUST** log every experiment and recovery event in a machine-readable, reviewable form.
- **MUST** recover from code failures, timeouts, malformed data, OOM conditions, and divergent training where a safe fallback exists.
- **MUST NOT** silently discard failed experiments. Record the failure, diagnosis, recovery action, and outcome.
- **SHOULD** complete a run with zero manual interventions; if intervention occurs, count and explain it.
- **MUST NOT** fabricate metrics, successful runs, diffs, token totals, GPU-hours, or recovery events.

---

## Challenge Scope

### Required benchmark: KuaiRand-Pure

KuaiRand-Pure is a short-video feed dataset with multiple user feedback signals, user/video features, and randomized exposure data.

Required task and evaluation contract:

- **Task**: **Within-user ranking (`用户内排序`)** — Each user's candidate videos in the evaluation set are ranked; no full-corpus retrieval.
- **Positive relevance label**: **`long_view`** (raw binary column, 0/1).
- **Official evaluation metrics**:
  - **`GAUC`**: Group AUC computed per user, weighted by positive count; only evaluates users with $0 < \text{positives} < \text{exposures}$ (63.7% of test users).
  - **`nDCG@5`**: Discounted cumulative gain ($2^{\text{rel}} - 1$); users with zero positive items receive 0.0 and are included in the average (27.1% of test users are all-negative, 9.2% are all-positive).
- **Primary metric score**: Equal-weighted mean of GAUC and nDCG@5:
  $$\text{score\_primary} = \frac{\text{GAUC} + \text{nDCG@5}}{2}$$
  $$\Delta(\text{primary}) = \text{score\_agent}(\text{primary}) - \text{score\_official\_baseline}(\text{primary})$$
- KuaiRand-Pure determines **100% of the primary metric score**.
- Ranking candidates, relevance labels, and evaluation grouping must follow the organizer-provided `evaluate.py` script exactly.
- The official baseline is the organizer-provided Factorization Machine (`FM`); do not substitute a self-created starter model.

Official dataset splits:

- **Train**: `20220408`–`20220421` (from `log_standard_4_08_to_4_21_pure.csv`, ~1.14M rows).
- **Validation**: `20220422`–`20220428` (from `log_standard_4_22_to_5_08_pure.csv`, 7 days).
- **Test**: `20220429`–`20220508` (from `log_standard_4_22_to_5_08_pure.csv`, 10 days).
- **Unbiased evaluation log (advanced)**: `log_random_4_22_to_5_08_pure.csv` (1.18M rows of randomized exposure data).

Official baseline ladder & headroom reference (Test set):

| Model / Benchmark | GAUC | nDCG@5 | Primary Score | Notes |
|---|---|---|---|---|
| Random (Lower Bound) | 0.4996 | 0.4511 | 0.4753 | Evaluation harness sanity check |
| Item Popularity (Trivial) | 0.6308 | 0.5121 | 0.5715 | Popularity prior |
| **FM (Official Baseline to Beat)** | **0.6610** | **0.5282** | **0.5946** | Target baseline ($\sigma = 0.0008$) |
| **Oracle Ceiling** | **1.0000** | **0.7289** | **0.8645** | Maximum achievable score (due to 27.1% all-negative users) |

*Note: The FM baseline has already captured 30.7% of the total available headroom between Random and Oracle. True remaining headroom is 0.270.*

Submission format contract:

- File format: CSV with header `row_id,user_id,video_id,score`.
- `row_id`: 0-indexed integer corresponding to deterministic evaluation row order.
- `row_id` is mandatory because `(user_id, video_id)` is **not unique** (3.06% duplicate pairs in test set, repeated up to 12 times).
- Validation and formatting verification: `python3 submit.py --check --split test submission.csv`.

Official starter kit reference files:

- [`kuairand-starter-kit/README.md`](file:///Users/arushiverma/Desktop/TikTok-TechJam_RGB/kuairand-starter-kit/README.md): Official problem specification, rules, and starter kit instructions.
- [`kuairand-starter-kit/evaluate.py`](file:///Users/arushiverma/Desktop/TikTok-TechJam_RGB/kuairand-starter-kit/evaluate.py): Official evaluation script (`GAUC` and `nDCG@5`). Source of truth.
- [`kuairand-starter-kit/baseline.py`](file:///Users/arushiverma/Desktop/TikTok-TechJam_RGB/kuairand-starter-kit/baseline.py): Official Factorization Machine (`FM`), item popularity, and random baselines.
- [`kuairand-starter-kit/data.py`](file:///Users/arushiverma/Desktop/TikTok-TechJam_RGB/kuairand-starter-kit/data.py): Deterministic data loader and split partitioning logic.
- [`kuairand-starter-kit/baseline_scores.json`](file:///Users/arushiverma/Desktop/TikTok-TechJam_RGB/kuairand-starter-kit/baseline_scores.json): Baseline scores, seed standard deviations ($\sigma = 0.0008$), and convergence thresholds ($\varepsilon = 0.002, N = 3$).
- [`kuairand-starter-kit/submit.py`](file:///Users/arushiverma/Desktop/TikTok-TechJam_RGB/kuairand-starter-kit/submit.py): Submission generator and `--check` / `--score` validator.
- [`kuairand-starter-kit/ablation_features.py`](file:///Users/arushiverma/Desktop/TikTok-TechJam_RGB/kuairand-starter-kit/ablation_features.py): Feature ablation script verifying the lack of gain from adding static features.

### Bonus benchmark: AliCCP

AliCCP is an Alibaba/Taobao e-commerce benchmark for the funnel:

```text
impression → click → conversion
```

Bonus metrics:

- **CTR AUC** over all impressions, where click is positive.
- **CVR AUC** over the clicked subset, where conversion is positive.

AliCCP is optional. A strong result may be reported as bonus work, but skipping it must not reduce the KuaiRand primary score. Do not spend KuaiRand-critical time or resources on AliCCP until KuaiRand has a reliable end-to-end result. If attempted, use the organizer-specified NISE reference implementation and preserve the official funnel labels, splits, evaluator, and output schema.

---

## Scoring Model

Judging weights:

| Criterion | Weight | What to demonstrate |
|---|---:|---|
| Technical Execution | 35% | Metric improvement, correct engineering, robust recovery |
| Innovation & Problem Insight | 20% | Strong hypotheses across the entire ML stack |
| Impact & Relevance | 20% | Autonomous iteration with minimal human intervention |
| Feasibility & Practicality | 15% | Proportionate LLM token and GPU-hour usage |
| Presentation & Communication | 10% | Clear final-event narrative and technical command |

### Primary metric calculation

For each dataset metric $m$:

```text
delta(m) = score_agent(m) − score_official_baseline(m)
score_dataset = mean(delta(m) for all dataset metrics)
```

For KuaiRand-Pure, this is the equal-weighted mean of GAUC delta and nDCG@5 delta vs FM baseline (0.5946). Absolute improvement is used: do not substitute relative percentage improvement.

### Convergence

The scored result is the **converged** result, not the highest temporary metric. A run converges when validation score fails to improve by more than organizer-defined $\varepsilon = 0.002$ for organizer-defined $N = 3$ consecutive iterations, or the fixed compute/wall-clock budget is reached. Use the validation-best artifact at that point.

The following are organizer-controlled configuration, loaded from `kuairand-starter-kit/baseline_scores.json`:

- Baseline scores: FM (Valid: GAUC 0.6621, nDCG@5 0.5289, Primary 0.5955; Test: GAUC 0.6610, nDCG@5 0.5282, Primary 0.5946).
- Exact scoring script: `kuairand-starter-kit/evaluate.py`.
- Submission schema: `row_id,user_id,video_id,score`.
- Convergence parameters: $\varepsilon = 0.002$ ($\approx 2.5\sigma$), $N = 3$.
- Compute and wall-clock limits.

---

## Required Research Loop

### Phase 0 — Establish a reproducible environment

Before experimentation:

- Pin runtime, library, CUDA, and model versions.
- Save dataset paths, split definitions, hardware details, and all random seeds.
- Validate raw schema, feature cardinalities, missing-value behavior, label definitions, and leakage boundaries.
- Make the training command, evaluation command, and artifact locations deterministic.
- Implement a small smoke run before an expensive full run.
- Track LLM token usage and GPU-hours from the first agent action.

### Phase 1 — Reproduce the official baseline

The baseline is a gate, not an optional reference.

- Obtain the exact organizer-referenced pipeline and evaluator.
- Run it end to end on the specified split.
- Compare observed validation metrics with the organizer-published baseline according to the supplied tolerance/convergence policy.
- If reproduction fails, diagnose environmental, data, schema, preprocessing, seed, and evaluator mismatches before trying novel models.
- Do not call a custom starter pipeline the official baseline.

### Phase 2 — Diagnose before changing code

For each iteration, use available evidence to determine the highest-leverage next change.

Inspect as applicable:

- Sample counts by split and `long_view` label prevalence.
- Zero-positive users (27.1% all-negative in test where nDCG is fixed at 0) and all-positive users (9.2% in test where nDCG is 1).
- Interactions per user and historical sequence lengths in train logs.
- Feature type, cardinality, sparsity, missingness, and unseen-ID behavior.
- Train/validation distribution shift.
- Model capacity, train-vs-validation gap, ranking-loss behavior, and convergence curves.
- Per-signal losses and task interference when auxiliary feedback (`is_click`, `is_like`, `is_follow`, `play_time_ms`) is used.
- GAUC and nDCG@5 confidence/stability across seeds (FM baseline $\sigma = 0.0008$).
- Runtime, GPU memory, dataloader throughput, and failure traces.
- Outcomes of prior experiments, including regressions.

### Phase 3 — Execute a bounded experiment

Each experiment must contain one primary hypothesis and an explicit success criterion.

A valid iteration:

1. Records the hypothesis and rationale.
2. Names the intended pipeline change.
3. Applies a code diff in an isolated experiment workspace or revision.
4. Runs a preflight/smoke check when the change is structurally risky.
5. Trains and evaluates with the official evaluator (`kuairand-starter-kit/evaluate.py`).
6. Records metrics, resources, artifacts, and errors.
7. Compares results with the selected parent experiment and official baseline.
8. Decides retain, reject, or investigate further.
9. Generates the next hypothesis from evidence.

Avoid changing unrelated variables in one experiment. Multi-change experiments are acceptable only when their components are inseparable and the log explains why.

### Phase 4 — Recover safely

Recovery must be deliberate and logged.

| Failure | Preferred recovery behavior |
|---|---|
| Syntax/import/config error | Parse traceback, apply minimal correction, rerun preflight, then resume. |
| Data/schema mismatch | Compare expected and actual schema, add a validated adapter or correct configuration, rerun data validation. |
| OOM | Reduce batch size, use gradient accumulation/mixed precision/checkpointing, then verify effective settings. |
| Timeout | Profile the bottleneck; reduce evaluation cadence, epochs, search breadth, or use a cheaper proxy before full validation. |
| Divergent/NaN loss | Restore last stable configuration; check learning rate, initialization, precision, normalization, labels, and loss implementation. |
| Metric regression | Preserve the result, reject it as parent unless evidence supports a follow-up ablation. |
| Transient infrastructure error | Retry with bounded backoff and preserve original command/logs. |

Never loop endlessly. Apply retry limits and escalation rules. When no safe autonomous recovery is available, halt the affected experiment, preserve its state, and move to another valid experiment rather than corrupting results.

---

## High-Value KuaiRand Research Directions

### ⚠️ Organizer-Tested Dead Ends (DO NOT REPEAT)

These directions were empirically tested by the organizers and showed **zero measurable benefit**:

| Tested Hypothesis | Result | Why It Failed |
|---|---|---|
| **Adding all 13 CWM static features** (`+music_id`, `+video_type`, `+upload_type` + 6 user coarse buckets) | Primary **0.5940** vs 5-domain **0.5950** (flat / slight degradation) | `user_id × video_id` interaction in FM already captures almost all signal. Coarse user buckets are redundant with `user_id`, and 1.14M rows cannot support noisy capacity. |
| **Scaling model capacity** ($k = 8 / 16 / 32$) | Primary **0.5895 / 0.5902 / 0.5887** (flat) | Capacity is not the bottleneck on 1.14M training interactions. |
| **Pure user-side 1st-order bias features** | 0 contribution to score | Ranking is evaluated strictly **within-user**. Any feature constant within a user does not change relative item ranking order. User features only work through **interactions with item features**. |

### 🚀 High-Headroom Research Priorities

Prioritize exploration in areas where actual headroom remains:

1. **Ranking Loss Function Alignment (Top Priority)**:
   - Current baseline uses pointwise BCE logloss, but evaluation metrics are **ranking-based (GAUC & nDCG@5)**.
   - Test Pairwise objectives (BPR, Margin Ranking) and Listwise objectives (Plackett-Luce / Softmax ranking over each user's candidate exposures).
2. **Sequential User History Modeling**:
   - KuaiRand users have hundreds of chronological interactions in the training split.
   - Apply user behavior sequence modeling (DIN, SIM, SASRec, transformer-based interest extractors).
3. **Multi-Task Learning (MTL) with Auxiliary Signals**:
   - Train multi-task architectures (MMoE, PLE, SharedBottom) leveraging auxiliary labels in logs: `is_click`, `is_like`, `is_follow`, `is_comment`, `is_forward`, and `play_time_ms` to assist the primary `long_view` objective.
4. **Watch-Time & Censored Regression Modeling**:
   - Video watch time (`play_time_ms`) is subject to right-censoring (videos finish before total interest is observed).
   - Apply censored regression and duration modeling (e.g., CWM survival loss).
5. **Feature Interaction Architectures**:
   - Explicit feature interaction models (DeepFM, DCNv2, xDeepFM, AutoInt) after ranking loss and sequence modeling.
6. **Temporal Dynamics & Distribution Drift**:
   - Model `hourmin`, `date`, and recency dynamics between train (`0408-0421`) and test (`0429-0508`).
7. **Unbiased Off-Policy Validation (Advanced)**:
   - Validate on `log_random_4_22_to_5_08_pure.csv` (1.18M random exposure rows) to detect and correct exposure bias.

### Priority order

1. Correct data loading, `evaluate.py` harness alignment, FM baseline reproduction (`0.5946`), and deterministic training.
2. High-information diagnostics (within-user label variance, sequence lengths, task correlations).
3. Loss function alignment (pairwise/listwise) and sequential history modeling.
4. Multi-task gating (PLE/MMoE) and censored watch-time modeling.
5. Deeper architectures and counterfactual debiasing only after measured gains.
6. AliCCP only after KuaiRand-Pure is submission-ready.

---

## Experiment Selection Policy

The agent should optimize improvement per unit of risk and resource consumption.

- Prefer experiments with a concrete causal rationale from diagnostics or accepted recommender-system methods.
- Favor low-cost falsification runs before full-scale training.
- Reuse successful components; do not rebuild the pipeline unnecessarily.
- Use a fixed baseline and a clear parent experiment for every comparison.
- Penalize complexity that has no measured benefit.
- Avoid broad blind grid searches, unbounded agent loops, and expensive architecture churn.
- Treat small improvements within seed noise ($\sigma = 0.0008$) as unconfirmed until validated.
- Maintain an experiment frontier: current best candidate, stable fallback, rejected branches, and pending follow-ups.
- Preserve reproducible artifacts for any candidate that could become final.

A useful iteration plan includes:

```text
Hypothesis: [specific expected mechanism]
Evidence: [metrics/diagnostic/prior result]
Change: [single bounded code/config change]
Success criterion: [expected validation movement and guardrails]
Budget: [estimated GPU-hours/tokens/iteration cap]
Fallback: [safe recovery or previous stable parent]
```

---

## Logging and Artifact Contract

Every iteration must be logged. Logs are central evidence for autonomy, robustness, and judging.

### Required fields

```yaml
run_id: unique immutable identifier
parent_run_id: baseline or previous experiment
status: planned | running | succeeded | failed | rejected | accepted
benchmark: kuairand | aliccp
split_definition: exact dataset partition/version
seed: integer or list
hypothesis: what is being tested
rationale: evidence or literature motivating it
planned_change: concise description
code_diff: patch, commit hash, or immutable diff artifact
commands: exact train/evaluate commands
config_artifact: immutable config path or serialized config
baseline_reference: organizer baseline identifier and observed result
metrics:
  gauc: number | null
  ndcg_at_5: number | null
  ctr_auc: number | null
  cvr_auc_clicked: number | null
  composite_validation_score: number | null # (gauc + ndcg_at_5) / 2
  delta_vs_parent: number | null
  delta_vs_official_baseline: number | null
resources:
  llm_input_tokens: integer
  llm_output_tokens: integer
  gpu_hours: number
  wall_clock_seconds: number
  peak_gpu_memory_mb: number | null
artifacts:
  checkpoint: path | null
  predictions: path | null
  stdout_log: path
  stderr_log: path | null
error_recovery:
  error: string | null
  diagnosis: string | null
  action: string | null
  result: string | null
decision: retain | reject | retry | branch | stop
next_hypothesis: string | null
manual_intervention_count: integer
```

### Logging rules

- **MUST** write the plan before executing a run and finalize the result after it ends.
- **MUST** preserve both successful and failed run records.
- **MUST** include the actual code diff, not a prose approximation.
- **MUST** log metrics from the official evaluation procedure (`evaluate.py`).
- **MUST** record cumulative and per-run LLM tokens and GPU-hours.
- **MUST** count a human edit, decision, command correction, manual restart, or manual recovery as an intervention.
- **MUST NOT** rewrite experiment history to remove regressions or failures.

---

## Repository and Implementation Expectations

Use a structure that a judge can run from a clean machine. Adapt names to the actual codebase, but preserve these responsibilities:

```text
README.md                 setup, reproduction, results, limitations, contributions
configs/                  immutable baseline and experiment configurations
data/                     dataset instructions only; do not commit restricted raw data
src/                      data, features, models, training, evaluation, agent logic
scripts/                  baseline, agent-run, evaluation, and submission entry points
runs/                     append-only iteration logs and lightweight metadata
artifacts/                checkpoints/predictions excluded from Git when too large
tests/                    targeted contract tests for preprocessing, metrics, recovery
```

The research agent should have separable responsibilities:

- **Task interpreter**: reads challenge configuration and validates requirements.
- **Data diagnostician**: profiles schema, distributions, and data-quality risks.
- **Experiment planner**: forms ranked, bounded hypotheses from evidence.
- **Code executor**: applies isolated code/config changes.
- **Trainer/evaluator**: launches deterministic runs and invokes the official evaluator.
- **Result analyst**: compares metrics, detects noise/regression, updates the experiment frontier.
- **Recovery controller**: recognizes failures and applies bounded safe recoveries.
- **Ledger/reporter**: writes immutable logs, resource accounting, and final summary.

Keep interfaces simple and file-backed. The agent must remain inspectable and runnable when the LLM is unavailable after a run.

---

## Do / Do Not

### Do

- Reproduce official baselines first.
- Use organizer configs, scripts, splits, and schemas as source of truth.
- Make each run attributable to a hypothesis, diff, config, command, seed, and artifact.
- Use train/validation metrics to drive the next step.
- Maintain a stable, reproducible fallback checkpoint.
- Design recovery paths before long autonomous runs.
- Prefer simple, measured changes over ungrounded sophistication.
- Optimize both GAUC and nDCG@5 because KuaiRand scoring weights them equally.
- Quantify resource usage throughout the run.
- Explain why an experiment was selected and why it was retained or rejected.
- Keep the public repository clean, runnable, and complete.

### Do not

- Do not use external training data or hidden-test information.
- Do not tune on test labels, manually inspect hidden-test outputs, or perform repeated hidden-test submissions.
- Do not report against a self-built baseline instead of the official baseline.
- Do not optimize only peak validation score while ignoring the convergence rule.
- Do not hide failures, regressions, retries, or manual interventions.
- Do not change several unrelated factors without an ablation plan.
- Do not claim model improvement without official-evaluator evidence.
- Do not hard-code unresolved organizer details such as baseline scores, compute limits, $\varepsilon$, $N$, or output schema.
- Do not spend primary-budget resources on the AliCCP bonus task before KuaiRand is robust.
- Do not let retries, hyperparameter sweeps, or LLM calls run without a budget cap.
- Do not make the system dependent on undocumented local paths, secrets, UI clicks, or human memory.

---

## Final Submission Checklist

Before submission, verify all of the following:

- [ ] KuaiRand-Pure pipeline runs end to end from documented setup.
- [ ] Official KuaiRand FM baseline (0.5946 primary) was reproduced and documented.
- [ ] Final artifact is the validation-best checkpoint/prediction at convergence or budget exhaustion.
- [ ] Predictions match the official CSV submission schema (`row_id,user_id,video_id,score`) and pass `submit.py --check`.
- [ ] Evaluation uses the organizer’s official metric implementation (`evaluate.py`).
- [ ] Results report GAUC, nDCG@5, and absolute delta versus the official baseline.
- [ ] Every iteration has hypothesis, code diff, metrics, and error/recovery log.
- [ ] Manual interventions are counted and summarized.
- [ ] Total LLM input/output tokens and GPU-hours are reported.
- [ ] README contains project overview, installation, reproduction steps, limitations, and team contributions.
- [ ] Devpost description lists the solution approach, development tools, APIs, libraries/frameworks, and datasets/assets.
- [ ] Demo shows an end-to-end autonomous run or a faithful recorded run with logs, metrics, and final artifact.
- [ ] AliCCP artifacts/results are included only if the bonus benchmark was genuinely attempted.

---

## Source and Authority

This guide operationalizes the official TikTok TechJam 2026 Track #2 statement, **“Autonomous Machine Learning Research Agent for Recommender Systems.”** When this guide conflicts with a newer organizer-provided Starter Kit, official evaluation script, baseline repository, submission schema, or explicit organizer instruction, the newer organizer material prevails.


# Rules to follow when generating outputs

## Communication & Explanation Rules

### 1. Plain-Language Explanations (Strict)
- **Think like a staff engineer, explain like a peer.** Maintain architectural depth and correctness in the background, but translate all explanations and documentation into everyday, functional English.
- **Banned jargon in explanations:** Avoid high-abstraction vocabulary unless strictly necessary (e.g., replace *"typed, immutable challenge contract"* with *"a locked-in set of rules that cannot be changed"*).
- **Rule of Functional Definition:** Whenever introducing a technical term or concept, explain what it *does* in real terms first:
  - *Don't say:* "User NLP is parsed into preferences, while organizer fields become invariants."
  - *Do say:* "The system reads what the user typed to figure out what they want (preferences), and locks down the organizer's settings so they can't be edited (rules that never change)."

### 2. Diagram & Architecture Formatting
- Use intuitive, action-oriented labels in diagrams and flowcharts (e.g., `Read User Input -> Lock Rule Set -> Validate Data` instead of `Ingest NLP Stream -> Instantiate Invariant Contracts`).
- Keep diagrams high-level and focused on data movement and user outcomes rather than academic design-pattern terminology.

### 3. Progressive Disclosure
- Always lead with a 1–2 sentence intuitive summary of how the system works.
- If deep implementation details (exact types, schemas, interfaces) are necessary, place them under a clearly marked `### Implementation Details (Code/Types)` section at the very end.

## Brevity & Output Control

### 1. Default Response Length
- **Default mode: Compact & Direct.** Keep default answers under 2–3 short paragraphs unless I explicitly ask for a deep dive, comprehensive breakdown, or detailed guide.
- **No filler intros or outros:** Never start responses with conversational fluff ("Sure, I can help with that", "That's a great question", "Here is a breakdown..."). Jump straight into the first point or code block.
- **No summary closings:** Do not end responses with repetitive wrap-up paragraphs ("In summary", "Overall, this ensures..."). Stop writing once the answer is complete.

### 2. High Signal, Zero Hallucinated Fluff
- Every sentence must provide concrete functional information or actionable code. 
- Avoid speculative commentary, generic best-practice preaching, or over-explaining standard library features.
- State assumptions directly in one line rather than writing hypothetical scenarios.

### 3. Depth on Demand
- Answer the immediate question directly. If there are advanced trade-offs or deeper layers, mention they exist in a single short sentence at the end (e.g., *"If you need the full database schema or concurrency handling, let me know."*).
