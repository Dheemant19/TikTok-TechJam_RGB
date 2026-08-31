# Handoff: FlowState Workflow Observer — Live Workflow Canvas

## Overview
An interactive, draggable workflow canvas showing the FlowState 14-node pipeline (Data → Research → Code & Safety → Train & Score → Decide & Package). Users can pan/zoom the canvas, drag nodes, click "Run Workflow" to watch nodes execute in sequence with live timers and a traveling progress indicator along the active connection, and click any node to open a Stripe-style morph-in inspector with Summary/Input/Output/History tabs.

## About the Design Files
The bundled file (`FlowState_Workflow_design.html`) is a **design reference** built as a single self-contained interactive HTML prototype — not production code to copy directly. It uses inline styles and a lightweight custom component runtime specific to the prototyping tool it was built in. Per `Plan_UI.md`, the target implementation should be a **Vite + React + TypeScript app** using `@xyflow/react` for the canvas, `motion` for transitions, TanStack Query for data, and Radix UI for accessible primitives — recreate this design's visuals and interactions in that stack, wiring it to the real observer API instead of the mock data used here.

## Fidelity
**High-fidelity.** Colors, spacing, shapes, type sizes, and animation timings below are final; recreate them precisely. Content (node labels, mock summaries/metrics) is placeholder/demo data — replace with real API data per the endpoints in `Plan_UI.md`.

## Screens / Views
This prototype covers one view: **Live Workflow**.

### Live Workflow canvas
- **Purpose**: Observe the pipeline run live, inspect any component's input/output/history, and (optionally) drag nodes to reposition them for reading (session-local only — never changes execution order).
- **Layout**: Full-viewport. A 68px translucent (`rgba(255,255,255,.78)`, `backdrop-filter: blur(14px)`) top toolbar sits above a pannable/zoomable canvas with a dotted background (`radial-gradient(#d9dfe9 1px, transparent 1px)`, 22px grid, on `#f4f6fa`).
- **Toolbar**: Left — 34px logo mark (10px radius, blue gradient `#60a5fa→#3b82f6`) + "FlowState" (15px/800) + "Workflow Observer" subtitle (11px/600, `#94a3b8`). Right — an "Environment: Production" pill, a "Reset" button, and a primary "Run Workflow" button (blue gradient, 12px radius, white 800-weight text, shows a spinning ring + "Running…" while active, becomes "Run Again" once done).
- **Canvas**: 5 lanes left to right, each lane a vertical stack of node cards, connected by curved SVG bezier edges:
  - Lane 0 — Data (cyan): Training Data, Inspect & Prepare Data, Check Data Safety
  - Lane 1 — Research (violet): Find Research Evidence, Choose the Next Experiment
  - Lane 2 — Code & Safety (amber): Write the Code Change, Run Fast Safety Tests
  - Lane 3 — Train & Score (rose): Train the Model, Recover from Failures (dashed, standby), Score on Validation
  - Lane 4 — Decide & Package (blue): Decide: Continue or Stop, Save Run Evidence, Build Final Package, Verified Predictions
- **Node card**: 224px wide, white background, 18px border radius, 1px border, resting shadow `0 10px 26px -12px rgba(15,23,42,.18)` plus a 2px colored ring + soft colored glow matching its lane color. A colored badge (44×44px) overlaps the top-left corner (offset -14px/16px), shaped per lane — rounded square / circle / diamond (rotated 45°) / pentagon / hexagon — filled with the lane's gradient and a 2-letter monogram. Below: label (14px/800, `#0f172a`), secondary architecture label (11px/600, `#94a3b8`), and a status row (7px status dot + status text + elapsed timer in monospace when running).
- **Recovery node**: dashed border, same rose color as the Train & Score lane, 0.75 opacity while idle/standby.

## Interactions & Behavior
- **Pan**: pointer-drag on empty canvas background (not on a node).
- **Zoom**: mouse wheel, clamped 0.55×–1.4×.
- **Drag node**: pointer-down + drag on a card moves it (session-local position only); a >4px move suppresses the subsequent click so dragging never opens the inspector.
- **Run Workflow**: steps through the 13 main-path nodes in order. Each step: card status → "Running" (pulsing dot, glowing pulse animation `runGlow` 1.4s, elapsed timer ticking every 100ms), then → "Succeeded" (green check dot) after ~0.85–1.3s (randomized), before advancing to the next node. The incoming edge into the running node turns blue, dashed, and animates (`dashFlow`, flowing dash offset). Recovery is a standby node and is not part of the automatic run.
- **Progress tracker**: while a node runs, an amber glowing "comet" (bright head + fading tail, `drop-shadow` glow) loops continuously along the active incoming bezier edge (750ms loop) to draw the eye to the active transition.
- **Reset**: clears all node statuses back to "Waiting" and stops any in-flight run.
- **Click a node → inspector**: captures the clicked card's on-screen bounding rect, opens a full-height right-anchored panel that **morphs from the card's exact position/size to a centered ~760px-wide panel** (Stripe-books style FLIP animation): `left/top/width/height/border-radius/box-shadow` all transition together over 0.5s with `cubic-bezier(.2,.8,.2,1)`. A dim backdrop (`rgba(15,23,42,.35)`) fades in alongside.
  - Inspector header: lane-gradient background, close button (top-right, 32px, translucent), large badge, node label (20px/800 white), secondary label, status.
  - Tabs: Summary / Input / Output / History — active tab has a 2px blue bottom border and dark text; inactive tabs are `#94a3b8`.
  - Summary tab: plain-language description + a 2-column grid of key facts (label/value cards, `#f8fafc` background).
  - Input/Output tabs: label/value rows separated by 1px dividers. Redacted fields display the fixed string "Hidden to protect data and credentials" (per `Plan_UI.md` redaction rule — never hide via CSS alone; the backend must not send the raw value).
  - History tab: one row per attempt with a status dot, "Attempt N — Status", and timestamp + note.
  - Close: click the ✕ or the backdrop; the panel reverses its morph back to the origin card before unmounting (~460ms).

## State Management
- `positions`: per-node `{x, y}` — draggable, session-local.
- `pan` / `zoom`: canvas transform state.
- `nodeStatus`: per-node `'waiting' | 'running' | 'succeeded'` (extend to the full `Plan_UI.md` vocabulary — `paused | failed | rejected | skipped | blocked` — when wiring to real data).
- `nodeElapsed`: per-node running duration in ms, ticked while status is `running`.
- `runStatus`: `'idle' | 'running' | 'done'` — drives the Run button label/disabled state.
- `selected`: id of the node whose inspector is open, plus the captured `overlayRect` and an `overlayOpen` boolean that drives the FLIP transition.
- `activeTab`: `'summary' | 'input' | 'output' | 'history'`.
- In production, replace the local `setTimeout` run simulation with the real SSE event stream (`GET /api/v1/sessions/{id}/events`) described in `Plan_UI.md`, mapping each event to a `nodeStatus`/`nodeElapsed` update.

## Design Tokens

**Lane colors** (gradient `a → b`, plus a matching shadow/glow color):
- Data (cyan): `#22d3ee → #06b6d4`, glow `rgba(6,182,212,.32)`
- Research (violet): `#a78bfa → #8b5cf6`, glow `rgba(139,92,246,.32)`
- Code & Safety (amber): `#fbbf24 → #f59e0b`, glow `rgba(245,158,11,.32)`
- Train & Score / Recovery (rose): `#fb7185 → #f43f5e`, glow `rgba(244,63,94,.32)`
- Decide & Package (blue): `#60a5fa → #3b82f6`, glow `rgba(59,130,246,.32)`

**Status colors**: waiting `#94a3b8`/dot `#cbd5e1` · running `#2563eb`/dot `#3b82f6` · succeeded `#16a34a`/dot `#22c55e`.

**Neutrals**: background `#f4f6fa`, dot grid `#d9dfe9`, card border `rgba(15,23,42,.06)`, body text `#334155`/`#1e293b`, muted text `#94a3b8`.

**Edges**: inactive `#64748b`, active `#3b82f6` (2.6px, dashed 10/6, animated), recovery link dashed `#94a3b8` (5/5, static).

**Progress tracker**: head `#f59e0b` r=8 with amber glow, tail `#fbbf24` r=5 at 55% opacity, 750ms loop.

**Typography**: Manrope (500/600/700/800) for all UI text; JetBrains Mono for elapsed timers and code-like values. Titles `-0.01em` letter-spacing.

**Radii**: cards 18px, badges follow lane shape, inspector 26px (open) / 18px (closed), fact cards 12px, buttons 12px.

**Shadows**: resting card `0 10px 26px -12px rgba(15,23,42,.18)` + colored ring/glow; hover lifts with `translateY(-5px) scale(1.015)` and a stronger colored shadow; inspector open `0 50px 110px -24px rgba(15,23,42,.5)`.

**Motion**: card hover 3D tilt via `perspective(900px) rotateX(-3deg) rotateY(3deg)`; running-card pulse `runGlow` 1.4s ease-in-out infinite; status dot pulse `pulseDot` 1s; inspector morph 0.5s `cubic-bezier(.2,.8,.2,1)` on left/top/width/height/border-radius/box-shadow; button press `scale(.98)`.

## Assets
No external images or icon fonts. Badges use CSS shapes (border-radius / rotated square / clip-path polygons) with a 2-letter monogram, not icon glyphs. Fonts loaded from Google Fonts (Manrope, JetBrains Mono).

## Files
- `FlowState_Workflow_design.html` — the full interactive prototype (open directly in a browser).
