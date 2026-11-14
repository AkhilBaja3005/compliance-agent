import { randomUUID } from "node:crypto";
import type { Batch, ModelId, Principal } from "./domain.js";
import { after, type Clock } from "./clock.js";
import type { ProductConfig } from "./config.js";
import { ProductState, scoped } from "./state.js";
import type { SourceService } from "./source-service.js";
import { requireThat } from "./errors.js";
import { validId } from "./codec.js";
import { modelSpec } from "./models.js";

export class BatchService {
  constructor(private state: ProductState, private sources: SourceService,
    private clock: Clock, private config: ProductConfig) {}
  open(actor: Principal, sourceId: string, model: ModelId, idempotencyKey: string): Batch {
    requireThat(actor.role === "admin" || actor.role === "operator", "FORBIDDEN", "Ingestion denied");
    this.sources.active(actor.tenantId, sourceId);
    modelSpec(model);
    requireThat(validId(idempotencyKey), "BAD_IDEMPOTENCY_KEY", "Use a bounded opaque idempotency key");
    const key = scoped(actor.tenantId, idempotencyKey);
    const previous = this.state.idempotency.get(key);
    if (previous) {
      const batch = this.state.batches.get(previous)!;
      requireThat(batch.sourceId === sourceId && batch.model === model,
        "IDEMPOTENCY_CONFLICT", "Key already used with different parameters");
      return batch;
    }
    const from = this.state.checkpoints.get(scoped(actor.tenantId, sourceId, model)) ?? 0;
    const batch: Batch = { id: randomUUID(), tenantId: actor.tenantId, sourceId, model, idempotencyKey,
      from, cursor: from, snapshotAt: this.clock.now().toISOString(), accepted: [], duplicates: [],
      processed: [], failures: [], state: "pending", expiresAt: after(this.clock, this.config.operationalTtlMs) };
    this.state.batches.set(batch.id, batch);
    this.state.idempotency.set(key, batch.id);
    return batch;
  }
  checkpoint(batch: Batch, next: number, done: boolean): void {
    requireThat(next >= batch.cursor, "BAD_CHECKPOINT", "Checkpoint cannot move backwards");
    batch.cursor = next;
    const key = scoped(batch.tenantId, batch.sourceId, batch.model);
    this.state.checkpoints.set(key, Math.max(this.state.checkpoints.get(key) ?? 0, next));
    if (done) batch.state = batch.failures.length ? "partial" : "complete";
  }
}
