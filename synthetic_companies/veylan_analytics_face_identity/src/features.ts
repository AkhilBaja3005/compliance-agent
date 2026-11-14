import { createHash } from "node:crypto";
import type { FaceRecord, Feature, ModelId } from "./domain.js";
import { modelSpec } from "./models.js";
import { requireThat } from "./errors.js";

export const digestToken = (token: string): string => createHash("sha256").update(token).digest("hex");
export function syntheticVector(imageToken: string, model: ModelId): number[] {
  requireThat(/^synthetic:[a-z0-9_-]{1,80}$/.test(imageToken), "BAD_TOKEN", "Synthetic token required");
  const spec = modelSpec(model);
  const bytes = createHash("sha256").update(`${spec.salt}:${imageToken}`).digest();
  // These numbers have no relationship to facial geometry or any real person.
  return Array.from({ length: spec.dimensions }, (_, i) => bytes[i] / 255);
}
export function extractFeature(record: FaceRecord, imageToken: string, model: ModelId): Feature {
  return { id: `${record.id}-${model}`, tenantId: record.tenantId, recordId: record.id,
    sourceId: record.sourceId, model, vector: syntheticVector(imageToken, model), expiresAt: record.expiresAt };
}
