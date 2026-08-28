import { Vec2 } from "./laneData";

export function edgePoint(pos: Vec2, side: "left" | "right", w: number, h: number): Vec2 {
  return side === "right" ? { x: pos.x + w, y: pos.y + h / 2 } : { x: pos.x, y: pos.y + h / 2 };
}

export function bezierPath(p1: Vec2, p2: Vec2): { d: string; midX: number } {
  const midX = (p1.x + p2.x) / 2;
  return { d: `M ${p1.x} ${p1.y} C ${midX} ${p1.y}, ${midX} ${p2.y}, ${p2.x} ${p2.y}`, midX };
}

export function bezierPoint(p1: Vec2, p2: Vec2, midX: number, t: number): Vec2 {
  const mt = 1 - t;
  return {
    x: mt ** 3 * p1.x + 3 * mt * mt * t * midX + 3 * mt * t * t * midX + t ** 3 * p2.x,
    y: mt ** 3 * p1.y + 3 * mt * mt * t * p1.y + 3 * mt * t * t * p2.y + t ** 3 * p2.y,
  };
}
