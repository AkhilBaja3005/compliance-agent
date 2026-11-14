import type { Feature, ModelId } from "./domain.js";
import type { Clock } from "./clock.js";
import { scoped } from "./state.js";

export class IdentityIndex {
  private entries = new Map<string, Feature>();
  constructor(private clock: Clock) {}
  upsert(feature: Feature): void {
    this.entries.set(scoped(feature.tenantId, feature.id), structuredClone(feature));
  }
  list(tenantId: string, model: ModelId): Feature[] {
    return [...this.entries.values()].filter(f => f.tenantId === tenantId && f.model === model &&
      Date.parse(f.expiresAt) > this.clock.now().getTime()).map(f => structuredClone(f));
  }
  removeRecord(tenantId: string, recordId: string): void {
    for (const [key, f] of this.entries) {
      if (f.tenantId === tenantId && f.recordId === recordId) this.entries.delete(key);
    }
  }
}
export function simulatedScore(a: number[], b: number[]): number {
  const distance = a.reduce((sum, value, i) => sum + (value - b[i]) ** 2, 0) / a.length;
  return Math.round((1 / (1 + distance)) * 1_000_000) / 1_000_000;
}
