import { useEffect, useRef } from "react";

interface Props {
  reducedMotion: boolean;
}

interface Wave {
  x: number;
  y: number;
  t: number;
  strength: number;
}

const GRID = 26;
const WAVE_SPEED = 0.62; // px per ms
const WAVE_LIFE = 900; // ms
const RING_WIDTH = 46;

function readVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/**
 * The canvas's own dot field, reacting to the pointer: every dot near a
 * recent pointer position is swept by expanding, fading color rings drawn
 * in the pipeline's own lane hues. Idle dots stay the quiet grid color;
 * nothing here ever leaves a static mark on the surface.
 */
export function CanvasPulseField({ reducedMotion }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const field = canvas?.parentElement;
    const host = field?.parentElement;
    if (!canvas || !field || !host || reducedMotion) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let width = 0;
    let height = 0;
    let cols = 0;
    let rows = 0;

    const resize = () => {
      const rect = host.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      cols = Math.ceil(width / GRID) + 1;
      rows = Math.ceil(height / GRID) + 1;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(host);

    let dotColor = readVar("--grid-dot", "#cbd4de");
    let palette = [
      readVar("--group-data-a", "#39aabd"),
      readVar("--group-research-a", "#9a78ca"),
      readVar("--group-code-a", "#d79554"),
      readVar("--group-train-a", "#dc7183"),
      readVar("--group-decide-a", "#4f76a4"),
    ];
    const refreshColors = () => {
      dotColor = readVar("--grid-dot", "#cbd4de");
      palette = [
        readVar("--group-data-a", "#39aabd"),
        readVar("--group-research-a", "#9a78ca"),
        readVar("--group-code-a", "#d79554"),
        readVar("--group-train-a", "#dc7183"),
        readVar("--group-decide-a", "#4f76a4"),
      ];
    };
    const themeObserver = new MutationObserver(refreshColors);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

    const waves: Wave[] = [];
    let lastWaveAt = 0;
    let lastX = -1;
    let lastY = -1;

    const pushWave = (x: number, y: number, strength: number) => {
      waves.push({ x, y, t: performance.now(), strength });
      if (waves.length > 24) waves.shift();
    };

    const onPointerMove = (event: PointerEvent) => {
      if (event.pointerType && event.pointerType !== "mouse" && event.pointerType !== "pen") return;
      const rect = host.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const now = performance.now();
      if (lastX >= 0) {
        const dist = Math.hypot(x - lastX, y - lastY);
        const speed = dist / Math.max(1, now - lastWaveAt);
        if (now - lastWaveAt > 55 || dist > 30) {
          pushWave(x, y, Math.min(1, 0.45 + speed * 0.9));
          lastWaveAt = now;
        }
      }
      lastX = x;
      lastY = y;
    };

    const onPointerDown = (event: PointerEvent) => {
      if (event.pointerType && event.pointerType !== "mouse" && event.pointerType !== "pen") return;
      const rect = host.getBoundingClientRect();
      pushWave(event.clientX - rect.left, event.clientY - rect.top, 1.6);
      lastWaveAt = performance.now();
    };

    host.addEventListener("pointermove", onPointerMove, { passive: true });
    host.addEventListener("pointerdown", onPointerDown, { passive: true });

    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const now = performance.now();
      for (let i = waves.length - 1; i >= 0; i--) {
        if (now - waves[i].t > WAVE_LIFE) waves.splice(i, 1);
      }

      ctx.clearRect(0, 0, width, height);

      // Idle grid: one batched fill for every resting dot.
      ctx.fillStyle = dotColor;
      ctx.globalAlpha = 1;
      ctx.beginPath();
      for (let gy = 0; gy < rows; gy++) {
        for (let gx = 0; gx < cols; gx++) {
          ctx.moveTo(gx * GRID + 1, gy * GRID);
          ctx.arc(gx * GRID, gy * GRID, 1, 0, Math.PI * 2);
        }
      }
      ctx.fill();

      if (!waves.length) return;

      // Active dots: only cells within reach of a live ring are re-drawn,
      // brighter and colored, on top of the idle grid.
      let minGX = cols;
      let maxGX = 0;
      let minGY = rows;
      let maxGY = 0;
      for (const w of waves) {
        const reach = (now - w.t) * WAVE_SPEED + RING_WIDTH;
        minGX = Math.min(minGX, Math.floor((w.x - reach) / GRID));
        maxGX = Math.max(maxGX, Math.ceil((w.x + reach) / GRID));
        minGY = Math.min(minGY, Math.floor((w.y - reach) / GRID));
        maxGY = Math.max(maxGY, Math.ceil((w.y + reach) / GRID));
      }
      minGX = Math.max(0, minGX);
      minGY = Math.max(0, minGY);
      maxGX = Math.min(cols, maxGX);
      maxGY = Math.min(rows, maxGY);

      for (let gy = minGY; gy <= maxGY; gy++) {
        for (let gx = minGX; gx <= maxGX; gx++) {
          const x = gx * GRID;
          const y = gy * GRID;
          let best = 0;
          let bestColor: string | null = null;
          for (let i = 0; i < waves.length; i++) {
            const w = waves[i];
            const age = now - w.t;
            const ringR = age * WAVE_SPEED;
            const dist = Math.hypot(x - w.x, y - w.y);
            const ringDelta = Math.abs(dist - ringR);
            if (ringDelta > RING_WIDTH) continue;
            const ringFalloff = 1 - ringDelta / RING_WIDTH;
            const ageFalloff = 1 - age / WAVE_LIFE;
            const intensity = ringFalloff * ageFalloff * w.strength;
            if (intensity > best) {
              best = intensity;
              const hue = Math.floor(((Math.atan2(y - w.y, x - w.x) + Math.PI) / (Math.PI * 2)) * palette.length);
              bestColor = palette[(hue + i) % palette.length];
            }
          }
          if (best <= 0.05 || !bestColor) continue;
          ctx.globalAlpha = Math.min(1, best * 1.15);
          ctx.fillStyle = bestColor;
          ctx.beginPath();
          ctx.arc(x, y, 1.3 + best * 3.2, 0, Math.PI * 2);
          ctx.fill();
        }
      }
      ctx.globalAlpha = 1;
    };
    raf = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(raf);
      resizeObserver.disconnect();
      themeObserver.disconnect();
      host.removeEventListener("pointermove", onPointerMove);
      host.removeEventListener("pointerdown", onPointerDown);
    };
  }, [reducedMotion]);

  if (reducedMotion) return null;
  return (
    <div className="canvas-pulse-field" aria-hidden="true">
      <canvas ref={canvasRef} className="canvas-pulse-field__canvas" />
    </div>
  );
}
