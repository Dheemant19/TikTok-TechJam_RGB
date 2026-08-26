# Architecture: Autonomous ML Research Agent for AliCCP

This document describes the agent architecture developed from the initial hand-drawn
draft, revised to close the iteration loop, separate two different kinds of failure
handling, and — in this revision — adopt four low-cost fixes identified by comparing
against a teammate's more elaborate RIGOR-RS proposal. It maps each component to a role
in the challenge's MLE loop (read problem → EDA → engineer features → train/tune →
evaluate → reflect/iterate).

**Changelog from the previous draft:**
1. Added a hard baseline-reproduction gate before any novel experiment is allowed
2. Added a test-label firewall check at the end of every experiment
3. SA2 now states a predicted outcome before SA3 runs anything (resolves the open
   convergence-vs-worth-pursuing question from the previous draft)
4. Added a rubric-mapping table for the write-up

Deliberately **not** adopted from RIGOR-RS: its capability/taint access-control model,
claim-resolution graph, full five-category test suite, and judge-facing observer UI.
These are real ideas but production-system-scale engineering — the time they'd cost is
better spent getting an actual converged run, which is what Technical Execution (35% of
the score) actually requires.

## 1. Overview

The system is one autonomous agent internally composed of three specialized sub-agents
(SA1, SA2, SA3) coordinated by an Orchestrator. All five components together constitute
"the agent" the challenge asks for — there is no human step anywhere in the loop below.

```
Item graph (feature source)
        |
        v
SA1 --> SA2 --> SA3
              (loop)  |
Orchestrator <--------+
   |         ^
   v         |  (not converged: new hypothesis)
Lineage      |
memory  -----+
   |
   v (converged / budget hit)
Report to user
```

## 2. Component roles

### SA1 — Read data + EDA

**Corresponds to challenge stage 1-2 ("read the problem," "inspect data").**

- Reads the fixed data split and the metric definitions (CTR AUC over all impressions,
  CVR AUC over the clicked subset only)
- Performs exploratory data analysis: distributions, class imbalance, missing values
- Produces a structural summary that SA2 consumes — not a modeling decision itself
- **Runs the baseline-reproduction gate first** (see §3a) — nothing downstream starts
  until this passes

This stage is deliberately kept simple and low-risk: a mistake here (e.g. misreading
the metric definition) is the most expensive kind of error in the whole system, since
every downstream iteration would optimize toward the wrong target.

### SA2 — Feature engineering + model selection

**Corresponds to challenge stage 3 ("engineer features") and part of stage 4 ("train
and tune").**

- Proposes what to try: a feature (e.g. a feature cross, a graph embedding) or a model
  choice (ESMM, MMoE, PLE — see EasyRec's reference implementations)
- Consumes the **item/category graph embeddings** as one available feature source,
  aimed specifically at the CVR sparsity problem (conversions are rare; graph-neighbor
  items can supply signal a sparse item's own ID embedding can't)
- **States a predicted outcome before SA3 runs anything**: which direction it expects
  CTR AUC and CVR AUC to move, and why. This is a single field on the hypothesis, not
  new infrastructure — but it means the Orchestrator is checking "did this go the way
  SA2 predicted," not just "did the number go up," which is what actually resolves
  whether a marginal, noise-level uptick counts as progress
- Is also the default destination when the Orchestrator determines a hypothesis needs
  revising — most "didn't beat baseline" cases are a feature/model problem, not a data
  problem, so this is the primary re-entry point for the loop

### SA3 — Write, run, and score code

**Corresponds to challenge stage 4 ("train and tune") and stage 5 ("evaluate").**

- Turns SA2's proposal into actual code and executes it
- Applies the **subsample-first strategy**: every hypothesis is tested on a small
  stratified sample (preserving the click/conversion ratio) before any full-scale run
- Applies the **promotion rule**: a candidate is only run at full scale once it clearly
  beats the subsample baseline by more than a noise-level margin
- Handles its own crash recovery locally: if execution throws an error, the traceback
  is fed back into SA3's own next attempt — this never involves the Orchestrator, since
  a bug is not a strategic decision
- **Never has read access to the test split.** Only train and validation files are on
  its data path — this isn't a policy SA3 has to remember to follow, it's simply the
  only data made available to it
- Reports metrics (and any unresolved errors) up to the Orchestrator

### Orchestrator — Diagnose, budget, and control the loop

**Corresponds to challenge stage 6 ("reflect and iterate") plus the overall stopping
condition.**

- Compares SA3's result against the official baseline **and** against SA2's predicted
  outcome — a result that beat the baseline but not in the way predicted still gets
  flagged for the run-log, since that's useful signal even when the number looks good
- Tracks the compute/wall-clock budget and the ε/N convergence rule (stop when the
  score hasn't improved by more than ε over N consecutive iterations, or the budget is
  hit — whichever comes first). This is now a **separate check** from "was this
  hypothesis worth it" (that's SA2's predicted-outcome comparison above) — the two were
  conflated in the previous draft
- Reads and writes the **lineage memory** to inform its decision (has this hypothesis
  been tried before? what happened last time?)
- **Runs the test-label firewall check** before finalizing: confirms no experiment in
  the run's history ever touched the test split. One assertion, checked every run — not
  a full access-control system, just a guardrail against an expensive mistake
- Decides one of two outcomes:
  - **Converged or budget hit** → produce the final report to the user
  - **Not converged** → route a new hypothesis back to SA2, informed by *why* the
    previous attempt fell short (not just "try again")

### Lineage memory

Tracks code and dataframe history — which version of the code produced which result,
what's already been tried. This is what the run-log deliverable is built from directly;
it is not a separate thing to maintain by hand.

Distinct from the item/category graph above — this is agent memory (what happened),
not a model feature (what the model sees). Both are called "knowledge graphs" loosely,
but they solve unrelated problems and shouldn't be conflated in the write-up.

Kept as a flat, queryable log (a table, not a graph database) — a graph structure was
considered and dropped for the same reason RIGOR-RS's own design writeup gives for
doing the same: a relational ledger does the job with far less engineering risk than an
actual graph store, for something that's fundamentally a parent-child history.

### Item/category graph (feature source)

Built once, upfront, from AliCCP's own structured data — not from documents, and not
regenerated per iteration. Recommended construction: co-click/co-conversion behavioral
signal (closer to EGES/GIN) rather than pure "shares a category" (which risks
duplicating information already available via the category_id embedding directly).

## 3. The closed loop, stated plainly

### 3a. Before the loop starts: baseline-reproduction gate

The challenge requires reproducing the official baseline before any improvement claim
is allowed (Task Requirement 1). This is enforced as a hard gate, not a step SA1 might
skip under time pressure:

1. SA1 trains and evaluates the official baseline pipeline exactly as provided
2. Its result is compared against the organizer's published baseline score
3. **If it doesn't match** (within a reasonable tolerance), the loop does not proceed —
   diagnose environment/data/split mismatches first, since a wrong baseline number
   invalidates every delta computed against it afterward
4. Only once this passes does SA2 get its first turn

### 3b. The loop itself

1. SA2 proposes a feature/model change **and states its predicted outcome**
2. SA3 writes the code, runs it on the subsample, and — if promoted — the full data,
   without ever touching the test split
3. Orchestrator compares the result to baseline, to SA2's prediction, and checks the
   budget/convergence rule
4. If not converged: Orchestrator routes a new hypothesis back to SA2 (step 1 repeats)
5. If converged or budget hit: Orchestrator runs the test-label firewall check, then
   produces the final report

No step in this cycle requires a human. Manual intervention is only counted if a person
steps in from outside this loop (e.g. editing a config, restarting a stuck run).

## 4. Two kinds of failure, two different handlers

| Failure type | Example | Handled by | Involves Orchestrator? |
|---|---|---|---|
| Code-level | Exception, timeout, bad shape | SA3's local retry | No |
| Strategy-level | Ran fine, didn't beat baseline | Orchestrator's diagnosis | Yes |

Keeping these separate matters: a code bug doesn't need strategic reasoning, and a
disappointing-but-working result doesn't need a bug-fix loop. Conflating them would
mean every crash burns an Orchestrator decision cycle it doesn't need.

## 5. Deliberately out of scope for now

- **MCP integration** — undecided. Would only be worth the engineering time if SA3's
  code execution needs to be exposed as a callable tool to multiple consumers; for a
  single-agent hackathon build, plain function calls are simpler and equally valid.
- **UI visualizing the workflow in real time** — not required by the deliverables
  (which ask for a repo, README, run-logs, and a results table, not a UI). Worth
  building only after the autonomous loop itself is solid and converging reliably.
- **Full capability/taint access control, claim-resolution graph, judge observer UI**
  (all present in RIGOR-RS) — real ideas, but production-scale engineering that risks
  consuming the time needed to get an actual converged, improved result.

## 6. Rubric mapping

| Judging criterion | Architecture evidence |
|---|---|
| Technical Execution (35%) | Baseline-reproduction gate, subsample-first + promotion rule, local crash recovery, ε/N convergence check |
| Innovation & Problem Insight (20%) | Item/category graph targeted at CVR sparsity, SA2's predicted-outcome-before-running discipline |
| Impact & Relevance (20%) | Fully closed loop with zero required human steps; manual interventions countable by definition (anything outside the loop) |
| Feasibility & Practicality (15%) | Subsample-first strategy keeps GPU-hours and token cost down; lineage memory as flat log, not a heavier graph store |
| Presentation & Communication (10%) | This document + the run-log's hypothesis/prediction/outcome trail |
