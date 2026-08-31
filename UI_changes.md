
# FlowState UI redesign and workflow-observer implementation brief

Work directly in the existing repository:

`Dheemant19/TikTok-TechJam_RGB`

The frontend is under `ui/` and is a React + TypeScript + Vite application using Zustand. The workflow canvas is implemented with regular DOM elements plus SVG edges, not React Flow or a canvas renderer.

Before modifying anything, inspect:

- `AGENTS.md`
- `Plan_UI.md`
- `Plan_Workflow.md`
- `DESIGN.md`
- `docs/STRIPE_STYLE_STAGE_FOCUS_PROMPT.md`
- `ui/src/data/nodeRegistry.ts`
- `ui/src/liveworkflow/LiveWorkflowCanvas.tsx`
- `ui/src/liveworkflow/EdgesLayer.tsx`
- `ui/src/liveworkflow/edgeMath.ts`
- `ui/src/liveworkflow/NodeCard.tsx`
- `ui/src/liveworkflow/StageFocusView.tsx`
- `ui/src/liveworkflow/StageDetailScroller.tsx`
- `ui/src/liveworkflow/FocusArchitecturePane.tsx`
- `ui/src/liveworkflow/useFlipInspector.ts`
- `ui/src/liveworkflow/stageNavigation.ts`
- `ui/src/liveworkflow/eventMapping.ts`
- `ui/src/liveworkflow/runStore.ts`
- `ui/src/liveworkflow/selectors.ts`
- `ui/src/liveworkflow/nodeDetail.ts`
- `ui/src/components/TopToolbar.tsx`
- `ui/src/routes/AutonomyLog.tsx`
- `ui/src/styles/base.css`
- `ui/src/styles/tokens.css`
- `ui/src/styles/experience.css`
- `ui/index.html`
- `ui/package.json`

Also inspect the backend event sources:

- `src/rigor_rs/orchestration/graph.py`
- `src/rigor_rs/contract/models.py`
- `src/rigor_rs/training/execution.py`

## Non-negotiable constraints

1. Do not change workflow execution behavior.
2. Do not alter the backend LangGraph workflow, experiment order, evaluator, training logic, recovery logic, API contract, SSE behavior, ledger history, or database semantics.
3. The new `initial_baseline` and `proxy_gate` identifiers are UI-level presentation nodes only. Do not send them to the backend or add them to the backend `COMPONENT_IDS` unless the existing API already supports them.
4. Preserve all existing controls:

   - Start Run
   - Pause
   - Resume
   - Cancel
   - Package
   - Session selection
   - SSE reconnection
   - Replay/history behavior
   - Redaction behavior
5. Do not fabricate metrics, events, timestamps, artifacts, or execution results. Use only actual backend events, snapshots, and payloads.
6. Preserve the current real DOM node cards. Do not replace them with SVG-only or canvas-only nodes because keyboard focus and screen-reader behavior must continue working.
7. Preserve reduced-motion behavior. All new animations must become static or instant when `prefers-reduced-motion: reduce` is enabled.
8. Preserve responsive behavior:

   - Desktop/tablet: workflow canvas.
   - Narrow screens: existing ordered stage-list fallback.
   - Stage detail view may use a compact horizontal navigation fallback on very narrow screens if a vertical rail would clip content.

## Current architecture to preserve

The current canvas uses:

- `NODES` and `RUN_ORDER` in `ui/src/data/nodeRegistry.ts`
- `NodeCard` for interactive DOM cards
- `EdgesLayer` for SVG connections
- `LiveWorkflowCanvas` for pan, zoom, dragging, and centering
- `useFlipInspector` for opening, closing, and navigating stage details
- `StageFocusView` for the full-screen stage view
- `StageDetailScroller` for Summary/Input/Output/History sections
- `runStore.ts` for sessions, SSE events, statuses, elapsed timers, and controls
- `eventMapping.ts` for converting backend event IDs into UI node state
- `experience.css` and `tokens.css` for visual styling

The existing FLIP-style opening animation is already present. Improve and extend it rather than creating a second inspector implementation.

# 1. Add the new workflow cards and correct event mapping

## New UI node: Compute Initial Baseline

Add this node to the Data group:

- ID: `initial_baseline`
- Label: `Compute Initial Baseline`
- Architecture label: `Baseline Reproducer`
- Group: `data`
- Monogram: `BL`

This card represents the official FM baseline computation only. It must be visually and logically separate from `Train the Model`.

The current backend emits baseline events using:

- `component_id: "trainer"`
- `stage: "baseline"`
- `event_type: "started"`, `"completed"`, or `"failed"`

Map those events to `initial_baseline`.

The actual `trainer` card must represent experiment training only, not baseline computation.

If a baseline safety failure is represented by a later `phase_guard` event without an explicit baseline terminal event, infer that the baseline presentation card is no longer actively running, but do not create a fake event. Use an appropriate failed or blocked presentation state based on the real event payload.

Add a live-detail entry in `laneData.ts` and a builder in `nodeDetail.ts`. Show only values present in the actual baseline payload, such as:

- Number of baseline seeds
- GAUC
- nDCG@5
- Primary score
- Baseline receipt/output status

Never invent baseline values.

## New UI node: Proxy Gate

Add a separate node under the Code & Safety group:

- ID: `proxy_gate`
- Label: `Proxy Gate`
- Architecture label: `Filter-Only Proxy`
- Group: `code`
- Monogram: `PG`

This must be separate from `Check Data Safety`.

The current backend uses several event sources for proxy-related execution:

- `trainer` + `stage: "execute"` + `event_type: "tier2"` or `"tier3"`
- `phase_guard` + `stage: "execute"` + events such as `inert_patch` or proxy-related failures

Map proxy-related events to `proxy_gate`.

Keep these mappings separate:

- `phase_guard` + `stage: "baseline"` → `phase_guard` / Check Data Safety
- `phase_guard` + `stage: "execute"` → `proxy_gate`
- `trainer` + `stage: "baseline"` → `initial_baseline`
- `trainer` + `stage: "execute"` + `tier1` → `pruner`
- `trainer` + `stage: "execute"` + `tier2`/`tier3` → `proxy_gate`
- `trainer` + `stage: "execute"` + `tier4` → `trainer`
- `trainer` resource events → `trainer`

A proxy failure must never set the Data group `phase_guard` card to `Blocked`.

The Check Data Safety card may become `Blocked` only because of an actual data/baseline safety-gate event, such as `integrity_halt`.

The Proxy Gate detail view must clearly state that proxy scores are filter-only and non-comparable. Proxy metrics must never update official GAUC, nDCG@5, primary-score, or convergence displays.

## Visible workflow topology

Update the UI graph to display this route:

`Training Data`
→ `Inspect & Prepare Data`
→ `Check Data Safety`
→ `Compute Initial Baseline`
→ `Find Research Evidence`
→ `Choose the Next Experiment`
→ `Write the Code Change`
→ `Run Fast Safety Tests`
→ `Proxy Gate`
→ `Train the Model`
→ `Score on Validation`
→ `Decide: Continue or Stop`
→ `Save Run Evidence`
→ `Build Final Package`
→ `Verified Predictions`

Keep the existing static dashed recovery connection:

`Train the Model` → `Recover from Failures`

Keep recovery navigation compatible with the existing recovery behavior.

Add a loop connection:

`Decide: Continue or Stop` → `Find Research Evidence`

This is a visual loop edge only and must not modify backend routing.

Update:

- `NODES`
- `RUN_ORDER`
- `EDGES`
- `TOTAL_STAGES`
- `nextStageId`
- node-detail definitions
- stage labels
- architecture readouts

Do not leave hard-coded text such as `13 nodes / 12 links`. Derive node and edge counts from the actual arrays.

# 2. Make Summary/Input/Output/History a vertical navigation rail

The current `StageFocusView` renders the four detail sections as non-clickable spans in the header. Replace that behavior.

The four sections must remain:

- Summary
- Input
- Output
- History

## Desktop layout

In the full-screen stage view:

- Keep the architecture pane on the left.
- Keep the detail content on the right.
- Add a narrow vertical navigation rail on the far right of the detail pane.
- The detail content itself remains scrollable.
- The navigation rail remains visible while the detail content scrolls.
- Use a Google Docs-style vertical navigation treatment:
  - subtle border
  - compact stacked items
  - active accent indicator
  - readable labels
  - lane-colored active state
  - no excessive decoration

Suggested structure:

`stage-focus__details-layer`
→ `stage-focus__details-column`
→ `StageDetailScroller` + `stage-focus__section-nav`

The rail must not cover the scrollable content. Reserve explicit width for it and add enough right padding to the detail scroller.

## Click behavior

Every section label must be a real clickable button.

Clicking a section:

- scrolls the existing `StageDetailScroller` to the correct section
- uses smooth scrolling unless reduced motion is enabled
- updates the active visual state
- updates `aria-current` or equivalent accessible state
- does not change the data or workflow state

Refactor `StageDetailScroller` with a `forwardRef`/imperative handle or an equivalent controlled callback so that `StageFocusView` can request:

- `scrollToSection("summary")`
- `scrollToSection("input")`
- `scrollToSection("output")`
- `scrollToSection("history")`

Continue using the existing `IntersectionObserver` to update which section is active while the user scrolls manually.

## Arrows on both sides of every tab

Each navigation item must have this layout:

`[previous arrow] [section label] [next arrow]`

Use compact double-chevron-style affordances:

- `«` or a double-left-chevron icon for the previous section
- `»` or a double-right-chevron icon for the next section

Behavior:

- Previous arrow moves to the previous detail section.
- Next arrow moves to the next detail section.
- Clicking the label scrolls directly to that section.
- The first section has a disabled previous arrow.
- The last section has a disabled next arrow.
- The arrows must have accessible labels such as:
  - `Previous section: Summary`
  - `Next section: Input`
- Every arrow must have at least a 44×44 CSS-pixel hit area, even if the visual icon is small.
- Do not use arrow clicks to navigate between process cards; these arrows are only for the four detail sections.

Keyboard behavior:

- Tab reaches every section button and arrow.
- Enter and Space activate them.
- Arrow Up/Down moves through the section list.
- Home moves to Summary.
- End moves to History.
- Escape still closes the stage view.

During a process-card transition, temporarily disable section navigation only if necessary to avoid a scroll race. Re-enable it when the incoming detail view is open.

# 3. Make process-card opening and navigation more seamless

Improve the existing FLIP transition in:

- `useFlipInspector.ts`
- `StageFocusView.tsx`
- `experience.css`

Requirements:

1. Capture the clicked card’s viewport `DOMRect`.
2. Keep the overlay mounted throughout opening and closing.
3. Morph from the exact source card position into the full-screen detail surface.
4. Preserve continuity of:
   - position
   - size
   - border radius
   - lane accent
   - depth/shadow
   - selected card identity
5. Do not abruptly remove the source card before the morph begins.
6. Do not show a white or transparent flash between the canvas and detail view.
7. Closing must reverse the same path back into the originating card.
8. Stage-to-stage navigation must retain the existing two-scene transition:
   - outgoing stage exits
   - incoming stage enters
   - detail content changes at the same visual rhythm
9. Keep focus restoration to the originating card.
10. Reduced motion must use an immediate or short opacity transition with no spatial morph.

The current canvas may be transformed through pan/zoom. Ensure the captured viewport rectangle remains correct even when the card is inside the transformed workflow world.

# 4. Improve idle and active workflow-edge animation

The current `EdgesLayer` marks edges active using accumulated status conditions such as:

`from succeeded && target running/succeeded`

Replace that logic.

## Idle edges

Idle arrows must be visibly thicker and easier to read.

Recommended minimum visual treatment:

- Increase idle line stroke width from the current thin value to approximately 2.4–2.8.
- Increase idle opacity to approximately 0.78–0.9.
- Increase the underlying contrast bed slightly so paths remain readable over the canvas.
- Increase arrow opacity and visual size modestly.
- Keep the existing restrained dashed-flow animation.
- Preserve the recovery edge as a static dashed edge.

Do not make every edge glow continuously.

## Dark mode

Add an explicit dark-theme override.

In dark mode:

- Idle edge lines must be brighter.
- Idle arrows must be thicker and more opaque.
- The arrow must remain visually distinct from the dark canvas.
- Use the existing lane colors and flow tokens; do not introduce unrelated neon colors.
- Make sure the port outlines remain visible against `--surface-1`.

## Exactly one highlighted transition edge

At any point, only one edge may be highlighted as the current transition.

Do not leave all historical completed edges highlighted.

Create a transient UI-only transition state, for example:

- `activeTransitionEdge`
- `transitionStartedAt`
- `transitionToken`

The state may live in Zustand or in a shared edge-transition hook, but it must be shared by:

- the main workflow canvas
- the architecture pane inside the stage-focus view

The active transition should:

1. Start when the workflow visibly moves from one process card to another.
2. Highlight only the relevant edge.
3. Use the active flow gradient.
4. Increase stroke width.
5. Add a restrained glow using `--flow-glow`.
6. Show one bright glowing dot traveling from source to target.
7. Use a smooth eased animation starting at the source, not a modulo calculation based on elapsed node time.
8. Finish after approximately 0.9–1.3 seconds.
9. Return the edge automatically to the idle animation state.
10. Leave the running card’s 3D animation active after the edge returns to idle.

Implement the moving dot with a dedicated animation clock, preferably `requestAnimationFrame` or an equivalent deterministic progress value. Do not use the current `nodeElapsed % loopMs` approach for the one-shot transition because it can begin halfway along the path and appear discontinuous.

A short fading tail may be used, but there must be one clear particle head rather than multiple unrelated glowing dots.

For reduced motion:

- Do not animate the dot.
- Show a static active edge briefly or use a high-contrast state.
- Return to idle without movement.

## Edge transition detection

Use meaningful state changes and graph topology.

Do not activate an edge for:

- snapshot polling
- duplicate SSE events
- pause/resume control events
- unchanged status updates
- historical states replayed without a new visual transition

Do not derive activity from “all previous nodes succeeded.”

# 5. Add the rejected-decision loop edge

The `Decide: Continue or Stop` card is `watchdog`.

When the watchdog event payload indicates a rejected decision, usually:

`payload.decision === "reject"`

activate the loop edge:

`watchdog → knowledge_mcp`

Requirements:

- Render the edge as a distinct curved backward loop.
- Avoid drawing it directly through other cards.
- Use a separate loop path in `edgeMath.ts`, preferably routed above or below the main lanes.
- Use the active transition style only while the loop is executing.
- Then return it to idle.
- Do not mark the loop edge active for `retain`, `ambiguous`, or terminal stop decisions.
- Do not change the backend decision or routing.

The stage-detail “Continue to” control must also be branch-aware. When the current watchdog decision is rejected, it should point to `Find Research Evidence`, not `Save Run Evidence`.

# 6. Reset statuses for every new experiment

The current reducer retains the latest status for every card across the entire session. That causes old experiment cards to remain marked Succeeded, Failed, Ready, or Blocked while a new experiment begins.

Implement an experiment-iteration status projection.

## Data group cards that must persist

Do not reset these cards when a new experiment begins:

- `train_data`
- `data_profiler`
- `phase_guard`
- `initial_baseline`

Their status should continue to represent the session-level data preparation, safety, and baseline state.

## Cards that must reset

When a new experiment/research cycle begins, reset the current status projection of all non-Data cards:

- `knowledge_mcp`
- `scientist`
- `coder`
- `pruner`
- `proxy_gate`
- `trainer`
- `recovery`
- `evaluator`
- `watchdog`
- `ledger`
- `finalizer`
- `submission`

Reset them to the appropriate initial state, normally `waiting`, before applying the new experiment’s events.

Use a new `knowledge_mcp` `started` event as the iteration boundary unless the backend exposes a more authoritative experiment boundary.

Important:

- Preserve every historical event in `state.events`.
- Preserve the History detail section.
- Preserve the Autonomy Log.
- Only reset the current visual status projection.
- Do not delete or rewrite ledger history.
- Reset stale elapsed timers for the iteration-scoped cards.
- Do not allow a proxy error from the previous experiment to leak into the new experiment.

Update `eventMapping.ts` so that:

- events are mapped to their correct UI node first
- iteration reset happens only on the current projection
- historical event arrays remain complete
- data-group states persist
- `phase_guard` does not receive proxy statuses
- `initial_baseline` and `proxy_gate` participate in the visible flow order

Update `runStore.ts` so stale elapsed values do not remain after an iteration reset.

# 7. Make the running card pop forward in 3D

The current `.workflow-node.is-running` mostly uses a glow animation. Add a clear but restrained 3D depth animation.

When a card has `status === "running"`:

- bring it visually forward with `translateZ`
- increase scale slightly, approximately 1.02–1.05
- raise its z-index above nearby cards
- increase its lane-colored depth shadow
- use a subtle ease-in/ease-out lift rather than a bouncing animation
- preserve the existing pointer tilt behavior
- preserve the card’s resting tilt
- do not interfere with dragging
- apply the effect in the main canvas and focus architecture pane

Use CSS variables or a transform composition so these states do not overwrite one another:

- hover tilt
- running lift
- selected/focus state
- dragging state

Dragging must take precedence over the running animation.

In reduced-motion mode:

- remove the animated lift
- use a static elevated shadow or minimal scale only

The lane identity color must remain unchanged. Status should still be communicated separately through the status text, dot, and running treatment.

# 8. Add a Recenter Workflow button

Add an accessible `Recenter workflow` button to the workflow canvas.

Place it near the existing zoom readout in the lower-right canvas controls.

Behavior:

- Calculate the current workflow content bounds using `contentBounds(positions)`.
- Calculate the canvas viewport bounds.
- Update `pan` so the workflow bounding box is centered in the viewport.
- Preserve the current zoom level.
- Do not modify node positions.
- Do not modify backend state.
- Do not reset the user’s zoom.
- Do not interfere with card dragging or canvas panning.

The button must include:

- visible target/crosshair-style icon
- text or tooltip
- accessible `aria-label`
- minimum 44×44 hit target
- immediate press feedback

Keep the existing initial centering behavior and add the button as a reusable function.

Also preserve the existing `F` keyboard shortcut if present in the design contract. It should recenter only when focus is not inside an input, select, textarea, button, or dialog.

# 9. Fix new-session selection in the run dropdown

The current `SessionPicker` is controlled by `sessionId`, but `startRun()` does not reliably refresh or insert the newly created session into `sessions`. This allows an older run to remain displayed as selected.

Fix this race.

When `api.startSession()` returns a new `session_id`:

1. Immediately make that returned ID the selected session.
2. Close or supersede any previous event stream safely.
3. Insert an optimistic session option into the local session list if the refreshed server list does not contain it yet.
4. Mark the optimistic option as `running`.
5. Attach to the new session.
6. Refresh the session list afterward.
7. Merge the refreshed list without dropping the currently selected new session if the server response is briefly stale.
8. Ensure the `<select value={sessionId}>` always has a matching option.

The dropdown should display the new option as:

`<new session_id> — running`

or the existing equivalent format.

It must never continue showing the previous run as selected after a new workflow starts.

If the session start fails:

- show the real error
- do not claim the new session started
- restore a consistent picker state

Add a regression test for the sequence:

`old session selected → click Start Run → new session returned → new session is selected and marked running`.

# 10. Add long-running stage updates to Autonomy Log

When any process card has remained in the `running` state for more than five minutes, inform the user in the Autonomy Log.

Threshold:

`300000 ms`

Use the existing `nodeStates`, `nodeElapsed`, `startedAt`, and latest event information.

The update must include:

- process-card name
- current stage or latest reported backend stage
- latest event type when available
- latest plain-language summary when available
- elapsed duration
- clear indication that the process is still running

Example wording:

`Still running after 5:00 — Train the Model is currently at execute / tier4: Full-scale training run.`

If a granular backend stage is unavailable, say:

`Train the Model is still running; no terminal event has been received.`

Do not guess a substage.

## Important event-integrity rule

Do not append a fake `RunEventDTO` to `events`.

These are UI-generated monitoring notices, not ledger events. Store them separately, for example:

- `longRunningNotices`
- `observerNotices`
- `monitoringRows`

Each notice should be keyed by:

`sessionId + nodeId + executionId or startedAt`

so the same five-minute alert is emitted only once for one execution.

The notice should:

- appear in `AutonomyLog.tsx`
- be visually distinct from ledger events
- be marked as an observer/monitoring update
- remain available as a useful record
- update its current status if the process later finishes
- not alter backend history
- not affect workflow routing or convergence

Update the timeline selector and row type to support both:

- real ledger event rows
- UI monitoring notice rows

Sort them chronologically.

The existing Autonomy Log must continue to show all actual SSE events in sequence.

# 11. Rename the product to FlowState

The website/product name must become:

`FlowState`

Replace the old product name in every user-facing location:

- top toolbar brand
- page title
- browser tab title
- accessible labels
- package display name
- design handoff text
- README and documentation branding
- comments describing the product
- HTML filenames containing the old brand
- UI storage keys
- visible error and empty states
- metadata and descriptions

Use:

- `FlowState`
- `FlowState Workflow Observer`
- `flowstate` for lowercase code identifiers where required

Perform a repository-wide case-insensitive audit of tracked files for the old variants:

- `RIGOR-RS`
- `rigor-rs`
- `rigor_rs`

Because the request explicitly requires the old naming to be removed from the codebase, perform a complete, tested namespace migration if those strings are implementation identifiers:

- rename `src/rigor_rs` to `src/flowstate`
- update all Python imports
- update `pyproject.toml`
- update Hatch package configuration
- update CLI entry points
- update MCP entry points
- update tests
- update scripts and configuration references
- regenerate the lock file instead of manually editing generated metadata
- update documentation and comments
- rename design files containing the old product name

This must be a namespace/branding migration only. Preserve:

- workflow behavior
- event component IDs such as `trainer`, `phase_guard`, and `watchdog`
- HTTP endpoint paths
- SSE schema
- database semantics
- artifact formats
- configuration behavior
- historical ledger data

Do not rename the remote GitHub repository unless explicitly asked.

After the migration, verify that no tracked source, documentation, package metadata, or UI asset still contains the old variants.

# 12. Accessibility and responsive requirements

Preserve and improve:

- keyboard navigation to every process card
- Enter/Space activation
- Escape to close stage details
- focus restoration
- visible focus rings
- screen-reader labels containing process name and current status
- accessible section navigation
- accessible previous/next arrows
- reduced motion
- readable contrast in light and dark modes
- minimum 44×44 hit areas for controls

Do not make the vertical section rail keyboard-inaccessible or mouse-only.

On narrow screens:

- preserve the existing ordered stage list fallback
- keep all four detail sections available
- use a compact horizontal section navigation only if the vertical rail cannot fit
- do not remove Summary/Input/Output/History
- do not expose broken or clipped arrows

# 13. Suggested file-level changes

Update these files where appropriate:

- `ui/src/data/nodeRegistry.ts`
- `ui/src/liveworkflow/eventMapping.ts`
- `ui/src/liveworkflow/laneData.ts`
- `ui/src/liveworkflow/nodeDetail.ts`
- `ui/src/liveworkflow/stageNavigation.ts`
- `ui/src/liveworkflow/StageDetailScroller.tsx`
- `ui/src/liveworkflow/StageFocusView.tsx`
- `ui/src/liveworkflow/FocusArchitecturePane.tsx`
- `ui/src/liveworkflow/LiveWorkflowCanvas.tsx`
- `ui/src/liveworkflow/EdgesLayer.tsx`
- `ui/src/liveworkflow/edgeMath.ts`
- `ui/src/liveworkflow/runStore.ts`
- `ui/src/liveworkflow/selectors.ts`
- `ui/src/components/TopToolbar.tsx`
- `ui/src/routes/AutonomyLog.tsx`
- `ui/src/styles/base.css`
- `ui/src/styles/tokens.css`
- `ui/src/styles/experience.css`
- `ui/index.html`
- `ui/package.json`
- `ui/package-lock.json`
- relevant repository-wide branding/package files

Do not introduce a new workflow-rendering library unless the existing implementation cannot support the requirements. The current DOM + SVG implementation is sufficient.

# 14. Validation checklist

Before finishing, verify all of the following.

## Functional

- Clicking any process card opens the full-screen detail view smoothly.
- Closing reverses the opening transition.
- Summary/Input/Output/History are vertically navigated from the right rail.
- Every section button is clickable.
- Every section row has working previous/next arrows.
- The first previous arrow and final next arrow are correctly disabled.
- The new Compute Initial Baseline card appears under Data.
- Baseline events update only Compute Initial Baseline.
- Actual training events update only Train the Model.
- Proxy events update Proxy Gate.
- Proxy errors never mark Check Data Safety as Blocked.
- Proxy Gate is under Code & Safety.
- Proxy Gate connects to Train the Model.
- The watchdog rejection loop connects to Find Research Evidence.
- Only one edge is highlighted at a time.
- The highlighted edge returns to idle after its transition.
- The glowing dot starts at the source and travels smoothly to the target.
- The running process card visibly comes forward in 3D.
- Recenter centers the canvas without changing zoom.
- Starting a new run selects the newly created running session.
- A new experiment resets non-Data cards while preserving Data card statuses.
- History and Autonomy Log retain historical events.
- A five-minute running process produces one monitoring update in Autonomy Log.

## Visual

Inspect:

- light mode
- dark mode
- reduced motion
- narrow/mobile layout
- a workflow with a proxy failure
- a workflow with a rejected watchdog decision
- a workflow with an active training card
- a workflow after the canvas has been dragged and zoomed
- a workflow with the new baseline and proxy cards visible

Check for:

- no clipped labels
- no overlapping arrows
- no duplicate active edges
- readable dark-mode idle arrows
- no white flash during FLIP transitions
- no double-highlighted edge in the stage-focus architecture scenes
- no stale status labels from the previous experiment
- no stale session selected after starting a run

## Build and code quality

Run the project’s actual package-manager commands based on the existing lock file. At minimum:

- frontend type-check/build
- repository tests after any package namespace migration
- formatting/lint checks if configured
- `git diff --check`

Run a final tracked-file search for the old product/package variants and confirm there are no remaining references.

Do not finish by merely describing the changes. Implement them, verify them in the browser, and report the exact files changed plus any limitation that could not be safely implemented without changing workflow behavior.
