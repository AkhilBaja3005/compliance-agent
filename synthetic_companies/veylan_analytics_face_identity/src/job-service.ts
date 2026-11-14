import { randomUUID } from "node:crypto";
import type { ExpansionJob, ModelId, Principal } from "./domain.js";
import type { JobQueue } from "./ports.js";
import type { BatchService } from "./batch-service.js";
import { ProductState } from "./state.js";
import { tenantOwned } from "./auth.js";
import { requireThat, structuredError } from "./errors.js";
import type { AuditLog } from "./audit.js";

export class JobService {
  constructor(private state: ProductState, private batches: BatchService,
    private queue: JobQueue, private audit: AuditLog) {}
  async enqueue(actor: Principal, sourceId: string, model: ModelId, key: string): Promise<ExpansionJob> {
    const batch = this.batches.open(actor, sourceId, model, key);
    let job = [...this.state.jobs.values()].find(j => j.tenantId === actor.tenantId && j.batchId === batch.id);
    if (!job) {
      job = { id: randomUUID(), tenantId: actor.tenantId, batchId: batch.id, sourceId, model,
        attempts: 0, state: "queued", expiresAt: batch.expiresAt };
      this.state.jobs.set(job.id, job);
      this.audit.emit(actor, "expansion.queued", job.id, { sourceId, model });
    }
    if (job.state === "queued") {
      try {
        await this.queue.send(JSON.stringify({ version: 1, tenantId: actor.tenantId, jobId: job.id }));
        job.error = undefined;
      } catch (error) {
        job.error = structuredError(error);
        // Caller can retry the same key; persisted job is not lost if send fails.
        throw error;
      }
    }
    return structuredClone(job);
  }
  inspect(actor: Principal, jobId: string): ExpansionJob {
    return structuredClone(tenantOwned(this.state.jobs.get(jobId), actor.tenantId));
  }
  cancel(actor: Principal, jobId: string): void {
    requireThat(actor.role === "admin" || actor.role === "operator", "FORBIDDEN", "Cancellation denied");
    const job = tenantOwned(this.state.jobs.get(jobId), actor.tenantId);
    if (["completed", "cancelled", "dead_letter"].includes(job.state)) return;
    job.state = "cancelled";
    this.state.batches.get(job.batchId)!.state = "cancelled";
    this.audit.emit(actor, "expansion.cancelled", job.id);
  }
}
