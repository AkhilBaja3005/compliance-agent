import type { FixtureCatalog } from "./fixture-loader.js";
import type { BlobStore, JobQueue } from "./ports.js";
import { FixedClock, type Clock } from "./clock.js";
import { commercialDefaults, type ProductConfig } from "./config.js";
import { ProductState } from "./state.js";
import { LocalAuthority } from "./auth.js";
import { AuditLog } from "./audit.js";
import { SourceService } from "./source-service.js";
import { FixtureConnector } from "./fixture-connector.js";
import { IdentityIndex } from "./identity-index.js";
import { SearchCache } from "./search-cache.js";
import { SearchService } from "./search-service.js";
import { BatchService } from "./batch-service.js";
import { IngestionService } from "./ingestion-service.js";
import { JobService } from "./job-service.js";
import { ExpansionWorker } from "./worker.js";
import { ExpansionScheduler } from "./scheduler.js";
import { RetentionService } from "./retention.js";
import { ProductApi } from "./api.js";
import { MemoryBlobStore } from "./adapters/memory-blob.js";
import { MemoryJobQueue } from "./adapters/memory-queue.js";
import { requireThat } from "./errors.js";

export function createProduct(catalog: FixtureCatalog, dependencies: {
  clock?: Clock; config?: ProductConfig; blobs?: BlobStore; queue?: JobQueue;
} = {}) {
  const clock = dependencies.clock ?? new FixedClock();
  const config = structuredClone(dependencies.config ?? commercialDefaults);
  const state = new ProductState();
  const authority = new LocalAuthority(catalog.principals);
  const audit = new AuditLog(clock, config.auditTtlMs);
  const blobs = dependencies.blobs ?? new MemoryBlobStore(clock);
  const queue = dependencies.queue ?? new MemoryJobQueue(clock, config.operationalTtlMs);
  const sources = new SourceService(state, config, audit);
  const connector = new FixtureConnector(catalog.sets);
  const index = new IdentityIndex(clock);
  const cache = new SearchCache(clock, config.cacheTtlMs);
  const batches = new BatchService(state, sources, clock, config);
  const ingestion = new IngestionService(state, sources, blobs, index, audit, clock, config);
  const jobs = new JobService(state, batches, queue, audit);
  const retention = new RetentionService(state, index, blobs, audit, cache, clock);
  const scheduler = new ExpansionScheduler(state, jobs, clock, config, retention);
  const search = new SearchService(state, index, cache, audit, clock);
  const worker = new ExpansionWorker(state, queue, connector, sources, batches, ingestion, clock, config, audit);
  const api = new ProductApi(authority, sources, jobs, search, scheduler, audit);
  for (const fixture of catalog.sources) {
    const admin = catalog.principals.find(p => p.tenantId === fixture.tenantId && p.role === "admin");
    requireThat(admin, "BAD_CATALOG", "Each tenant needs a trusted local admin fixture");
    const { tenantId: _tenant, status, ...input } = fixture;
    api.admitSource(admin.id, input);
    if (status === "suspended") api.suspendSource(admin.id, fixture.id);
  }
  // State/index handles are internal characterization seams; only api is an operator boundary.
  return { api, worker, clock, state, index, retention };
}
