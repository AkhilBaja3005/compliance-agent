import type { Candidate, ModelId } from "./domain.js";
import type { Clock } from "./clock.js";
import { scoped } from "./state.js";

export class SearchCache {
  private values = new Map<string, { expires: number; candidates: Candidate[] }>();
  constructor(private clock: Clock, private ttlMs: number) {}
  key(tenantId: string, model: ModelId, revision: number, digest: string, limit: number): string {
    return scoped(tenantId, model, String(revision), digest, String(limit));
  }
  prune(): void {
    for (const [key, value] of this.values) {
      if (value.expires <= this.clock.now().getTime()) this.values.delete(key);
    }
  }
  get(key: string): Candidate[] | undefined {
    this.prune();
    const value = this.values.get(key);
    return value ? structuredClone(value.candidates) : undefined;
  }
  set(key: string, candidates: Candidate[], earliestRecordExpiry: number): void {
    this.prune();
    if (this.values.size >= 1000) this.values.delete(this.values.keys().next().value!);
    this.values.set(key, { expires: Math.min(this.clock.now().getTime() + this.ttlMs, earliestRecordExpiry),
      candidates: structuredClone(candidates) });
  }
}
