# Plan_UI.md — FlowState Workflow Observer

## Context
Build a local, single-machine web app that shows the FlowState run as a live, n8n-style workflow without turning the competition pipeline into an editable diagram. Users can start, pause, resume, and cancel a run through guarded controls; the CLI and integrity kernel remain authoritative. Selecting any engine, agent, or safety gate opens its current input, output, artifacts, timing, and past attempts. The Data Profiler owns preprocessing and visualization, so its node must expose the fitted train-only transform receipt and human-readable data charts as first-class output.

No UI scaffold currently exists: the repository has no `package.json`, `ui/`, `web/`, or frontend source tree. Create the UI under `ui/`; do not place frontend dependencies in the Python package.

## Approach

### 1. Establish the frontend and observer API contract
1. Create a Vite React TypeScript application in `ui/` using:
   - React for rendering.
   - `@xyflow/react` for the workflow canvas, pan/zoom, minimap, node selection, and keyboard navigation.
   - `motion` for interruptible spring transitions.
   - TanStack Query for snapshots, artifact metadata, and control mutations.
   - Apache ECharts, imported from `echarts/core`, for profiler and resource charts.
   - Radix UI primitives only for accessible dialogs, tabs, tooltips, and popovers; style them with CSS Modules and shared CSS variables instead of a theme kit.
   - Lucide icons with text labels; icons never carry meaning alone.
   - Vitest + React Testing Library for interaction contracts and Playwright for the live/replay smoke path.
2. Pin all resolved dependencies in `ui/pnpm-lock.yaml`; use Node.js 22 LTS and pnpm. All libraries and the local runtime are free and open source.
3. Add a typed client in `ui/src/api/` for these backend endpoints; the workflow plan implements them:
   - `GET /api/v1/sessions` — recent live and replayable sessions.
   - `GET /api/v1/sessions/{session_id}/snapshot` — graph, current state, metrics, budgets, and finalization state.
   - `GET /api/v1/sessions/{session_id}/events?after_sequence={n}` — ordered Server-Sent Events; reconnect with the last applied sequence and ignore duplicates.
   - `GET /api/v1/sessions/{session_id}/components/{component_id}/executions/{execution_id}` — redacted input/output summary, timestamps, status, attempt number, and artifact references.
   - `GET /api/v1/artifacts/{artifact_id}` — metadata or safe text/JSON content; never return checkpoints, raw datasets, secrets, validation labels, or sealed test labels.
   - `POST /api/v1/sessions` with `{challenge_config_path, budget_config_path}` — start after server-side validation.
   - `POST /api/v1/sessions/{session_id}/pause`, `/resume`, and `/cancel` — guarded state transitions; invalid transitions return `409` with a plain-language reason.
   - `POST /api/v1/sessions/{session_id}/package` with `{confirmation: session_id}` — build the final package only after convergence/budget stop and explicit confirmation; it does not submit to a hidden endpoint.
4. Generate TypeScript API types from the backend OpenAPI document during development and commit the generated file. The browser must not define a second status vocabulary or metric schema.
5. Use SSE rather than WebSockets: all updates are server-to-browser, reconnect semantics are simpler, and the local SQLite event sequence provides deterministic replay.

### 2. Build the workflow canvas around the actual architecture
1. Define one node registry in `ui/src/workflow/nodeRegistry.ts` with stable IDs and human-facing labels:
   - `train_data` — Training Data
   - `data_profiler` — Inspect & Prepare Data
   - `phase_guard` — Check Data Safety
   - `knowledge_mcp` — Find Research Evidence
   - `scientist` — Choose the Next Experiment
   - `coder` — Write the Code Change
   - `pruner` — Run Fast Safety Tests
   - `trainer` — Train the Model
   - `recovery` — Recover from Failures
   - `evaluator` — Score on Validation
   - `watchdog` — Decide: Continue or Stop
   - `ledger` — Save Run Evidence
   - `finalizer` — Build Final Package
   - `submission` — Verified Predictions
2. Preserve architecture terms as secondary labels in the inspector—such as “Research Agent” or “Official Evaluator”—while the primary canvas labels explain what each component does. Do not use invented labels such as “AI brain,” “magic,” or “autonomous intelligence.”
3. Lay out the graph left-to-right in five readable groups: Data → Research → Code & Safety → Train & Score → Decide & Package. Recovery sits beside training and reconnects to the last stable parent. The layout is fixed by default so users read the true workflow; users may pan, zoom, fit-to-view, and temporarily move nodes, but moved positions are session-local UI preferences and never alter execution order.
4. Model states exactly as `waiting | ready | running | paused | succeeded | failed | rejected | skipped | blocked`. Use shape, icon, text, and color together:
   - running: blue status dot plus elapsed time;
   - succeeded: green check;
   - failed/blocked: red error icon and short reason;
   - rejected: amber minus and “Experiment rejected”;
   - paused/waiting/skipped: neutral gray variants.
   Do not use glow, neon, animated backgrounds, or endlessly pulsing nodes.
5. When an event changes a node, animate only that state transition. Keep graph interaction live during all animation; never disable selection while the inspector opens or closes.

### 3. Make every component inspectable
1. Selecting a node opens a right-side inspector anchored to the selected node. It has four tabs:
   - **Summary**: what the component is doing, status, start/end time, attempt, and plain-language result.
   - **Input**: redacted structured inputs and source artifact links.
   - **Output**: structured result, metrics, decision, error/recovery result, and output artifacts.
   - **History**: every execution attempt for that component in sequence order.
2. Put plain-language fields first. Place hashes, exact commands, model/config IDs, raw JSON, and traceback details under a collapsed `Implementation details` section.
3. Render artifact types deliberately: JSON as labeled fields with optional raw view, text logs in a searchable monospace viewer, patches as unified diffs, charts through the profiler view, and binary/checkpoint artifacts as metadata plus checksum only.
4. Apply redaction on the backend and display a fixed explanation—`Hidden to protect data and credentials`—when content is withheld. Never depend on CSS or client code to hide secrets or protected labels.
5. Add keyboard behavior: Tab reaches every node and control, Enter/Space selects, Escape closes the inspector, `F` fits the graph, and arrow keys move focus through connected nodes. Restore focus to the originating node when the inspector closes.

### 4. Add Data Profiler preprocessing and visualization as visible outputs
1. Treat the Data Profiler as one deterministic component with two responsibilities:
   - **Inspect** raw and transformed data and produce bounded aggregate diagnostics.
   - **Prepare** data by fitting approved vocabularies, bucket edges, imputers, scalers, and feature statistics on training data only, then applying the frozen artifact to validation/test features without refitting.
2. Add a dedicated **Data Profile** route backed by the profiler’s `profile.json`, `visualization.json`, and `transform_receipt.json` artifacts. It must show:
   - split row counts and `long_view` prevalence;
   - users with zero, all, or mixed positive labels;
   - interactions per user and sequence-length distribution;
   - missing/malformed values by field;
   - feature cardinality and unseen-ID rates;
   - `play_time_ms` versus `duration_ms` censoring summary;
   - daily/hourly volume and label-rate drift between train and validation;
   - duplicate user/video exposure rate;
   - transform lineage: source hash → fitted transform hash → materialized artifact hash.
3. Use pre-aggregated bins and counts from the profiler. The browser never downloads raw interaction rows. Empty charts render `No data was produced for this check`; failed profiler output renders the recorded failure and links to the safe log.
4. Use accessible chart defaults: visible axes and units, color-blind-safe series, tooltips duplicated in a keyboard-readable data table, no 3D charts, no decorative animation, and `prefers-reduced-motion` disables chart interpolation.
5. Let a click on any profiler chart filter only that page’s supporting table; it must not modify the experiment or training data.

### 5. Add run-level views needed for the complete workflow
1. Implement six top-level destinations with direct labels:
   - **Live Workflow** — graph, current experiment, latest decision, and controls.
   - **Data Profile** — profiler charts and frozen preprocessing receipt.
   - **Experiments** — baseline, current best, stable fallback, pending, rejected, and failed runs; compare GAUC, nDCG@5, and primary score against parent and official FM baseline.
   - **Research Library** — MCP evidence cards, curated/auto-ingested source marker, citations, license, retrieval time, and pinned code links.
   - **Resources** — per-run and cumulative Bedrock input/output tokens, GPU-hours, wall time, peak memory, retries, and manual interventions.
   - **Final Package** — validation-best receipt, clean replay status, prediction schema check, manifest hashes, and explicit one-way boundary.
2. Add an autonomy timeline below the canvas. Each row shows timestamp, component, action, outcome, and duration. Selecting a row selects the corresponding node and execution attempt.
3. Add replay mode that reads the same ordered event records as a live run. Controls are Play/Pause, previous/next event, and playback speed `0.5× | 1× | 2× | 4×`. Replay is visually marked and cannot expose start/pause/cancel/package mutations.
4. Start/pause/resume/cancel buttons are shown only when the snapshot’s `allowed_actions` includes them. Cancel requires a concise confirmation stating that history is preserved and the stable fallback remains. Package requires typing the session ID because it freezes the research frontier; ordinary run controls do not require confirmation dialogs.

### 6. Apply the Apple-style visual and motion system with restraint
1. Use the platform system font stack with optical sizing. Body text uses comfortable leading; large screen titles use `letter-spacing: -0.02em` and tighter leading. All spacing uses rem-based tokens so browser text scaling does not break layouts.
2. Use a calm neutral palette with one blue action color and restrained semantic green/amber/red. Support light and dark themes from `prefers-color-scheme`; do not use gradients, glowing borders, oversized hero copy, floating marketing cards, or decorative AI imagery.
3. Use translucency only for the top toolbar and the non-modal inspector over scrolling content. Do not stack translucent cards. Under `prefers-reduced-transparency`, replace blur with an opaque surface and a clear border; under `prefers-contrast: more`, increase contrast and surface separation.
4. Use Motion springs that start from the current on-screen value:
   - ordinary inspector/node reposition: no bounce, approximately `0.32–0.4s` response;
   - draggable canvas movement: direct 1:1 pointer tracking with no scripted bounce;
   - momentum is not needed for workflow nodes because their movement has no product meaning.
   Inspector entry and exit follow the same right-edge path. Reduced motion replaces movement with a short opacity cross-fade.
5. Give immediate pointer-down feedback with a small `0.98` scale on buttons, preserve a minimum 44×44 CSS-pixel hit target for primary controls, and never delay actions for decorative motion.
6. Keep the app desktop-first for the workflow canvas. At tablet widths, collapse navigation to an icon-plus-label drawer. On narrow mobile widths, replace the canvas with the ordered component list and open the inspector as a bottom sheet; all information remains available, but starting/packaging runs stays disabled on narrow screens to avoid accidental actions.

### 7. Serve the UI locally and preserve offline demo behavior
1. During development, Vite proxies `/api` to FastAPI. For packaged local use, build static assets into `ui/dist`; FastAPI serves them with SPA fallback after API routes.
2. Show an explicit connection banner on SSE loss while preserving the last verified snapshot. Reconnect with `Last-Event-ID`; if the server reports a sequence gap, discard client state and reload the authoritative snapshot before applying new events.
3. Bundle one small, redacted replay fixture derived from real ledger event shapes—not fabricated competition metrics—so the interface can be exercised without a long training run. Label it `Interface demo data`; do not present it as a completed experiment.

## Critical files & anchors
- `docs/architecture/ARCHITECTURE_v3_kuairand.md` — Layer 3 responsibilities and complete 11-step flow; v3 metric names override older UI text.
- `docs/architecture/diagrams/ARCHITECTURE_v3_simplified_plain_english.svg` — Data Profiler output, node responsibilities, and plain-language labels around lines 356–390 and 449–579.
- `docs/architecture/ARCHITECTURE_v2_kuairand.md` — observer requirements around lines 1140–1164 and profiler/report-renderer ownership around lines 368–386; replace its obsolete NDCG@10/Recall@50 text with v3 GAUC/nDCG@5.
- `kuairand-starter-kit/evaluate.py` — authoritative GAUC, nDCG@5, primary score, and within-user evaluation behavior.
- `kuairand-starter-kit/baseline_scores.json` — source for baseline/convergence values displayed by the UI; never duplicate those values in frontend constants.

## Verification
1. From the repository root, start the FastAPI observer in fixture mode and run `pnpm --dir ui dev`. Open the actual browser surface at desktop, tablet, and mobile widths.
2. Live-path check: start a smoke session in the UI; expect the graph to advance in server event order, the active node to show elapsed time, and node selection to show its redacted input/output without reloading.
3. Control check: pause a pausable smoke run, verify no new execution stages start, resume it, then cancel another run; expect a preserved failed/cancelled ledger event and no history deletion. Send a disallowed transition directly and expect HTTP `409` plus a readable UI message.
4. Profiler check: load a small deterministic KuaiRand fixture. Expect all listed charts, a train-only transform receipt, and no raw rows in browser network responses. Change only an upstream transform hash and verify the profiler refreshes; unchanged inputs must reuse the prior profile artifact.
5. Replay check: disconnect the live stream, reconnect with the last event ID, and verify no duplicate timeline rows. Replay the same session at `1×`; the final snapshot must match the live session snapshot.
6. Accessibility check: operate navigation, graph/list, inspector, chart tables, and controls using keyboard only; run axe on all six destinations with zero serious/critical violations. Verify browser zoom at 200%, reduced motion, reduced transparency, high contrast, light, and dark modes.
7. Visual check: inspect the real rendered UI for restrained materials, readable hierarchy, no neon/glow, no clipped labels, symmetric inspector motion, and immediate press feedback. Capture desktop and mobile screenshots for comparison during implementation.
8. Run `pnpm --dir ui test` and the focused Playwright live/replay flow after browser verification; tests must assert event ordering, allowed-action controls, redaction, profiler empty/error states, and metric labels `GAUC`, `nDCG@5`, and `primary`.

## Required from the project owner
- No paid UI hosting, analytics account, icon license, font license, or design service is required.
- Provide the desired project name/logo asset only if branding beyond `FlowState` is wanted; otherwise use text branding and Lucide icons.
- Provide no dataset rows or secrets to the frontend. The workflow configuration supplies local dataset paths to the backend.

## Assumptions & contingencies
- The app is a local single-operator dashboard. If a network-accessible deployment is later required, add authentication and TLS before binding beyond loopback; do not expose this build directly.
- The UI has observer plus safe-control authority, but cannot edit graph topology, evaluator logic, split rules, or run history. If a control conflicts with kernel state, the server decision wins and the UI refreshes its snapshot.
- If ECharts cannot render in the target browser, retain the same `visualization.json` contract and show the accessible tables; charts are an enhancement, while the aggregate values remain authoritative.

