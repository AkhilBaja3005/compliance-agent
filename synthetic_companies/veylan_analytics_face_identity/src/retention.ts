import type { ProductState } from "./state.js";
import { scoped } from "./state.js";
import type { IdentityIndex } from "./identity-index.js";
import type { BlobStore } from "./ports.js";
import type { Clock } from "./clock.js";
import type { AuditLog } from "./audit.js";
import type { SearchCache } from "./search-cache.js";

export class RetentionService {
  constructor(private state: ProductState, private index: IdentityIndex, private blobs: BlobStore,
    private audit: AuditLog, private cache: SearchCache, private clock: Clock) {}
  async sweep(): Promise<void> {
    // Hold the same process-local lease across awaited deletes and state cleanup.
    if (this.state.workerBusy) return;
    this.state.workerBusy = true;
    try {
      const now = this.clock.now().getTime();
      for (const [key, record] of this.state.records) {
        if (Date.parse(record.expiresAt) > now) continue;
        await this.blobs.delete(record.tenantId, record.blobKey);
        this.index.removeRecord(record.tenantId, record.id);
        this.state.records.delete(key);
        const digestKey = scoped(record.tenantId, record.digest);
        if (this.state.digests.get(digestKey) === record.id) this.state.digests.delete(digestKey);
        this.state.changed(record.tenantId);
      }
      for (const [id, job] of this.state.jobs) {
        if (Date.parse(job.expiresAt) <= now) this.state.jobs.delete(id);
      }
      for (const [id, batch] of this.state.batches) {
        if (Date.parse(batch.expiresAt) > now) continue;
        this.state.batches.delete(id);
        this.state.idempotency.delete(scoped(batch.tenantId, batch.idempotencyKey));
      }
      this.audit.prune();
      this.cache.prune();
    } finally { this.state.workerBusy = false; }
  }
}
