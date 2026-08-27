# Product

## Register

product

## Users

Two audiences, same screen: (1) hackathon judges watching a short live/replayed demo of an autonomous ML research agent, who need to instantly read "what is the system doing right now and is it working" without domain briefing; (2) the operator (competition team) who needs precise, inspectable state — inputs, outputs, artifacts, timing, past attempts — for every stage of the pipeline, plus safe start/pause/resume/cancel control. Both are watching a long-running, mostly-autonomous process punctuated by real decisions (retain/reject an experiment, recover from a failure, register a new best) that need to read as consequential, not decorative.

## Product Purpose

RIGOR-RS Workflow Observer is the control-room view of an autonomous ML research agent (RIGOR-RS) that reproduces an official recommender-systems baseline, proposes and runs bounded experiments, and converges on a validation-best submission — with zero required human intervention. The UI shows the entire pipeline (data prep → baseline → research → code → train/score → decide → package) as one continuous system: zoomed out, the whole pipeline is visible at once as live telemetry; focused on one stage, that stage takes over the view with its real logs, inputs, outputs, and history. Success = a viewer can tell, at a glance, exactly which stage is active, what it just decided, and why — and can drill into any stage without losing the sense of the whole running system.

## Brand Personality

Mission control / observatory. Precise, calm, confident — an instrument panel, not a toy. Three words: **instrumented, unhurried, exact.** Idle state holds still (or drifts in a slow, deliberate orbit); motion is reserved for real state changes, not ambient decoration. One committed accent — amber/phosphor, CRT-instrument warmth against near-black — carries "this is active / this is signal" across the whole scene. The system should feel like it is quietly, competently running itself, and the viewer is allowed to watch.

## Anti-references

Not a SaaS marketing site: no gradient hero text, no neon glow, no floating glassmorphic cards for their own sake, no bouncy/elastic motion, no generic "AI product" imagery (circuit-board textures, particle swarms, brain icons). Not a game HUD — no arbitrary sci-fi chrome that doesn't map to a real system value. Not cluttered dashboard-software default (dense card grids, tiny uppercase eyebrows over every section, drop-shadow-on-everything). Every visual element must trace back to something the system actually did.

## Design Principles

1. **Show the whole system, then the one true stage.** Two deliberate camera states only — full-pipeline overview and single-stage focus — connected by one continuous, interruptible transition. No intermediate ambiguous zoom levels.
2. **Motion is evidence, not decoration.** A node moves, glows, or pulses only because a real status changed or is currently running. Idle nodes are still.
3. **One accent carries all signal.** Amber/phosphor means "active or meaningful right now"; everything else is calm neutral. Never introduce a second decorative color.
4. **Real data or nothing.** Every number, log line, and label rendered in 3D or in the focus view comes from the same ledger/event contract as the existing 2D observer — no placeholder telemetry.
5. **Precision survives spectacle.** However dynamic the 3D scene gets, exact status, timestamps, and plain-language summaries stay legible — this is an instrument, and instruments must be readable at a glance.

## Accessibility & Inclusion

Reduced motion is mandatory, not optional, given the heavy 3D/camera-motion surface: `prefers-reduced-motion` disables camera fly-throughs, ambient orbit, and node pulse in favor of instant cuts and a static readout; the accessible 2D/list fallback already built for narrow screens remains the reduced-motion and no-WebGL fallback path. Keyboard operability (stage selection, focus/exit, controls) and the existing screen-reader-readable data tables for every chart must be preserved through the redesign, not just the pointer-driven 3D interaction.
