# Architecture: Autonomous ML Research Agent for AliCCP

This document describes the agent architecture developed from the initial hand-drawn
draft, revised to close the iteration loop and separate two different kinds of failure
handling. It maps each component to a role in the challenge's MLE loop (read problem →
EDA → engineer features → train/tune → evaluate → reflect/iterate).

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
- Reports metrics (and any unresolved errors) up to the Orchestrator

### Orchestrator — Diagnose, budget, and control the loop

**Corresponds to challenge stage 6 ("reflect and iterate") plus the overall stopping
condition.**

- Compares SA3's result against the official baseline
- Tracks the compute/wall-clock budget and the ε/N convergence rule (stop when the
  score hasn't improved by more than ε over N consecutive iterations, or the budget is
  hit — whichever comes first)
- Reads and writes the **lineage memory** to inform its decision (has this hypothesis
  been tried before? what happened last time?)
- Decides one of two outcomes:
  - **Converged or budget hit** → produce the final report to the user
  - **Not converged** → route a new hypothesis back to SA2, informed by *why* the
    previous attempt fell short (not just "try again")

**Open design question, not yet resolved:** the ε/N rule currently does double duty as
both the stopping condition and the implicit signal for "is this hypothesis worth
pursuing further." Whether these should be the same check or two separate ones is worth
deciding before implementation — conflating them risks either stopping too early on a
promising but slow-improving direction, or never stopping on a direction that's
technically still inching forward.

### Lineage memory

Tracks code and dataframe history — which version of the code produced which result,
what's already been tried. This is what the run-log deliverable is built from directly;
it is not a separate thing to maintain by hand.

Distinct from the item/category graph above — this is agent memory (what happened),
not a model feature (what the model sees). Both are called "knowledge graphs" loosely,
but they solve unrelated problems and shouldn't be conflated in the write-up.

### Item/category graph (feature source)

Built once, upfront, from AliCCP's own structured data — not from documents, and not
regenerated per iteration. Recommended construction: co-click/co-conversion behavioral
signal (closer to EGES/GIN) rather than pure "shares a category" (which risks
duplicating information already available via the category_id embedding directly).

## 3. The closed loop, stated plainly

1. SA1 reads the problem and the data
2. SA2 proposes a feature/model change (drawing on the item graph as one option)
3. SA3 writes the code, runs it on the subsample, and — if promoted — the full data
4. Orchestrator compares the result to baseline and checks the budget/convergence rule
5. If not converged: Orchestrator routes a new hypothesis back to SA2 (step 2 repeats)
6. If converged or budget hit: Orchestrator produces the final report

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
