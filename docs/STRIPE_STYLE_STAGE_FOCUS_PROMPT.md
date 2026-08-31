# Stripe-Style Stage Focus View — Implementation Prompt

You are implementing this directly in the existing repository:

https://github.com/Dheemant19/TikTok-TechJam_RGB

Important: inspect the current code before changing anything. Do not invent component names or replace the existing workflow architecture.

## Reference material

1. Stripe Press:

   https://press.stripe.com/

2. Attached reference video:

   stripe_animation.mp4

3. Attached current UI video:

   current_ui.mp4

The Stripe reference is only a motion and interaction reference. Do not copy Stripe branding, typography, colors, book imagery, or website content.

## Objective

Replace the current centered inspector modal with a full-screen stage-focus experience.

When the user clicks a workflow process such as “Training Data”:

- Do not open a centered 760px dialog.
- Open a full-screen focus view.
- Divide the focus view into two equal halves.
- The left half must show the complete live workflow architecture with the selected process emphasized and enlarged.
- The right half must contain vertically scrollable details.
- Remove the existing Summary/Input/Output/History tab navigation.
- Render Summary, Input, Output, and History as sequential scroll sections.
- Keep the left architecture pane visually static while the right pane scrolls.
- Once the user reaches the end of History and continues scrolling downward, transition to the next process in the actual workflow order.
- The transition between processes must feel like a smooth Stripe-style 3D page transition.
- The next process must open using the same two-column layout.
- The architecture must remain live React/SVG content. Never use a screenshot, bitmap, canvas capture, or html2canvas.

The workflow execution behavior, run state, node statuses, graph topology, routes, and existing controls must not change.

## Current repository structure

The relevant existing files are:

- ui/src/App.tsx
- ui/src/routes/LiveWorkflow.tsx
- ui/src/liveworkflow/LiveWorkflowCanvas.tsx
- ui/src/liveworkflow/InspectorPanel.tsx
- ui/src/liveworkflow/NodeCard.tsx
- ui/src/liveworkflow/EdgesLayer.tsx
- ui/src/liveworkflow/laneData.ts
- ui/src/liveworkflow/runStore.ts
- ui/src/liveworkflow/useFlipInspector.ts
- ui/src/data/nodeRegistry.ts
- ui/src/data/demoFixture.ts
- ui/src/components/StageListFallback.tsx
- ui/src/components/TopToolbar.tsx
- ui/src/styles/base.css
- ui/src/styles/tokens.css

The current implementation has:

- A draggable and pannable live workflow canvas.
- Live SVG edges rendered by EdgesLayer.
- Live React node cards rendered by NodeCard.
- A centered fixed inspector in InspectorPanel.
- Four tabs: Summary, Input, Output, and History.
- Opening and closing animation logic in useFlipInspector.
- Live status and elapsed-time state in Zustand through useRunStore.
- Node data in NODES, RUN_ORDER, EDGES, and NODE_DETAILS.

The current frontend uses:

- React 18
- TypeScript
- Vite
- React Router
- Zustand
- CSS and inline styles
- package-lock.json

Do not migrate the project to another framework or replace the current architecture.

## Non-negotiable requirements

### 1. Keep the architecture data-driven

Render the architecture from:

- NODES
- EDGES
- positions
- nodeStatus
- nodeElapsed
- EdgesLayer
- NodeCard

Do not render an exported screenshot or static image.

### 2. Do not change workflow execution

Do not modify:

- useRunStore
- RUN_ORDER
- EDGES
- the meaning of any node status
- the run/reset behavior
- the execution timing logic
- the existing top-level routes
- the workflow data contracts

### 3. Use the real workflow order

The main process order is already defined by RUN_ORDER:

    [
      "train_data",
      "data_profiler",
      "phase_guard",
      "knowledge_mcp",
      "scientist",
      "coder",
      "pruner",
      "trainer",
      "evaluator",
      "watchdog",
      "ledger",
      "finalizer",
      "submission"
    ]

When the current stage reaches the end of its four detail sections, advance to the next ID in RUN_ORDER.

Do not determine the next process from screen position, dragged position, or rendered DOM order.

recovery is a side node and is not part of the automatic RUN_ORDER. It should not interrupt the normal sequence. If the user manually opens Recovery, use a sensible continuation such as evaluator, or provide an explicit “Return to Train the Model” or “Continue workflow” affordance.

When the final submission stage is reached, do not wrap back to the first stage. Show a completion state instead.

### 4. Keep global application functionality intact

Do not delete or rewrite:

- TopToolbar
- DemoBanner
- navigation routes
- Run Workflow
- Reset
- main canvas dragging
- canvas panning
- canvas zoom
- keyboard selection behavior

The focus view may temporarily cover the underlying canvas, but closing it must restore the original page unchanged.

### 5. Reuse the existing detail data

Use NODE_DETAILS[nodeId] for:

- summary text
- facts
- input rows
- output rows
- history rows

Do not hard-code duplicate detail data inside the new components.

## Full-screen focus view

Create a new stage-focus component. It may replace InspectorPanel.tsx or be implemented as a new component such as:

    ui/src/liveworkflow/StageFocusView.tsx

The focus view should be rendered as a fixed overlay or portal with:

    position: fixed;
    inset: 0;
    width: 100vw;
    height: 100dvh;
    overflow: hidden;
    z-index: high;

Use 100dvh with a fallback to 100vh.

The focus view must have:

- a compact focus header
- a 50% left architecture pane
- a 50% right detail-scroller pane
- a close button
- current stage metadata
- current status
- stage progress such as “Stage 1 of 13”

Do not render the old four-tab navigation bar.

The global toolbar and workflow state must remain mounted underneath or outside the focus view. Do not create a second independent workflow store.

The focus view should use the existing visual system:

- --surface-0
- --surface-1
- --surface-2
- --text-0
- --text-1
- --text-2
- --primary
- existing lane colors
- Manrope for UI text
- JetBrains Mono for hashes, metrics, timestamps, and technical values

Do not replace the existing palette with Stripe’s dark navy, olive, or cream palette.

## Opening animation

Preserve the current card-origin opening behavior, but change the final destination.

The current code receives the clicked card’s DOMRect through openNode(id, rect). Continue using this origin rectangle.

Opening should work like this:

1. The user clicks a node.
2. Capture the clicked node’s DOMRect.
3. Mount the focus view at the clicked card’s position and size.
4. Animate it from the clicked card rectangle into the full viewport.
5. During the expansion:
   - the surrounding architecture fades or dims
   - the focus container expands
   - the selected stage moves into the left focus area
   - the right Summary section appears
6. Finish with the full-screen two-column layout.

Use a smooth non-bouncy easing such as:

    cubic-bezier(.2, .8, .2, 1)

Suggested duration:

    550–750ms

The opening animation must not depend on a screenshot. A temporary live React duplicate of the selected NodeCard is acceptable for the transition, but do not rasterize the page.

Closing should reverse the opening transition when possible:

1. Animate the focus view back toward the originating card.
2. Unmount after the animation completes.
3. Restore keyboard focus to the original node.
4. If the original node no longer has a usable rectangle, use a short fade-out instead of jumping.

Escape must close the focus view.

## Left architecture pane

Create a component such as:

    FocusArchitecturePane.tsx

It must render actual live architecture content.

The left pane should contain two live layers:

1. Architecture context layer
2. Selected-node focus layer

### Architecture context layer

Render all nodes and edges using the existing code:

    <EdgesLayer ... />
    {NODES.map((node) => (
      <NodeCard ... />
    ))}

Use the current positions state from LiveWorkflowCanvas.

Calculate a fit-to-pane transform from:

- contentBounds(positions)
- NODE_W
- NODE_H
- the actual left-pane size

Use ResizeObserver so the fit calculation updates when the viewport changes.

The complete architecture should remain visible as a live, subdued background/context map:

- all nodes remain mounted
- all edges remain mounted
- statuses continue updating
- running nodes continue showing elapsed time
- edge activity continues reflecting nodeStatus
- no screenshot or static image is allowed

The context layer should be visually de-emphasized:

    opacity: approximately 0.25–0.5

The selected node should be more prominent than all other nodes.

Background nodes should not drag the main canvas while the focus view is open. Set the context layer to pointer-events: none unless direct node selection is intentionally implemented.

### Selected-node focus layer

Render the selected process as a real React node, not as an image.

The focused node should:

- use the same label, monogram, architecture label, and status as the original node
- use the same lane color
- be substantially larger than the context nodes
- be centered or slightly offset within the left pane
- have a strong but restrained shadow
- have a clear selected outline/accent
- remain synchronized with useRunStore
- show running, succeeded, waiting, and other supported statuses correctly
- support keyboard focus
- support pointer hover

Refactor NodeCard only as needed to support a mode such as:

    mode: "canvas" | "focus" | "context"

Do not break existing canvas behavior.

In context mode:

- use the existing compact card appearance
- disable pointer interaction
- disable drag behavior

In focus mode:

- use a larger card scale
- remove drag behavior
- allow hover tilt
- allow clicking the card if direct stage navigation is supported

The selected card should visually read as the hero object of the left pane while the full architecture remains visible behind it.

## 3D hover effect

Implement the selected-node hover effect with CSS 3D transforms.

Do not add WebGL or a heavyweight 3D scene for this interaction.

Use a perspective container:

    .focus-architecture-pane {
      perspective: 1200px;
    }

On pointer movement over the focused node:

- calculate the pointer position relative to the card
- map it to a small tilt
- cap the rotation at approximately ±6 degrees
- apply a slight translateZ and scale
- update through requestAnimationFrame or CSS custom properties
- reset smoothly on pointer leave

Example visual behavior:

    transform:
      perspective(1000px)
      rotateX(var(--tilt-x))
      rotateY(var(--tilt-y))
      translateZ(28px)
      scale(1.025);

Use:

- transform-style: preserve-3d
- backface-visibility: hidden
- will-change: transform
- a deeper shadow while hovered
- a lane-colored highlight or edge accent

Do not make the node continuously spin.

The hover tilt must not change the architecture camera, scroll position, workflow state, or selected process.

## Right detail scroller

Create a component such as:

    StageDetailScroller.tsx

The right side must be the only scrollable area on desktop.

Use:

    overflow-y: auto;
    overscroll-behavior: contain;
    scroll-snap-type: y proximity;

Do not allow the page behind the focus view to scroll.

The right side must render all four sections in this exact order:

    Summary
    Input
    Output
    History

They must be regular document sections, not tabs.

Do not render a tablist.

Do not hide three sections and reveal one selected tab.

Each section must have a stable ID:

    type DetailSectionId = "summary" | "input" | "output" | "history";

Each section should have:

- a visible heading
- clear spacing
- readable hierarchy
- enough vertical height to feel like a distinct chapter
- a subtle section divider
- a data-section attribute
- an accessible heading ID

Suggested structure:

    <section id="summary" data-section="summary">
      ...
    </section>

    <section id="input" data-section="input">
      ...
    </section>

    <section id="output" data-section="output">
      ...
    </section>

    <section id="history" data-section="history">
      ...
    </section>

### Summary section

Render:

- process name
- plain-language description from detail.summary
- current status
- group/lane
- architecture label
- stage number
- facts from detail.facts
- a clearly styled Latest output or Result area using the existing output data

The Summary must appear immediately at the top when a stage opens.

### Input section

Render every row in detail.input.

Each row should show:

- field label
- value
- monospace styling when row.mono is true
- redaction treatment when the value is:
  Hidden to protect data and credentials

Do not expose secrets or raw protected data.

### Output section

Render every row in detail.output.

Use a structured output layout rather than plain paragraphs.

Use:

- output label
- value
- monospace styling where appropriate
- artifact/hash styling for technical values
- lane-colored accent for the section marker

### History section

Render every row in detail.history.

Use a vertical timeline containing:

- attempt number
- status
- timestamp
- note
- status-colored dot

The History section must end with a continuation area.

For non-final stages, show:

    Continue to [next stage label]

For the final stage, show:

    End of workflow

The continuation area must not replace the normal scroll behavior.

## Scroll-driven section state

Track the visible section using IntersectionObserver.

The observer root must be the right-side scroll container, not the browser viewport.

Update:

    activeSection

as the user scrolls.

The left pane must remain static while:

- Summary is visible
- Input is visible
- Output is visible
- History is visible

Scrolling the right pane must not:

- move the left pane
- zoom the architecture
- pan the architecture
- move the selected node
- close the focus view

A small non-interactive progress indicator may be shown in the focus header, for example:

    Summary · Input · Output · History

However, it must not behave like the old tab bar. It should be a read-only scroll-progress indicator. The actual content sections must remain the source of truth.

## Transition to the next process

After the user reaches the bottom of History:

- do not immediately advance the moment History becomes visible
- wait until the user attempts to continue scrolling downward
- detect the bottom using:

      scrollTop + clientHeight >= scrollHeight - 4

- only respond to downward continuation
- prevent browser overscroll from moving the page behind the focus view
- guard against repeated wheel events and trackpad inertia
- allow only one transition at a time

The transition sequence should be:

1. User reaches the end of History.
2. User scrolls downward again.
3. Determine the next node using RUN_ORDER.
4. Keep the current left scene mounted as the outgoing scene.
5. Mount the next live architecture/focus scene as the incoming scene.
6. Animate the outgoing scene away in 3D.
7. Animate the incoming scene into place.
8. Transition the right-side details to the next node.
9. Reset the new right-side scroll position to the top.
10. Display the next node’s Summary section.
11. Remove the outgoing scene after the animation completes.
12. Re-enable scrolling and interaction.

Use a transition duration around:

    650–900ms

Use a restrained 3D page transition such as:

Outgoing scene:

    transform:
      rotateY(-12deg)
      translate3d(-8%, 0, -80px)
      scale(.96);
    opacity: 0;

Incoming scene initial state:

    transform:
      rotateY(12deg)
      translate3d(8%, 0, -80px)
      scale(.96);
    opacity: 0;

Incoming scene final state:

    transform:
      rotateY(0deg)
      translate3d(0, 0, 0)
      scale(1);
    opacity: 1;

The transition must be implemented with keyed live React components and CSS/native animation state.

Do not just replace the text and leave the left pane unchanged.

The left pane must visibly transition from the old process to the next process.

The selected node’s lane accent, label, monogram, status, and details must all update together.

While transitioning:

- temporarily block repeated advance gestures
- do not allow the right scroll container to trigger multiple stages
- do not lose the current workflow status
- do not restart or reset the run
- do not mutate RUN_ORDER

For direct clicks on another visible process in the architecture context:

- use the same 3D transition
- update to the clicked process
- reset the right side to Summary
- do not treat the click as workflow execution
- do not change run order or node status

## State model

Extend or replace useFlipInspector with a clear focus state model.

Suggested state:

    type FocusPhase =
      | "closed"
      | "opening"
      | "open"
      | "transitioning"
      | "closing";

    interface StageFocusState {
      selectedNodeId: string | null;
      previousNodeId: string | null;
      originRect: OverlayRect | null;
      phase: FocusPhase;
      activeSection: DetailSectionId;
      isAdvancing: boolean;
    }

The state must support:

- opening from a canvas node
- opening animation
- full-screen open state
- close animation
- Escape close
- direct navigation to another node
- automatic next-node transition
- reduced-motion fallback
- focus restoration

Do not place detail data in this hook. Continue reading details from NODE_DETAILS.

## Live status updates

The focus view must subscribe to the same Zustand state as the main canvas:

    useRunStore((s) => s.nodeStatus)
    useRunStore((s) => s.nodeElapsed)

If the selected node starts running while its focus view is open:

- update the status indicator
- update elapsed time
- update the focused architecture card
- update the Summary status
- preserve the current scroll section

If another node changes status during the focus view, the background architecture must reflect that change.

Do not freeze the architecture into the state it had when the modal opened.

## Accessibility

The focus view should use:

    role="dialog"
    aria-modal="true"
    aria-label="Stage details for [node label]"

Requirements:

- Escape closes the focus view.
- The close button must be at least 44×44 CSS pixels.
- The focused node must be keyboard reachable.
- Enter and Space should activate selectable nodes.
- Tab must reach all interactive controls.
- Headings must be real semantic headings.
- Do not use color alone to communicate status.
- Preserve existing aria-label behavior from NodeCard.
- Announce stage changes with an aria-live="polite" region.
- Announce the current detail section where useful.
- Restore focus to the originating node after closing.
- Do not trap keyboard focus outside the focus view.
- Do not allow keyboard scrolling to move the background page.

If direct selection of background nodes is implemented:

- make them keyboard reachable
- ensure dimmed nodes remain understandable
- ensure the selected node has a visible focus ring

## Reduced motion

Respect the existing useReducedMotion hook and the prefers-reduced-motion media query.

When reduced motion is enabled:

- remove 3D rotation
- remove hover tilt
- remove depth movement
- replace opening with a short opacity transition
- replace process transitions with a short crossfade
- preserve all scroll and navigation behavior
- do not remove any information
- do not auto-advance unexpectedly

The interface must remain fully functional without motion.

## Responsive behavior

### Desktop

- Use two equal columns.
- Left: live architecture.
- Right: scrollable details.
- The split must remain approximately 50/50.

### Tablet

- Preserve the two-column layout if there is enough width.
- Reduce the architecture context scale.
- Keep the focused node readable.
- Prevent the details column from becoming narrower than usable text width.

### Mobile and narrow screens

The existing app switches to StageListFallback at max-width: 720px.

Do not regress this behavior.

For narrow screens, use a stacked focus layout:

- live architecture at the top
- detail scroller below
- Summary, Input, Output, and History still rendered sequentially
- same next-node transition behavior
- no forced horizontal split
- no clipped text
- no horizontal page scrolling

Keep the current mobile workflow safety behavior from the repository.

## Visual design

Preserve the existing FlowState visual language:

- light neutral surfaces
- subtle dotted workflow background
- blue primary action
- cyan Data lane
- violet Research lane
- amber Code & Safety lane
- rose Train & Score lane
- blue Decide & Package lane
- existing node badge shapes
- rounded cards
- Manrope UI typography
- JetBrains Mono for technical values

Use the selected node’s existing lane color for:

- focus outline
- section marker
- status accent
- subtle background tint
- transition accent

Keep the design restrained.

Do not add:

- neon glows
- excessive blur
- decorative AI imagery
- unrelated gradients
- fake 3D screenshots
- moving background particles
- endless animation
- Stripe logos or branding
- a new tab bar
- a replacement workflow model

The left architecture should visually resemble a live technical diagram being brought into focus, while the right side should read like a structured stage report.

## Recommended component refactor

Use a structure similar to:

    ui/src/liveworkflow/
      StageFocusView.tsx
      FocusArchitecturePane.tsx
      StageDetailScroller.tsx
      stageNavigation.ts
      useStageFocus.ts
      NodeCard.tsx
      EdgesLayer.tsx
      laneData.ts

Possible responsibilities:

StageFocusView.tsx

- full-screen shell
- opening and closing lifecycle
- focus header
- close behavior
- stage transition coordination

FocusArchitecturePane.tsx

- live context architecture
- fit-to-pane transform
- focused node
- 3D hover behavior
- incoming/outgoing scene transition

StageDetailScroller.tsx

- four sequential sections
- section observer
- right-side scrolling
- bottom-of-History detection
- next-stage request

stageNavigation.ts

- next-stage lookup from RUN_ORDER
- stage number
- final-stage detection
- human-readable next-stage labels

useStageFocus.ts

- selected node
- origin rectangle
- opening and closing phase
- transition phase
- focus restoration

Keep laneData.ts as the source of node details and layout constants unless there is a strong reason to split its data.

## Validation requirements

After implementation, verify:

1. Clicking Training Data opens the new full-screen focus view.
2. The view is split into equal left and right areas.
3. The left side shows a live architecture with all nodes and edges.
4. Training Data is visibly enlarged and highlighted.
5. The selected node responds to pointer hover with a restrained CSS 3D tilt.
6. The right side starts at Summary.
7. Scrolling reveals Input, then Output, then History.
8. The old tab bar is gone.
9. The left side does not move while the right side scrolls.
10. The right side cannot scroll the page behind the focus view.
11. Continuing downward at the bottom of History transitions to the next RUN_ORDER node.
12. The next node is Inspect & Prepare Data when starting from Training Data.
13. The next node’s Summary appears at the top after transition.
14. The transition visibly changes the live architecture focus.
15. No screenshot or static architecture image is used.
16. Run Workflow still works.
17. Reset still works.
18. Node statuses and elapsed times still update live.
19. Closing the focus view restores the original canvas.
20. Escape closes the focus view.
21. Keyboard focus returns to the original node after closing.
22. Reduced motion removes 3D movement but preserves functionality.
23. Narrow-screen fallback remains usable.
24. The final stage does not loop back to Training Data.
25. The application builds successfully.

Run the existing build using the repository’s current package manager:

    cd ui
    npm run build

Do not replace package-lock.json with a different lockfile unless absolutely necessary.

Before finishing, inspect the implementation in an actual browser at:

- desktop width
- tablet width
- mobile width
- reduced-motion mode

The final result should feel like a live, code-driven architecture explorer with a Stripe-inspired scroll narrative—not like a centered modal with four tabs.
