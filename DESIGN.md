---
name: RIGOR-RS Workflow Observer
description: A draggable, colorful workflow canvas recreated pixel-for-pixel from a design handoff, with a Stripe-style morphing inspector and a live run simulation.
colors:
  surface-0: "#f4f6fa"
  surface-1: "#ffffff"
  surface-2: "#f8fafc"
  border: "rgba(15,23,42,.06)"
  border-strong: "rgba(15,23,42,.14)"
  grid-dot: "#d9dfe9"
  text-0: "#0f172a"
  text-1: "#334155"
  text-2: "#94a3b8"
  primary: "#3b82f6"
  primary-dim: "#2563eb"
  lane-data: "#06b6d4"
  lane-research: "#8b5cf6"
  lane-code: "#f59e0b"
  lane-train: "#f43f5e"
  lane-decide: "#3b82f6"
  status-success: "#22c55e"
  status-attention: "#f59e0b"
  status-failed: "#ef4444"
typography:
  ui:
    fontFamily: "Manrope, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "14px"
    fontWeight: 500
  telemetry:
    fontFamily: "JetBrains Mono, ui-monospace, SF Mono, monospace"
    fontSize: "12px"
rounded:
  sm: "10px"
  md: "12px"
  lg: "18px"
spacing:
  1: "0.25rem"
  2: "0.5rem"
  3: "0.75rem"
  4: "1rem"
  5: "1.5rem"
  6: "2rem"
  7: "3rem"
  8: "4rem"
components:
  nav-pill-active:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: "8px 12px"
  card:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.text-0}"
    rounded: "18px"
    padding: "44px 16px 14px 16px"
---

# Design System: RIGOR-RS Workflow Observer

<!-- Revision history: this is the third visual world for this project. v1 was a
     near-black "instrument panel" (single amber accent, flat 2D/3D hybrid). v2 was
     a light 3D WebGL scene with per-group pastel/vivid colors. v3 -- this one --
     discards both in favor of an exact recreation of a supplied high-fidelity
     design handoff (design_handoff_workflow_observer/RIGOR-RS_Workflow_design.html),
     at the user's explicit direction ("use the exact code"). Colors, spacing,
     shapes, type sizes, and animation timings below are taken verbatim from that
     handoff, not invented. Only the accessibility layer (keyboard operability,
     reduced motion, the narrow-screen list fallback) and the cross-route app shell
     (toolbar nav, other five routes, autonomy timeline) are original additions on
     top of the handoff, which covered only the Live Workflow view. -->

## Overview

**Creative North Star: "The Live Diagram"** (carried over from v2; the handoff replaces its execution, not its thesis)

The pipeline renders as a workshop of physical, colorful index cards on a light, dotted-grid canvas — pannable, zoomable, and draggable, closer to a whiteboard planning session than a terminal or an instrument panel. Five lanes (Data/cyan, Research/violet, Code & Safety/amber, Train & Score/rose, Decide & Package/blue) each carry one gradient identity color, expressed as a small shaped badge (rounded square, circle, diamond, pentagon, hexagon — one shape per lane) plus a matching colored ring/glow around an otherwise white card. Pressing "Run Workflow" steps through the 13-node main path in sequence with live elapsed timers, a pulsing running-state glow, and an amber "comet" that travels continuously along the active incoming edge. Clicking any node captures its exact on-screen position and morphs it (a Stripe-books-style FLIP animation: left/top/width/height/border-radius/box-shadow all transitioning together) into a large, lane-colored inspector with Summary/Input/Output/History tabs; closing reverses the same morph back to the origin card.

**Key Characteristics:**
- Light canvas (`#f4f6fa`), 22px dot grid (`#d9dfe9`), Manrope UI type, JetBrains Mono for elapsed timers
- Five lane gradient colors, each with a distinct badge shape — identity is never ambiguous
- Draggable nodes (session-local reposition only, never changes execution order) and pannable/zoomable canvas
- A single named interaction is the signature: the FLIP-morph inspector, reused unmodified as a slide-up bottom sheet on narrow screens
- Full parity fallback: reduced motion gets an instant (non-morphing) inspector and no ambient animation; narrow screens get a keyboard-navigable list with the same live status; every node card is a real, tabbable, Enter/Space-operable element (an accessibility layer the handoff itself did not specify, added on top of it)

## Colors

### Primary
- **Primary Blue** (`#3b82f6`, gradient to `#60a5fa` on buttons): active nav pill, links, focus rings, the "Decide & Package" lane's identity color, active-edge stroke, comet head glow, and the Run Workflow button.

### Secondary — one gradient per pipeline lane
- **Cyan** (`#22d3ee → #06b6d4`, glow `rgba(6,182,212,.32)`) — Data lane, rounded-square badge.
- **Violet** (`#a78bfa → #8b5cf6`, glow `rgba(139,92,246,.32)`) — Research lane, circle badge.
- **Amber** (`#fbbf24 → #f59e0b`, glow `rgba(245,158,11,.32)`) — Code & Safety lane, diamond (rotated square) badge.
- **Rose** (`#fb7185 → #f43f5e`, glow `rgba(244,63,94,.32)`) — Train & Score lane (and the standby Recovery node), pentagon badge.
- **Blue** (`#60a5fa → #3b82f6`, glow `rgba(59,130,246,.32)`) — Decide & Package lane, hexagon badge.

### Neutral
- **Surface 0** (`#f4f6fa`): page and canvas background. **Revision (2026-08-28):** layered under the dot grid, two very faint radial washes (`rgba(59,130,246,.07)` top-left, `rgba(139,92,246,.06)` bottom-right — the same primary blue and research violet already in the lane palette) keep the background from reading as flat white, without darkening it or introducing a new hue.
- **Surface 1** (`#ffffff`): every card, the toolbar (at 78% opacity with a 14px blur), the inspector.
- **Surface 2** (`#f8fafc`): fact-card background inside the inspector's Summary tab.
- **Border / Border Strong** (`rgba(15,23,42,.06)` / `rgba(15,23,42,.14)`): card borders and dividers.
- **Grid Dot** (`#d9dfe9`): the canvas's dotted-grid background.
- **Text 0 / 1 / 2** (`#0f172a` / `#334155` / `#94a3b8`): primary, body, and muted/secondary text.

### Status (node status text/dot, independent of lane color)
- **Waiting** — text `#94a3b8`, dot `#cbd5e1`.
- **Running** — text `#2563eb`, dot `#3b82f6`, pulsing.
- **Succeeded** — text `#16a34a`, dot `#22c55e`.
- **Standby** (Recovery node only, while waiting) — same as Waiting, different label text.

### Named Rules
**The Lane-Owns-Identity Rule.** A node's lane gradient never changes with status — it is a fixed identity color shown in the badge and the resting glow. Status is communicated separately, through the dot/text color and the run-state glow/pulse animation, so identity and state are always visually independent.

**The Real DOM Card Rule.** Every node is a real, focusable DOM element (not a canvas-drawn shape), specifically so it can be a native Tab stop with native Enter/Space activation — this is the accessibility layer added on top of the handoff, which specified pointer-only interaction.

## Typography

**UI Font:** Manrope (500/600/700/800)
**Telemetry Font:** JetBrains Mono (400/500) — elapsed timers only.

### Hierarchy
- **Node label** (800, 14px, `-.01em` tracking): the plain-language card title.
- **Secondary/architecture label** (600, 11px, `#94a3b8`): the node's underlying system role.
- **Inspector title** (800, 20px, white, `-.01em`): the node label inside the morphed panel header.
- **Body** (14.5px, 1.65 line-height, `#334155`): inspector summary prose.
- **Fact value** (700, 13.5px): inspector Summary-tab fact cards.
- **Label/eyebrow** (700, 10.5–11px, uppercase, `.04em` tracking, `#94a3b8`): fact-card and field-row labels.

## Layout

Full-viewport pannable/zoomable canvas (pointer-drag to pan on empty background, wheel to zoom, clamped 0.55×–1.4×) beneath a fixed 68px translucent toolbar. Five lanes at fixed x-offsets (`50, 340, 630, 920, 1210`), each a vertical stack of 224×128px cards on a 178px row rhythm, vertically centered against the tallest lane (4 nodes). Node positions are draggable and session-local; the canvas transform (`translate(pan) scale(zoom)`) is the single source of truth for where the pipeline renders. **Revision (2026-08-28):** the canvas centers its content bounding box in the viewport on mount, and the wheel-zoom anchors to the pointer position (not the transform's local origin) — an initial version anchored zoom at the top-left corner, so zooming out visibly dragged the pipeline toward that corner instead of staying put.

This project's own additions beyond the handoff: a route toolbar (six destinations) sharing the same 68px bar as the handoff's brand mark and Run/Reset controls (the latter shown only on the Live Workflow route). Below 720px width, the canvas is replaced entirely by a keyboard-navigable list (grouped by lane, same live status), and the Run/Reset/Environment controls are hidden from the toolbar. **Revision (2026-08-28):** the autonomy log moved off the Live Workflow route entirely, into its own page (`/autonomy`) reached via a dedicated header button (clock icon, distinct from the six route pills); it is no longer a bottom strip on the canvas. The five non-canvas routes (Data Profile, Experiments, Research Library, Resources, Final Package, and now Autonomy Log) share one container convention: `maxWidth: 1200px`, `margin: 0 auto` — centered, filling most of a laptop-width viewport rather than sitting flush left in a narrow column.

## Elevation & Depth

Every card rests on a colored glow-shadow unique to its lane (`0 10px 26px -12px rgba(15,23,42,.18), 0 0 0 2px {laneShadow}, 0 0 18px 1px {laneShadow}`), replaced by a pulsing `runGlow` animation while running. Hover lifts with a 3D tilt (`perspective(900px) rotateX(-3deg) rotateY(3deg) translateY(-5px) scale(1.015)`) and a stronger colored shadow. The morphed inspector panel is the deepest surface (`0 50px 110px -24px rgba(15,23,42,.5)`).

### Named Rules
**The Glow-Is-Identity Rule.** A resting card's shadow always carries its lane's color at low opacity — this is a second, ambient reinforcement of lane identity beyond the badge, always present even when the badge itself is off-screen or occluded.

## Shapes

18px card radius; badge shape is lane-specific (rounded square, circle, 45°-rotated square/diamond, pentagon via clip-path, hexagon via clip-path) and doubles as a second identity signal independent of color; inspector radius morphs from the origin card's 18px to 26px (open) / 18px (collapsing); fact cards 12px; buttons and toolbar chips 12px.

## Components

### Node Card (signature component)
224×128px white rounded card; a 44×44px lane-shaped badge overlaps the top-left corner (-14px/16px offset) with a 2-letter monogram; label, secondary label, and a status row (dot + text, elapsed timer in mono when running) below. The standby Recovery node uses a dashed border and 0.75 opacity instead of a solid ring. Fully draggable (pointer-down + move, >4px suppresses the following click) and, as an addition to the handoff, fully keyboard-operable (`tabIndex`, `role="button"`, Enter/Space opens the inspector, a visible focus ring).

### Edges & Run Tracker
Curved SVG bezier paths between lane-adjacent nodes; inactive edges are thin gray (`#64748b`), an edge whose source has succeeded and target is active turns blue, thicker, and animates its dash offset (`dashFlow`). The Trainer→Recovery link is always a static gray dashed line (never "active"). While a node runs, an amber comet (bright head + fading tail, glow via `drop-shadow`) loops continuously along its incoming edge.

### Inspector (FLIP morph)
Captures the clicked card's `getBoundingClientRect()` and animates `left/top/width/height/border-radius/box-shadow` together (0.5s, `cubic-bezier(.2,.8,.2,1)`) to a centered ~760px panel with a lane-gradient header, badge, title, and status; four tabs (Summary/Input/Output/History); closing reverses the morph before unmounting. A dim backdrop (`rgba(15,23,42,.35)`) fades in alongside. On narrow screens the same mechanism drives a full-width bottom sheet instead (a synthetic "collapsed at the bottom edge" starting rect, so the exact same code path produces a slide-up sheet). Under `prefers-reduced-motion`, the morph is skipped entirely — the panel appears and disappears at its final state instantly.

### Toolbar
68px, `rgba(255,255,255,.78)` with a 14px backdrop blur, translucent over the canvas. Brand mark (34px blue-gradient rounded square + wordmark) on the left; six route nav pills in the middle (active = solid Primary Blue); on the Live Workflow route only, an "Environment: Production" pill, a Reset button, and the primary Run Workflow button (shows a spinning ring + "Running…" while active, becomes "Run Again" once done) on the right.

## Do's and Don'ts

### Do:
- **Do** treat lane color as fixed identity and status color/animation as the separate, independent signal of what's happening right now.
- **Do** keep every node card a real, focusable DOM element — never move node rendering to `<canvas>` or SVG-only shapes, which would silently drop the keyboard/screen-reader layer.
- **Do** reuse the FLIP-morph mechanism (never build a second inspector implementation) for both the desktop centered panel and the mobile bottom sheet, driven only by the target rect and `isNarrow`.
- **Do** suppress the FLIP transition entirely under reduced motion — an instant open/close, not a shortened one.

### Don't:
- **Don't** let a node's fill color change with run status — only the glow, pulse, and the small status dot/text change; the lane gradient is permanent.
- **Don't** show the Run Workflow/Reset/Environment controls on narrow screens — they overflow the toolbar and were never part of the narrow-screen contract (Plan_UI.md: run controls stay disabled on small screens).
- **Don't** invent new lane colors, badge shapes, or animation timings — this file's values come from a supplied design handoff and are final; treat them as pinned, not as a starting point for iteration.
- **Don't** reintroduce three.js/WebGL for this view — v2's 3D scene is retired; the canvas is plain DOM + SVG, which is what makes native keyboard focus on nodes possible at all.
