import type { Batch, ExpansionJob, FaceRecord, Source } from "./domain.js";

export const scoped = (...parts: string[]): string => JSON.stringify(parts);
// Single-process state: mutations run under the worker's process-wide lease.
export class ProductState {
  sources = new Map<string, Source>();
  records = new Map<string, FaceRecord>();
  digests = new Map<string, string>();
  batches = new Map<string, Batch>();
  jobs = new Map<string, ExpansionJob>();
  idempotency = new Map<string, string>();
  checkpoints = new Map<string, number>();
  lastScheduled = new Map<string, number>();
  workerBusy = false;
  revision = new Map<string, number>();
  changed(tenantId: string): void {
    this.revision.set(tenantId, (this.revision.get(tenantId) ?? 0) + 1);
  }
}
