import { Vec2 } from "./laneData";

export function edgePoint(pos: Vec2, side: "left" | "right", w: number, h: number): Vec2 {
  return side === "right" ? { x: pos.x + w, y: pos.y + h / 2 } : { x: pos.x, y: pos.y + h / 2 };
}

export function bezierPath(p1: Vec2, p2: Vec2): { d: string; midX: number } {
  const midX = (p1.x + p2.x) / 2;
  return { d: `M ${p1.x} ${p1.y} C ${midX} ${p1.y}, ${midX} ${p2.y}, ${p2.x} ${p2.y}`, midX };
}

/**
 * Routes a rejected-decision handoff as one smooth arch clearing every lane
 * it crosses -- no straight rail segments, which previously turned sharp
 * corners directly over intermediate cards. Pulling both control points a
 * generous 34% of the span in from their own endpoint (rather than the
 * usual ~20% used for a gentle forward-edge curve) widens and flattens the
 * hump so the middle of the arch stays close to `clearanceY` across most of
 * its width instead of peaking briefly and sagging back down early.
 */
export function loopPath(p1: Vec2, p2: Vec2, clearanceY: number): { d: string } {
  const span = p1.x - p2.x;
  const c1: Vec2 = { x: p1.x - span * 0.34, y: clearanceY };
  const c2: Vec2 = { x: p2.x + span * 0.34, y: clearanceY };
  return { d: `M ${p1.x} ${p1.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${p2.x} ${p2.y}` };
}
