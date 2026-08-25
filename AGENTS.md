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

- **MUST** use only the challenge datasets for training: AliCCP and, if attempted, KuaiRand.
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

### Required benchmark: AliCCP

AliCCP is an Alibaba/Taobao e-commerce benchmark for the funnel:

```text
impression → click → conversion
```

Required metrics:

- **CTR AUC** over all impressions, where click is positive.
- **CVR AUC** over the clicked subset, where conversion is positive.

Important implications:

- CVR is conditional: $P(\text{conversion} \mid \text{click})$.
- Conversion labels are sparse.
- CVR observations create sample-selection bias because conversion is observed only after a click.
- The agent may model CTCVR internally, but reported metrics remain CTR AUC on all impressions and CVR AUC on clicked impressions.
- AliCCP determines **100% of the primary metric score**.
- Official reference implementation: NISE repository specified by the organizers.

### Bonus benchmark: KuaiRand

KuaiRand is a short-video feed dataset with multiple feedback signals and randomized exposure data.

Default metric task:

- Click is the positive relevance label.
- **NDCG@10**.
- **Recall@50**.

KuaiRand is optional. A strong result earns bonus credit, but skipping it must not reduce the AliCCP primary score. Do not spend AliCCP-critical time or resources on KuaiRand until AliCCP has a reliable end-to-end result.

Organizer-provided suggested split:

- `log_standard_4_08_to_4_21_*`: train.
- First 50% of `log_standard_4_22_to_5_08_*`: validation.
- Last 50% of `log_standard_4_22_to_5_08_*`: test.

The randomized-exposure data enables counterfactual/off-policy evaluation research, but that is advanced optional work, not part of the primary score.

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

For AliCCP, this is the equal-weighted mean of CTR AUC delta and CVR AUC delta. Absolute improvement is used: do not substitute relative percentage improvement.

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
- CTR/CVR class imbalance and clicked-subset size.
- Feature type, cardinality, sparsity, missingness, and unseen-ID behavior.
- Train/validation distribution shift.
- Model capacity, train-vs-validation gap, calibration, and convergence curves.
- Per-task losses and task interference.
- AUC confidence/stability across seeds where budget permits.
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

## High-Value AliCCP Research Directions

These are candidate directions, not mandatory changes. Select them from diagnostics and prior outcomes.

### Features and representation

- Correct handling of high-cardinality categorical IDs with embeddings.
- Feature cardinality thresholds, rare-category handling, and hashed representations where justified.
- Embedding dimension and regularization choices proportional to feature cardinality.
- Missing-value and unseen-category treatment consistent between train and validation.
- Carefully validated feature crosses for meaningful user/item/category interactions.
- Frequency or recency-derived features only when they respect split boundaries and avoid label leakage.

### Model architectures

Begin with stable, reproducible baselines, then test justified alternatives:

- Logistic regression / factorization-machine-style sanity checks.
- Wide & Deep, DeepFM, xDeepFM, DCN/DCNv2 for feature interactions.
- ESMM for the impression → click → conversion funnel.
- MMoE or PLE when multi-task sharing/interference diagnostics justify it.
- Task towers, shared-bottom capacity, and expert/gate configuration chosen through measured ablations.

### Multi-task objectives

- CTR and CVR loss balancing.
- CVR-on-clicked-subset alignment with the official metric.
- CTCVR auxiliary objectives when they improve funnel consistency.
- Negative transfer detection: one task rising while the other falls is evidence to investigate task sharing, not a metric to hide.
- Label weighting or focal-style methods only with a documented class-imbalance rationale and metric validation.

### Training and evaluation

- Learning-rate schedules, warmup, optimizer, weight decay, dropout, gradient clipping, and batch size.
- Early stopping based on the correct composite validation objective.
- Seed stability and validation variance checks before treating a tiny difference as a discovery.
- Efficient data loading and mixed precision where they preserve correctness.
- Calibration analysis as a diagnostic; AUC ranking is primary, so do not optimize calibration at the expense of ranking without evidence.

### Priority order

1. Correct data, evaluator, baseline reproduction, and reliable training.
2. High-information diagnostics and inexpensive ablations.
3. Improvements that lift the equal-weighted CTR/CVR objective rather than one metric alone.
4. More complex architectures only after simpler alternatives provide evidence.
5. KuaiRand only after AliCCP is submission-ready.

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
benchmark: aliccp | kuairand
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
  ctr_auc: number | null
  cvr_auc_clicked: number | null
  ndcg_at_10: number | null
  recall_at_50: number | null
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
- Optimize both CTR and CVR because AliCCP scoring weights them equally.
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
- Do not spend primary-budget resources on the KuaiRand bonus task before AliCCP is robust.
- Do not let retries, hyperparameter sweeps, or LLM calls run without a budget cap.
- Do not make the system dependent on undocumented local paths, secrets, UI clicks, or human memory.

---

## Final Submission Checklist

Before submission, verify all of the following:

- [ ] AliCCP pipeline runs end to end from documented setup.
- [ ] Official AliCCP baseline was reproduced and documented.
- [ ] Final artifact is the validation-best checkpoint/prediction at convergence or budget exhaustion.
- [ ] Predictions/checkpoint match the official submission schema.
- [ ] Evaluation uses the organizer’s official metric implementation.
- [ ] Results report CTR AUC, CVR AUC, and absolute delta versus the official baseline.
- [ ] Every iteration has hypothesis, code diff, metrics, and error/recovery log.
- [ ] Manual interventions are counted and summarized.
- [ ] Total LLM input/output tokens and GPU-hours are reported.
- [ ] README contains project overview, installation, reproduction steps, limitations, and team contributions.
- [ ] Devpost description lists the solution approach, development tools, APIs, libraries/frameworks, and datasets/assets.
- [ ] Demo shows an end-to-end autonomous run or a faithful recorded run with logs, metrics, and final artifact.
- [ ] KuaiRand artifacts/results are included only if the bonus benchmark was genuinely attempted.

---

## Source and Authority

This guide operationalizes the official TikTok TechJam 2026 Track #2 statement, **“Autonomous Machine Learning Research Agent for Recommender Systems.”** When this guide conflicts with a newer organizer-provided Starter Kit, official evaluation script, baseline repository, submission schema, or explicit organizer instruction, the newer organizer material prevails.
