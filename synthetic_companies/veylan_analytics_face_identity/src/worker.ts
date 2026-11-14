import type { JobQueue, SourceConnector } from "./ports.js";
import type { ProductState } from "./state.js";
import type { SourceService } from "./source-service.js";
import type { BatchService } from "./batch-service.js";
import type { IngestionService } from "./ingestion-service.js";
import type { ProductConfig } from "./config.js";
import type { Clock } from "./clock.js";
import type { AuditLog } from "./audit.js";
import { decodeMessage } from "./codec.js";
import { requireThat, structuredError } from "./errors.js";

export class ExpansionWorker {
  constructor(private state: ProductState, private queue: JobQueue, private connector: SourceConnector,
    private sources: SourceService, private batches: BatchService, private ingestion: IngestionService,
    private clock: Clock, private config: ProductConfig, private audit: AuditLog) {}
  // One bounded fixture job per call. No background timer starts on import or construction.
  async runOnce(): Promise<boolean> {
    if (this.state.workerBusy) return false;
    this.state.workerBusy = true;
    try {
      const delivery = await this.queue.receive();
      if (!delivery) return false;
      let message;
      try { message = decodeMessage(delivery.body); } catch {
        this.audit.emit({ id: "expansion-worker", tenantId: "system" }, "queue.rejected", "invalid-envelope");
        await this.queue.ack(delivery.receipt);
        return true;
      }
      const job = this.state.jobs.get(message.jobId);
      if (!job || job.tenantId !== message.tenantId || ["completed", "cancelled", "dead_letter"].includes(job.state)) {
        await this.queue.ack(delivery.receipt);
        return true;
      }
      const batch = this.state.batches.get(job.batchId)!;
      try {
        requireThat(Date.parse(job.expiresAt) > this.clock.now().getTime(), "JOB_EXPIRED", "Job expired");
        requireThat(job.attempts < this.config.maxAttempts, "RETRY_EXHAUSTED", "Retry budget exhausted");
        job.attempts += 1;
        job.state = "running";
        const assertActive = () => requireThat(job.state !== "cancelled", "JOB_CANCELLED", "Job cancelled");
        while (true) {
          assertActive();
          const source = this.sources.active(job.tenantId, job.sourceId);
          const page = this.connector.page(source, batch.cursor, batch.snapshotAt, this.config.pageSize);
          for (const face of page.items) await this.ingestion.ingestRecord(batch, face, assertActive);
          assertActive();
          this.sources.active(job.tenantId, job.sourceId);
          this.batches.checkpoint(batch, page.next, page.done);
          if (page.done) break;
        }
        job.state = "completed";
        job.error = undefined;
        this.audit.emit({ id: "expansion-worker", tenantId: job.tenantId }, "expansion.completed", job.id,
          { accepted: batch.accepted.length, duplicates: batch.duplicates.length, failures: batch.failures.length });
      } catch (error) {
        job.error = structuredError(error);
        const stopped = this.state.jobs.get(job.id)?.state === "cancelled" ||
          this.sources.get(job.tenantId, job.sourceId).status === "suspended" ||
          job.error.code === "SOURCE_SUSPENDED" || job.error.code === "JOB_CANCELLED";
        if (stopped) { job.state = "cancelled"; batch.state = "cancelled"; }
        else if (job.error.retryable && job.attempts < this.config.maxAttempts) {
          job.state = "retry";
          await this.queue.retry(delivery.receipt, this.config.retrySeconds);
          return true;
        } else job.state = "dead_letter";
        this.audit.emit({ id: "expansion-worker", tenantId: job.tenantId }, `expansion.${job.state}`, job.id,
          { errorCode: job.error.code, attempts: job.attempts });
      }
      await this.queue.ack(delivery.receipt);
      return true;
    } finally { this.state.workerBusy = false; }
  }
}
