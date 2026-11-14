import type { JobMessage, SyntheticFace } from "./domain.js";
import { requireThat } from "./errors.js";

export function validId(value: unknown): value is string {
  return typeof value === "string" && /^[a-zA-Z0-9_-]{1,100}$/.test(value);
}
export function decodeMessage(body: string): JobMessage {
  requireThat(body.length <= 2048, "BAD_MESSAGE", "Message too large");
  let value: unknown;
  try { value = JSON.parse(body); } catch { value = null; }
  const x = value as Partial<JobMessage> | null;
  requireThat(x && x.version === 1 && validId(x.tenantId) && validId(x.jobId),
    "BAD_MESSAGE", "Invalid job envelope");
  return { version: 1, tenantId: x.tenantId, jobId: x.jobId };
}
export function validateFace(value: unknown): asserts value is SyntheticFace {
  const x = value as SyntheticFace | null;
  requireThat(x && validId(x.id) && validId(x.subjectRef) &&
    typeof x.imageToken === "string" && /^synthetic:[a-z0-9_-]{1,80}$/.test(x.imageToken) &&
    typeof x.enrolled === "boolean" && typeof x.availableAt === "string" &&
    Number.isFinite(Date.parse(x.availableAt)) && !x.fault,
  "INVALID_FIXTURE", "Only valid synthetic face records are accepted");
}
export function objectKey(tenantId: string, key: string): string {
  requireThat(validId(tenantId) && validId(key), "BAD_KEY", "Invalid storage key");
  return `demoface/${tenantId}/${key}.json`;
}
export function encodeBlob(value: SyntheticFace, expiresAt: string): string {
  validateFace(value);
  requireThat(Number.isFinite(Date.parse(expiresAt)), "BAD_EXPIRY", "Invalid expiration");
  return JSON.stringify({ version: 1, expiresAt, value });
}
export function decodeBlob(body: string, now: Date): SyntheticFace | undefined {
  requireThat(body.length < 16384, "BAD_BLOB", "Blob too large");
  const x = JSON.parse(body) as { version: number; expiresAt: string; value: unknown };
  requireThat(x.version === 1 && Number.isFinite(Date.parse(x.expiresAt)), "BAD_BLOB", "Invalid blob");
  if (Date.parse(x.expiresAt) <= now.getTime()) return undefined;
  validateFace(x.value);
  return x.value;
}
