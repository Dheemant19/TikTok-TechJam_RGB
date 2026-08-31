# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two audiences, same screen: (1) hackathon judges watching a short live/replayed demo of an autonomous ML research agent, who need to instantly read "what is the system doing right now and is it working" without domain briefing; (2) the operator (competition team) who needs precise, inspectable state — inputs, outputs, artifacts, timing, past attempts — for every stage of the pipeline, plus safe start/pause/resume/cancel control. Both are watching a long-running, mostly-autonomous process punctuated by real decisions (retain/reject an experiment, recover from a failure, register a new best) that need to read as consequential, not decorative.

## Product Purpose

FlowState Workflow Observer is the control-room view of an autonomous ML research agent (FlowState) that reproduces an official recommender-systems baseline, proposes and runs bounded experiments, and converges on a validation-best submission — with zero required human intervention. The UI shows the entire pipeline (data prep → baseline → research → code → train/score → decide → package) as one continuous system: zoomed out, the whole pipeline is visible at once as live telemetry; focused on one stage, that stage takes over the view with its real logs, inputs, outputs, and history. Success = a viewer can tell, at a glance, exactly which stage is active, what it just decided, and why — and can drill into any stage without losing the sense of the whole running system.

## Positioning

FlowState is not a static recommender model or a hyperparameter-search wrapper: it is an auditable, low-intervention research agent that a neighboring "we ran AutoML on your dataset" tool could not truthfully claim to be. Every claimed improvement is gated on first reproducing the organizer's official FM baseline (not a self-built starter baseline); every experiment is a real code diff run through the official evaluator (`kuairand-starter-kit/evaluate.py`), not a narrated intention; every failure, recovery, and manual intervention is logged rather than discarded; and the final submission is the validation-best artifact at organizer-defined convergence ($\varepsilon = 0.002$, $N = 3$), not the best transient reading. The Workflow Observer UI is the surface that makes this auditability visible rather than asserted.

## Brand Personality

*(Superseded 2026-08-28 — see the revision note at the end of this section.)* Mission control / observatory. Precise, calm, confident — an instrument panel, not a toy. Three words: **instrumented, unhurried, exact.** Idle state holds still (or drifts in a slow, deliberate orbit); motion is reserved for real state changes, not ambient decoration. One committed accent — amber/phosphor, CRT-instrument warmth against near-black — carries "this is active / this is signal" across the whole scene. The system should feel like it is quietly, competently running itself, and the viewer is allowed to watch.

**Revision (2026-08-28, v2):** the user explicitly reversed this in favor of a light, multi-color card system, pinned by a reference screenshot (an n8n-style AI-agent workflow builder: white cards with colored header accents — teal, pink, violet, amber, blue — on a light dotted-grid background) plus explicit interaction references (Spline/IcePanel for 3D depth and camera motion, tsl-graph.xyz for draggable nodes, Stripe's press-page card enlarge for the click interaction) and the instruction "I DON'T WANT BLACK." The new committed personality: an instrument that happens to be light and colorful rather than dark — still precise and evidence-driven, not a toy, but each pipeline group now carries its own identity color (echoing the reference) instead of a single amber accent.

**Revision (2026-08-28, v3 — current):** the v2 3D WebGL scene was itself discarded in favor of an exact recreation of a supplied high-fidelity design handoff (`design_handoff_workflow_observer/`) — a plain DOM/SVG canvas, not 3D. The five-lane colorful-card personality and "light, not dark" commitment from v2 carry forward unchanged; what changed is the execution (draggable 2D cards instead of a WebGL scene, a Stripe-style FLIP-morph inspector instead of a docked panel, a literal Run Workflow simulation). DESIGN.md is the current source of truth for the visual system; treat every paragraph above as historical rationale, not a standing spec.

## Anti-references

*(Partially superseded 2026-08-28.)* Not a game HUD — no arbitrary sci-fi chrome that doesn't map to a real system value. Not cluttered dashboard-software default (dense card grids, tiny uppercase eyebrows over every section). Every visual element must trace back to something the system actually did. **No longer in force:** "no floating glassmorphic cards," "no gradient/dark SaaS look," and "drop-shadow-on-everything" — the committed world is now explicitly a light, card-based, colorful system with real drop shadows (see DESIGN.md), chosen deliberately over the original dark instrument-panel anti-references above.

## Design Principles

1. **Superseded 2026-08-28 (v3) — see DESIGN.md.** ~~Show the whole system, then the one true stage. Two deliberate camera states only — full-pipeline overview and single-stage focus — connected by one continuous, interruptible transition.~~ There is no camera or focus mode in the v3 plain-DOM/SVG canvas; the pipeline is always fully visible (pan/zoom to navigate) and a clicked node morphs into an inspector overlay instead of the view refocusing.
2. **Motion is evidence, not decoration.** A node moves, glows, or pulses only because a real status changed or is currently running. Idle nodes are still. (Still true in v3: the run-state glow, the comet tracker, and the FLIP morph all fire only on a real state change or a real click — nothing animates ambiently except the identical dot-grid background.)
3. **Superseded 2026-08-28 (v2) — see DESIGN.md.** ~~One accent carries all signal. Amber/phosphor means "active or meaningful right now"; everything else is calm neutral. Never introduce a second decorative color.~~ Replaced by a five-color lane-identity system carried through to v3 unchanged: each pipeline lane (Data/Research/Code & Safety/Train & Score/Decide & Package) owns one gradient color and badge shape; status (waiting/running/succeeded) is a separate, independent signal (dot + text color), never a change to the lane's own color.
4. **Real data or nothing.** Every number and label shown comes from the same ledger/event contract as the rest of the observer — no placeholder telemetry beyond the explicitly labeled "Interface demo data."
5. **Precision survives spectacle.** However dynamic the canvas gets (pan, zoom, drag, the run simulation, the FLIP morph), exact status, timestamps, and plain-language summaries stay legible — this is an instrument, and instruments must be readable at a glance.

## Operating Context

Built for TikTok TechJam 2026 Track #2 ("Autonomous Machine Learning Research Agent for Recommender Systems"), scored against KuaiRand-Pure (required) and AliCCP (optional bonus, never at KuaiRand's expense). The observer runs against a local, single-machine deployment (loopback-only; not intended for network exposure without added auth/TLS) — a FastAPI backend (`src/flowstate/api/server.py`) streams session/event/artifact data over REST + Server-Sent Events to the web UI. The pipeline itself is a LangGraph state machine driving two Bedrock-backed LangChain agents (Research/Scientist and Coder) through data prep → baseline reproduction → research (aided by a local Research Knowledge MCP seeded from `data/research/curated_papers.json`) → code change → train/score → decide → package, with every step recorded to an append-only SQLite ledger that is the UI's sole source of truth. Judging weighs Technical Execution (35%), Innovation & Problem Insight (20%), Impact & Relevance (20%), Feasibility & Practicality (15%), and Presentation & Communication (10%) — the last of which the Observer UI directly serves as the live/replay demo surface judges watch.

## Capabilities and Constraints

- **MUST NOT** use external training data, hidden-test labels, or a self-built baseline in place of the organizer's official FM baseline; the organizer's `evaluate.py` is the sole source of truth for metrics (GAUC, nDCG@5, primary = mean of the two).
- **MUST** log every experiment (hypothesis, real code diff, commands, metrics, resources, decision) and every recovery event, including failures and rejected experiments — the ledger is append-only and history is never rewritten.
- **MUST** treat the validation-best artifact at organizer-defined convergence as final; final hidden-test evaluation happens once and is irreversible.
- The UI has observer-plus-safe-control authority only: it can start/pause/resume/cancel a run and trigger final packaging, but cannot edit graph topology, evaluator logic, split rules, or run history. On any conflict the server/kernel state wins and the UI refreshes from the authoritative snapshot.
- Redaction (hiding secrets, raw dataset rows, checkpoints, and sealed test labels) is enforced server-side; the UI must never be the only thing hiding protected content.
- Resource usage (LLM input/output tokens, GPU-hours, wall-clock, manual interventions) is tracked from the first agent action and must be visible, not just the metric score.
- Undecided/organizer-controlled facts (baseline scores, $\varepsilon$, $N$, compute/token budgets, submission schema) are loaded at runtime from organizer-provided config/scripts, never hard-coded or duplicated as frontend constants.

## Evidence on Hand

- `AGENTS.md` — the full competition rules, constraints, scoring model, research-loop phases, logging/artifact contract, and communication style rules that this build must satisfy.
- `Plan_Workflow.md`, `Plan_UI.md`, `Plan_MCP.md` — the three implementation plans (backend/orchestration, frontend/observer, research-knowledge MCP) referenced by the most recent commit ("Implemented the three plans").
- `kuairand-starter-kit/` — the organizer's official starter kit: `evaluate.py` (evaluator), `baseline.py` (official FM/popularity/random baselines), `data.py` (deterministic loader/splits), `baseline_scores.json` (baseline scores and convergence thresholds), `submit.py` (submission validator).
- `data/research/curated_papers.json` — the human-curated seed set of research papers for the Research Knowledge MCP.
- `docs/architecture/` — Architecture v2/v3 documents and diagrams that the UI plan cites for component responsibilities and plain-language labels.
- No visual implementation currently exists on disk: a full React/Vite Workflow Observer frontend (`ui/`, ~74 files: 3D scene, workflow canvas, inspector, routes) was committed at `54b6c51` but has since been deleted from the working tree, uncommitted, as a deliberate decision to rebuild rather than an accident. Treat this as no incumbent visual implementation; do not assume its prior component structure is binding.

## Product Principles

1. **Reproduction gates improvement.** No result counts as an improvement until the official FM baseline is reproduced and every comparison is made against it, not against an intermediate or self-built stand-in.
2. **Evidence and auditability over narration.** A change is only real once it exists as a code diff run through the official evaluator with a logged result; the UI's job is to make that evidence legible, not to represent intentions as outcomes.
3. **Autonomy is a measured property, not a slogan.** Manual interventions are counted and shown, not hidden; the target is zero required human intervention, and every deviation from that is a fact the system reports on itself.
4. **Convergence, not peak.** The system (and the UI) always represents the validation-best artifact at the organizer's convergence rule as the result that matters, never a transient high score.
5. **Resource cost is part of the result.** LLM tokens and GPU-hours are first-class, continuously visible facts alongside the metric score, not a footnote.

## Accessibility & Inclusion

Reduced motion is mandatory, not optional: `prefers-reduced-motion` disables the run-state pulse/glow, the comet tracker, and the FLIP-morph transition (the inspector opens/closes instantly at its final state instead) in favor of a static, immediate readout. The narrow-screen list fallback (grouped by lane, same live status) is not WebGL-gated in v3 — there is no WebGL/3D surface any more — but remains the committed narrow-viewport path. Keyboard operability is a v3 addition beyond the supplied design handoff, not carried over from it: every node card is a real, focusable DOM element (`tabIndex`, `role="button"`, Enter/Space opens the inspector, Escape closes it, a visible focus ring) — this must be preserved in any future revision, since the handoff itself specifies pointer-only interaction.
