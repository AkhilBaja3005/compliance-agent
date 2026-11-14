import type { Source, ModelId } from "./domain.js";
import type { LocalAuthority } from "./auth.js";
import type { SourceService } from "./source-service.js";
import type { JobService } from "./job-service.js";
import type { SearchService } from "./search-service.js";
import type { ExpansionScheduler } from "./scheduler.js";
import type { AuditLog } from "./audit.js";

// Application facade, intentionally no HTTP listener or public authentication endpoint.
export class ProductApi {
  constructor(private auth: LocalAuthority, private sources: SourceService, private jobs: JobService,
    private searchService: SearchService, private scheduler: ExpansionScheduler, private audit: AuditLog) {}
  admitSource(principalId: string, input: Omit<Source, "tenantId" | "status">) {
    return this.sources.admit(this.auth.resolve(principalId, ["admin"]), input);
  }
  suspendSource(principalId: string, sourceId: string): void {
    this.sources.suspend(this.auth.resolve(principalId, ["admin"]), sourceId);
  }
  enqueueExpansion(principalId: string, sourceId: string, model: ModelId, idempotencyKey: string) {
    return this.jobs.enqueue(this.auth.resolve(principalId, ["admin", "operator"]), sourceId, model, idempotencyKey);
  }
  cancelJob(principalId: string, jobId: string): void {
    this.jobs.cancel(this.auth.resolve(principalId, ["admin", "operator"]), jobId);
  }
  jobStatus(principalId: string, jobId: string) {
    return this.jobs.inspect(this.auth.resolve(principalId, ["admin", "operator", "viewer"]), jobId);
  }
  search(principalId: string, query: { imageToken: string; model: ModelId; limit: number }) {
    return this.searchService.search(this.auth.resolve(principalId, ["admin", "operator", "viewer"]), query);
  }
  scheduleExpansion(principalId: string, model: ModelId = "synthetic-v1") {
    return this.scheduler.tick(this.auth.resolve(principalId, ["admin"]), model);
  }
  auditEvents(principalId: string) {
    return this.audit.list(this.auth.resolve(principalId, ["admin"]).tenantId);
  }
}
