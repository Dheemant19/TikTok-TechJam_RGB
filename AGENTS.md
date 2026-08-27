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

### Required benchmark: KuaiRand

KuaiRand is a short-video feed dataset with multiple feedback signals and randomized exposure data.

Required metric task:

- Click is the positive relevance label.
- **NDCG@10**.
- **Recall@50**.

- KuaiRand determines **100% of the primary metric score**.
- Ranking candidates, relevance labels, and query/user grouping must follow the organizer-provided evaluator exactly.
- The official baseline is the organizer-referenced KuaiRand implementation and configuration; do not substitute a self-created starter model.

Organizer-provided suggested split:

- `log_standard_4_08_to_4_21_*`: train.
- First 50% of `log_standard_4_22_to_5_08_*`: validation.
- Last 50% of `log_standard_4_22_to_5_08_*`: test.

The randomized-exposure data enables counterfactual/off-policy evaluation research, but that is advanced optional work unless the organizer's official primary task or evaluator requires it.

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

For each metric $m$:

```text
delta(m) = score_agent(m) − score_official_baseline(m)
score_dataset = mean(delta(m) for all dataset metrics)
```

For KuaiRand, this is the equal-weighted mean of NDCG@10 delta and Recall@50 delta. Absolute improvement is used: do not substitute relative percentage improvement.

### Convergence

The scored result is the **converged** result, not the highest temporary metric. A run converges when validation score fails to improve by more than organizer-defined $\varepsilon$ for organizer-defined $N$ consecutive iterations, or the fixed compute/wall-clock budget is reached. Use the validation-best artifact at that point.

The following are organizer-controlled configuration, not assumptions to hard-code:

- Baseline scores.
- Exact scoring/evaluation script.
- Submission schema.
- $\varepsilon$ and $N$.
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

- Sample counts by split and label prevalence.
- Click prevalence, interactions per user, candidate-set size, and users with no relevant validation items.
- Feature type, cardinality, sparsity, missingness, and unseen-ID behavior.
- Train/validation distribution shift.
- Model capacity, train-vs-validation gap, ranking-loss behavior, and convergence curves.
- Per-signal losses and task interference when auxiliary feedback is used.
- NDCG@10 and Recall@50 confidence/stability across seeds where budget permits.
- Runtime, GPU memory, dataloader throughput, and failure traces.
- Outcomes of prior experiments, including regressions.

### Phase 3 — Execute a bounded experiment

Each experiment must contain one primary hypothesis and an explicit success criterion.

A valid iteration:

1. Records the hypothesis and rationale.
2. Names the intended pipeline change.
3. Applies a code diff in an isolated experiment workspace or revision.
4. Runs a preflight/smoke check when the change is structurally risky.
5. Trains and evaluates with the official evaluator.
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

These are candidate directions, not mandatory changes. Select them from diagnostics and prior outcomes.

### Features and representation

- Correct handling of high-cardinality categorical IDs with embeddings.
- Feature cardinality thresholds, rare-category handling, and hashed representations where justified.
- Embedding dimension and regularization choices proportional to feature cardinality.
- Missing-value and unseen-category treatment consistent between train and validation.
- Carefully validated feature crosses for meaningful user/video/author/category interactions.
- Watch-time, engagement, frequency, or recency-derived features only when they respect chronological split boundaries and avoid label leakage.
- Candidate-generation and ranking features must be reproducible for validation and test without using future interactions.

### Model architectures

Begin with stable, reproducible baselines, then test justified alternatives:

- Popularity, logistic-regression, and matrix-factorization-style sanity checks.
- Two-tower retrieval models with sampled negatives when candidate generation is in scope.
- Wide & Deep, DeepFM, xDeepFM, or DCN/DCNv2 for ranking feature interactions.
- Sequential recommenders when timestamped user history is available without crossing split boundaries.
- MMoE or PLE only when auxiliary feedback signals improve the primary click-ranking metrics in measured ablations.

### Ranking objectives and sampling

- Pointwise, pairwise, or listwise objectives selected according to measured alignment with NDCG@10 and Recall@50.
- Negative-sampling distributions that reflect the official candidate set and do not leak validation or test interactions.
- Hard-negative mining only from permitted training data and model-generated scores.
- Auxiliary engagement objectives only when they improve the primary click-ranking metrics.
- Negative-transfer detection: an auxiliary task rising while a primary metric falls is evidence to change task sharing, not a result to hide.

### Training and evaluation

- Learning-rate schedules, warmup, optimizer, weight decay, dropout, gradient clipping, and batch size.
- Early stopping based on the correct composite validation objective.
- Seed stability and validation variance checks before treating a tiny difference as a discovery.
- Efficient data loading and mixed precision where they preserve correctness.
- Validate candidate coverage, duplicate handling, tie behavior, and per-user ranking construction against the official evaluator.
- Analyze head-versus-tail users/items and ranking depth; optimize the official ranking metrics rather than proxy loss alone.

### Priority order

1. Correct data, evaluator, baseline reproduction, and reliable training.
2. High-information diagnostics and inexpensive ablations.
3. Improvements that lift the equal-weighted NDCG@10/Recall@50 objective rather than one metric alone.
4. More complex architectures only after simpler alternatives provide evidence.
5. AliCCP only after KuaiRand is submission-ready.

---

## Experiment Selection Policy

The agent should optimize improvement per unit of risk and resource consumption.

- Prefer experiments with a concrete causal rationale from diagnostics or accepted recommender-system methods.
- Favor low-cost falsification runs before full-scale training.
- Reuse successful components; do not rebuild the pipeline unnecessarily.
- Use a fixed baseline and a clear parent experiment for every comparison.
- Penalize complexity that has no measured benefit.
- Avoid broad blind grid searches, unbounded agent loops, and expensive architecture churn.
- Treat small improvements within seed noise as unconfirmed until validated.
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
  ndcg_at_10: number | null
  recall_at_50: number | null
  ctr_auc: number | null
  cvr_auc_clicked: number | null
  composite_validation_score: number | null
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
- **MUST** log metrics from the official evaluation procedure.
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
- Optimize both NDCG@10 and Recall@50 because KuaiRand scoring weights them equally.
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

- [ ] KuaiRand pipeline runs end to end from documented setup.
- [ ] Official KuaiRand baseline was reproduced and documented.
- [ ] Final artifact is the validation-best checkpoint/prediction at convergence or budget exhaustion.
- [ ] Predictions/checkpoint match the official submission schema.
- [ ] Evaluation uses the organizer’s official metric implementation.
- [ ] Results report NDCG@10, Recall@50, and absolute delta versus the official baseline.
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
