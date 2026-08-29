import type { JsonRecord, JsonValue } from "./types";

// Narrow `JsonValue` (unvalidated backend payload data) down to a concrete
// shape at the point of use instead of casting. Every accessor returns
// `undefined` on a shape mismatch rather than throwing, since payloads are
// backend-controlled but not schema-pinned on the frontend.

export function asRecord(value: JsonValue | undefined): JsonRecord | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value : undefined;
}

export function asArray(value: JsonValue | undefined): JsonValue[] | undefined {
  return Array.isArray(value) ? value : undefined;
}

export function asString(value: JsonValue | undefined): string | undefined {
  return typeof value === "string" ? value : undefined;
}

export function asNumber(value: JsonValue | undefined): number | undefined {
  return typeof value === "number" ? value : undefined;
}

export function asBoolean(value: JsonValue | undefined): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

export function field(record: JsonRecord | undefined, key: string): JsonValue | undefined {
  return record ? record[key] : undefined;
}
