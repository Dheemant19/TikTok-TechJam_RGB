import { Vec2 } from "./laneData";

export function edgePoint(pos: Vec2, side: "left" | "right", w: number, h: number): Vec2 {
  return side === "right" ? { x: pos.x + w, y: pos.y + h / 2 } : { x: pos.x, y: pos.y + h / 2 };
}

export function bezierPath(p1: Vec2, p2: Vec2): { d: string; midX: number } {
  const midX = (p1.x + p2.x) / 2;
  return { d: `M ${p1.x} ${p1.y} C ${midX} ${p1.y}, ${midX} ${p2.y}, ${p2.x} ${p2.y}`, midX };
}

/**
 * Routes a rejected-decision handoff from the decision card's left edge to
 * the research-evidence card's top edge. The final control point stays above
 * the target, so the curve approaches vertically and cannot look like a
 * horizontal rail continuing toward the next research card.
 */
export function loopPath(p1: Vec2, p2: Vec2, clearanceY: number): { d: string } {
  const span = p1.x - p2.x;
  const c1: Vec2 = { x: p1.x - span * 0.28, y: clearanceY };
  const c2: Vec2 = { x: p2.x, y: clearanceY };
  return { d: `M ${p1.x} ${p1.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${p2.x} ${p2.y}` };
}
