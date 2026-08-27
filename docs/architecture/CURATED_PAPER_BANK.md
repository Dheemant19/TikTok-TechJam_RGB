# Curated Paper Bank — Plain-Language Guide

This explains the design for the **Top-25 Local Vector Store** that ARCHITECTURE_v3
already names in §3.3 — the small, hand-picked set of papers (with working code)
that the Research Agent can check before it goes out to OpenAlex or GitHub.

## 1. What problem this solves

Right now the Research Agent's main way to find ideas is to search OpenAlex (a
research-paper search engine) and GitHub live, every time it needs evidence.
That's fine, but it costs tokens and API calls every single time, and it might
surface a paper that sounds relevant but doesn't actually have usable code, or
doesn't fit this specific problem.

A curated bank is just: **you, a human, pre-read ~25 papers, and only pick ones
that (a) actually apply to KuaiRand-Pure ranking and (b) come with real,
working code.** The agent then has these on hand instantly, for free, before
it ever needs to make a network call.

v3 already decided this should exist and capped it at 25 papers. This document
is about *how to store those 25 papers* so the rest of the system can use them.

## 2. Important: a contradiction in the challenge brief

Before picking papers, you need to know which metric you're actually
optimizing for, because it changes what "relevant" even means.

The official challenge document (`TechJam Track#2.docx`) says two different
things in two different places:

- Early sections (Problem Statement, Judging Criteria) say: **NDCG@10 /
  Recall@50**, with **click** as the positive signal.
- The **Starter Kit** section — which describes the actual `evaluate.py` code
  you'll be scored with — says: **GAUC / nDCG@5**, with **long_view** as the
  positive signal.

These are not the same task. v3 (your architecture doc) already committed to
the Starter Kit version (GAUC / nDCG@5 / long_view), which makes sense since
that's the real scoring code, not just prose. This doc follows that same
choice. **But you should double-check with the organizers before locking in
25 papers around the wrong metric** — it's a real inconsistency in their own
document, not something we're inferring.

## 3. The file format: one JSON file, 25 entries

Since it's capped at 25 papers, there's no need for anything fancy — one
JSON file, one entry per paper, in a plain array. No database needed for
something this small.

Here's what one entry looks like, with each field explained:

```json
{
  "paper_id": "arxiv:2401.xxxxx",
  "title": "Example: Deep Interest Network for CTR Prediction",
  "arxiv_id": "2401.xxxxx",
  "doi": null,
  "year": 2024,
  "venue": "RecSys 2024",
  "priority_area": "sequential_user_modeling",
  "keywords": ["DIN", "attention", "GAUC", "nDCG@5", "long_view"],
  "relevance_note": "Models a user's chronological watch history with an attention mechanism — directly usable since KuaiRand-Pure gives hundreds of chronological interactions per user.",
  "auxiliary_signals": [],
  "implementations": [
    {
      "repo_url": "https://github.com/example/din-pytorch",
      "is_official": true,
      "pinned_commit": "a1b2c3d",
      "file_hash": "sha256:...",
      "license": "MIT",
      "stars": 850,
      "last_commit": "2025-11-02"
    }
  ],
  "trust_tier": "curated",
  "added_by": "you",
  "added_at": "2026-08-27",
  "status": "unread"
}
```

Plain-language walkthrough of each field:

| Field | What it means | Why it's there |
|---|---|---|
| `paper_id` | A stable ID, usually `arxiv:<id>` | Every entry needs one unchanging name so it doesn't get duplicated if the same paper is later found again through OpenAlex |
| `title`, `year`, `venue` | Basic citation info | Self-explanatory — lets a human or the agent quickly recognize the paper |
| `priority_area` | Which of the 7 improvement directions in v3 §5 this paper targets | So the agent can ask "give me curated papers about X" and get an instant, free answer — no search needed |
| `keywords` | Exact words from the challenge, like `GAUC`, `nDCG@5`, `long_view`, `BPR` | The retrieval system uses two methods together: one that understands *meaning* (semantic search) and one that matches *exact words* (called BM25). BM25 only works if the exact technical term is actually written down here — "AUC-based ranking metric" won't match a search for "GAUC" |
| `relevance_note` | 1–2 sentences, written by you, on *why* this paper matters for this specific problem | This is the single most valuable field. A bare link is just a link — this note is what turns it into evidence the agent can actually reason with |
| `auxiliary_signals` | Which of KuaiRand's other 11 signals this method uses (`is_like`, `is_follow`, etc.) | Only fill this in for multi-task papers — tells the agent whether it has the right data available to try this idea |
| `implementations` | A list of GitHub repos implementing this paper | A list, not a single link, because a paper can have both an official repo and better community versions |
| → `is_official` | Is this the paper authors' own repo? | Official code is generally more trustworthy than a random reimplementation |
| → `pinned_commit`, `file_hash` | An exact, unchanging version of the code | Code on GitHub can change or break. Pinning a commit means "this exact version worked when I checked it" — same reproducibility rule the rest of the architecture uses everywhere else |
| → `license` | e.g. MIT, Apache-2.0 | You can't legally reuse code with certain licenses — this gets checked before anything is copied |
| → `stars`, `last_commit` | Popularity and freshness | Quick signal for "is this actively maintained or abandoned" |
| `trust_tier` | Always `"curated"` for this file | Distinguishes these from papers the system finds automatically later — curated ones get a small ranking boost |
| `added_by`, `added_at` | Who added it and when | Basic bookkeeping, useful if you're not working alone |
| `status` | `unread` / `reviewed` / `applied` / `rejected` | Lets you track which curated papers the team has actually acted on |

## 4. The 7 topics to pick papers for (from v3 §5)

v3 already worked out which research directions have real headroom on this
exact dataset. Use these as your `priority_area` values, and aim for roughly
3–4 papers each (≈ 25 total):

1. `ranking_loss_alignment` — pairwise/listwise ranking losses (BPR, Margin
   Ranking, Plackett-Luce) instead of plain classification loss. **Marked as
   top priority.**
2. `sequential_user_modeling` — modeling a user's chronological history
   (DIN, SIM, SASRec, transformers).
3. `multi_task_learning` — using the other 11 feedback signals to help
   predict `long_view` (MMoE, PLE).
4. `watch_time_censored_regression` — modeling watch time directly instead
   of just a binary label.
5. `feature_interaction_architectures` — DeepFM, DCNv2, xDeepFM, AutoInt.
6. `temporal_drift_modeling` — handling the time gap between train and test
   periods.
7. `off_policy_validation` — using KuaiRand's randomized-exposure data to
   validate more honestly.

**Do not spend a slot on:** papers whose main idea is "add more static
features" or "just make the model bigger." The organizers already tested
both on this exact dataset and got zero improvement (v3 §5) — a curated
paper repeating that would waste one of only 25 slots.

## 5. How the agent actually uses this file — and one correction

My first instinct was: "check the curated file first, and only search
OpenAlex/GitHub if nothing curated matches." v3 explicitly says *not* to do
that — it calls the curated set "non-exclusive," meaning it shouldn't be
treated as a closed set that blocks live search, because that risks biasing
the agent toward whatever 25 papers happened to get picked before real
diagnostics justified them.

The correct version: curated papers go through the **same** search process
as everything else (the combined meaning-search + exact-word-match system),
they just get ranked slightly higher because `trust_tier = curated`. The
efficiency win is simpler than a shortcut: reading this local file costs
nothing — no API call, no extra tokens — so whenever a curated paper does
rank highly, it's free evidence, without ever needing to skip the real
search.

## 6. Practical next step

A small script that checks, once per paper when you add or edit it (not at
agent runtime), that the GitHub link still works and refreshes the star
count / last-commit date — so the bank doesn't quietly rot into dead links
over the following weeks. Cheap to build, and keeps this file trustworthy
without costing the agent anything later.

## 7. Candidate Papers — Round 1 (pending your review)

25 real papers, cross-checked via search, mapped to the 7 priority areas.
**Repo existence was checked; stars/last-commit dates were not** — verify
those yourself before anything here goes into the final JSON. Mark each
`Decision` line as you go (`keep` / `remove` / `swap for X`).

### ranking_loss_alignment

1. **BPR: Bayesian Personalized Ranking from Implicit Feedback** — Rendle et al., UAI 2009, arXiv:1205.2618
   Pairwise ranking loss: optimizes "user prefers A over B" directly instead of scoring items independently.
   *Why it helps:* the textbook alternative to pointwise BCE — matches v3's top-priority recommendation.
   Code: community ports only (e.g. `Jeong-Junhwan/bpr`) — no canonical official repo.
   **Decision:** _

2. **LambdaMART / LambdaRank** — Burges et al.
   Gradient-boosted ranking that directly weights pairwise gradients by the NDCG change from swapping two items.
   *Why it helps:* fast, non-neural baseline aligned to `nDCG@5` — good sanity check against a neural model.
   Code: built into **LightGBM** (`lambdarank`) / **XGBoost** (`rank:ndcg`) — not a standalone paper repo.
   **Decision:** _

3. **PiRank: Scalable Learning To Rank via Differentiable Sorting** — Swezey, Grover, Charron, Ermon, NeurIPS 2021, arXiv:2012.06731
   Makes NDCG itself differentiable via a relaxed/soft sort operation.
   *Why it helps:* optimizes something closer to `nDCG@5` directly, rather than a surrogate like BPR.
   Code: official, `ermongroup/pirank`.
   **Decision:** _

4. **TF-Ranking: A Scalable TensorFlow Library for Learning-to-Rank** — Pasumarthi et al., KDD 2019, arXiv:1812.00073
   A library of pointwise/pairwise/listwise losses (ListNet, ApproxNDCG, LambdaLoss) in one place.
   *Why it helps:* lets the agent try several listwise objectives cheaply without writing each from scratch.
   Code: official, `tensorflow/ranking`, actively maintained (Google).
   **Decision:** _

### sequential_user_modeling

5. **Deep Interest Network for Click-Through Rate Prediction (DIN)** — Zhou et al. (Alibaba), arXiv:1706.06978
   Attention mechanism weighs a user's past interactions differently depending on the current candidate item.
   *Why it helps:* KuaiRand-Pure gives each user hundreds of chronological interactions — DIN is the standard first step to use them.
   Code: official, `zhougr1993/DeepInterestNetwork`.
   **Decision:** _

6. **Deep Interest Evolution Network (DIEN)** — Zhou et al. (Alibaba), arXiv:1809.03672
   Adds a two-layer GRU to model how a user's interest evolves, not just which past items are relevant.
   *Why it helps:* natural next step past DIN if attention alone underfits.
   Code: official, `mouna99/dien`.
   **Decision:** _

7. **Self-Attentive Sequential Recommendation (SASRec)** — Kang & McAuley, ICDM 2018
   Transformer-style self-attention over a user's interaction sequence, no recurrence.
   *Why it helps:* fast, well-established sequential baseline — good first thing to try.
   Code: official, `kang205/SASRec` — old TF1/Py2 repo, check for a maintained fork first.
   **Decision:** _

8. **BERT4Rec** — Sun et al. (Alibaba), arXiv:1904.06690
   Bidirectional Transformer trained with a masked-item objective over interaction sequences.
   *Why it helps:* usually stronger than SASRec but heavier — good once there's compute budget to spend.
   Code: official, `FeiSun/BERT4Rec`.
   **Decision:** _

### multi_task_learning

9. **Modeling Task Relationships with Multi-gate Mixture-of-Experts (MMoE)** — Ma et al. (Google), KDD 2018
   Shared expert sub-networks, with a per-task gating network deciding how much to draw from each expert.
   *Why it helps:* the standard architecture for using the other 11 KuaiRand signals to help `long_view`.
   Code: community, `drawbridge/keras-mmoe` — most-cited open implementation, not official Google code.
   **Decision:** _

10. **Progressive Layered Extraction (PLE)** — Tang et al. (Tencent), RecSys 2020
    Adds task-private experts on top of MMoE's shared experts, specifically to reduce the "seesaw" effect.
    *Why it helps:* the docx's own primer (A.3) names the seesaw problem explicitly — this paper targets it directly.
    Code: community, `QunBB/RecSys` — no confirmed official repo.
    **Decision:** _

11. **Entire Space Multi-Task Model (ESMM)** — Ma et al. (Alibaba), SIGIR 2018, arXiv:1804.07931
    Jointly models the full impression→click→conversion funnel to fix sample-selection bias.
    *Why it helps:* the same bias structure applies to any post-click signal here (docx A.2), even without a CVR label.
    Code: community, `dai08srhg/ESMM` — not official.
    **Decision:** _

12. **Multi-Task Learning as Multi-Objective Optimization** — Sener & Koltun (Intel Labs), NeurIPS 2018, arXiv:1810.04650
    Treats multi-task training as finding a Pareto-optimal point across tasks' gradients, instead of fixed loss weights.
    *Why it helps:* a diagnostic to confirm an auxiliary signal is actually helping (not fighting) `long_view` before committing to MMoE/PLE.
    Code: official, `isl-org/MultiObjectiveOptimization`.
    **Decision:** _

### feature_interaction_architectures

13. **DeepFM** — Guo et al. (Huawei), IJCAI 2017, arXiv:1703.04247
    Combines a Factorization Machine with a deep MLP sharing embeddings — no manual feature-crossing needed.
    *Why it helps:* the official baseline is already an FM — this is the minimal upgrade path.
    Code: `shenweichen/DeepCTR` — the field's de facto reference implementation, not author-written but treated as canonical.
    **Decision:** _

14. **DCN V2: Improved Deep & Cross Network** — Wang et al. (Google), arXiv:2008.13535
    Learns explicit, bounded-degree feature crosses via a cross network run in parallel with a deep network.
    *Why it helps:* stronger, cheaper feature-crossing than plain DeepFM.
    Code: `DeepCTR`'s "DCN-Mix" is an approximation, not a verified port of the original architecture — no official repo found, flag before use.
    **Decision:** _

15. **xDeepFM** — Lian et al. (Microsoft/USTC), KDD 2018, arXiv:1803.05170
    Adds a Compressed Interaction Network that learns feature crosses at the vector level, not bit level.
    *Why it helps:* a well-cited middle ground between DeepFM and DCN.
    Code: official, `Leavingseason/xDeepFM`.
    **Decision:** _

16. **AutoInt** — Song et al., CIKM 2019, arXiv:1810.11921
    Multi-head self-attention over feature embeddings learns which combinations matter, instead of hand-designed crosses.
    *Why it helps:* a different interaction mechanism than DCN/xDeepFM — useful as a contrast experiment.
    Code: official, `shichence/AutoInt`.
    **Decision:** _

### watch_time_censored_regression

17. **CWM: Counteracting Duration Bias in Video Recommendation via Counterfactual Watch Time** — KDD 2024, arXiv:2406.07932
    Reframes watch time as "value delivered" using counterfactual reasoning, separating genuine interest from the fact that longer videos allow longer watch times.
    *Why it helps:* directly targets the duration confound in `play_time_ms` (v3 priority #4), from a Kuaishou-adjacent research line.
    Code: official, `hyz20/CWM`.
    **Decision:** _

18. **D2Co** — RecSys 2023
    Companion/earlier method from the same authors as CWM, correcting watch-time labels for bias and noise.
    *Why it helps:* a simpler correction to try before CWM's full counterfactual framework.
    Code: official, `hyz20/D2Co`.
    **Decision:** _

19. **Time-to-Event Prediction with Neural Networks and Cox Regression** — Kvamme, Borgan, Scheel, JMLR 2019
    General-purpose survival-analysis library (`pycox`) for right-censored outcomes.
    *Why it helps:* `play_time_ms` is right-censored — off-the-shelf tooling instead of building censored-regression handling from scratch.
    Code: official, `havakv/pycox`.
    **Decision:** _

*(Dropped from this round: "Deconfounding Duration Bias" / D2Q, arXiv:2206.06003 — real KDD'22 Kuaishou paper, but no public code repo found in this pass. Worth a manual second look before ruling it out.)*

### temporal_drift_modeling

20. **TiSASRec: Time Interval Aware Self-Attention for Sequential Recommendation** — Li, Wang, McAuley, WSDM 2020
    Extends SASRec by encoding the actual time gaps between interactions, not just their order.
    *Why it helps:* a minimal add-on to SASRec (priority #2) that also covers recency/temporal dynamics (priority #6).
    Code: official, `JiachengLi1995/TiSASRec` (TF; PyTorch ports linked from the repo).
    **Decision:** _

21. **TGSRec: Continuous-Time Sequential Recommendation with Temporal Graph Collaborative Transformer** — Fan et al., CIKM 2021, arXiv:2108.06625
    Models interactions as a continuous-time graph, so it can predict at any future timestamp, not just "next item."
    *Why it helps:* directly tests generalization across KuaiRand-Pure's train (Apr 8–21) / test (Apr 29–May 8) gap.
    Code: official, `DyGRec/TGSRec`.
    **Decision:** _

22. **Algorithmic Drift: A Simulation Framework to Study the Effects of Recommender Systems on User Preferences** — 2024, arXiv:2409.16478
    Simulates how a deployed recommender's choices reshape future user behavior (online feedback-loop drift).
    *Why it helps:* weakest fit of the 25 — this is about online drift, not offline train/test shift; useful mainly as background on the docx's own "offline vs. online" caveat (A.4).
    Code: official, `SimoneMungari/AlgorithmicDrift`.
    **Decision:** _

### off_policy_validation

23. **KuaiRand: An Unbiased Sequential Recommendation Dataset with Randomly Exposed Videos** — Gao et al., CIKM 2022, arXiv:2208.08696
    The paper KuaiRand-Pure itself comes from — explains exactly how the randomized-exposure log was collected and what it's valid for.
    *Why it helps:* non-negotiable include.
    Code: official, `chongminggao/KuaiRand`.
    **Decision:** _

24. **KuaiRec: A Fully-observed Dataset and Insights for Evaluating Recommender Systems** — Gao et al., CIKM 2022, arXiv:2202.10842
    Companion near-fully-observed dataset from the same lab, studying how exposure bias distorts offline evaluation.
    *Why it helps:* directly useful for sanity-checking whether KuaiRand-Pure's validation metric is distorted by exposure bias.
    Code: official, `chongminggao/KuaiRec`.
    **Decision:** _

25. **Doubly Robust Off-Policy Evaluation for Ranking Policies under the Cascade Behavior Model** — Kiyohara et al., WSDM 2022 (Best Paper Runner-Up), arXiv:2202.01562
    Statistically corrected estimator for how a new ranking policy would perform, using only logged data from the old policy.
    *Why it helps:* the actual technique for turning the randomized-exposure log into a trustworthy off-policy validation signal (priority #7).
    Code: official, `aiueola/wsdm2022-cascade-dr`.
    **Decision:** _

### Flags to check before finalizing

- #1 (BPR), #10 (PLE), #11 (ESMM), #14 (DCN V2) — only community reimplementations found, no official author repo.
- #2 (LambdaMART) isn't a standalone paper repo — it's a built-in objective in LightGBM/XGBoost. Decide if that fits the schema or should be dropped.
- #14's `DeepCTR` "DCN-Mix" approximates DCN V2, it isn't a verified port of the original architecture.
- #22 is the loosest topical fit — candidate for removal or replacement.
- No star counts or last-commit dates were verified for any repo — required before writing `stars` / `last_commit` into the JSON.
