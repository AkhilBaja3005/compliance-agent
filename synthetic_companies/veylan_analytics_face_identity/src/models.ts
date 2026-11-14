import type { ModelId } from "./domain.js";
import { requireThat } from "./errors.js";

export const models: Record<ModelId, { dimensions: number; salt: string; purpose: string }> = {
  "synthetic-v1": { dimensions: 8, salt: "demoface-fixture-v1", purpose: "fabricated identity ranking" },
  "synthetic-v2": { dimensions: 8, salt: "demoface-fixture-v2", purpose: "fabricated identity ranking" },
};
export function modelSpec(id: ModelId) {
  requireThat(Object.hasOwn(models, id), "UNKNOWN_MODEL", "Unknown synthetic model version");
  return models[id];
}
