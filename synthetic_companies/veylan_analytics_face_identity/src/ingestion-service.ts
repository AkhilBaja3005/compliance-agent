import type { Batch, FaceRecord, SyntheticFace } from "./domain.js";
import type { Clock } from "./clock.js";
import { after } from "./clock.js";
import type { ProductConfig } from "./config.js";
import type { BlobStore } from "./ports.js";
import { ProductState, scoped } from "./state.js";
import type { SourceService } from "./source-service.js";
import type { IdentityIndex } from "./identity-index.js";
import { validateFace } from "./codec.js";
import { digestToken, extractFeature } from "./features.js";
import { ProductError, requireThat } from "./errors.js";
import type { AuditLog } from "./audit.js";

export class IngestionService {
  constructor(private state: ProductState, private sources: SourceService, private blobs: BlobStore,
    private index: IdentityIndex, private audit: AuditLog, private clock: Clock, private config: ProductConfig) {}
  async ingestRecord(batch: Batch, face: SyntheticFace, assertJobActive: () => void): Promise<void> {
    assertJobActive();
    const source = this.sources.active(batch.tenantId, batch.sourceId);
    if (batch.processed.includes(face.id)) return;
    try {
      validateFace(face);
      requireThat(source.type !== "direct_enrollment" || face.enrolled,
        "ENROLLMENT_REQUIRED", "Direct submissions must be enrolled subjects");
    } catch (error) {
      if (!(error instanceof ProductError) || !["INVALID_FIXTURE", "ENROLLMENT_REQUIRED"].includes(error.code)) throw error;
      batch.failures.push({ recordId: face.id, code: error.code });
      batch.processed.push(face.id);
      return;
    }
    // Bulk discovery accepts every valid record; face.enrolled is not a bulk admission condition.
    const digest = digestToken(face.imageToken);
    const digestKey = scoped(batch.tenantId, digest);
    const previousId = this.state.digests.get(digestKey);
    const previous = previousId ? this.state.records.get(scoped(batch.tenantId, previousId)) : undefined;
    if (previous && Date.parse(previous.expiresAt) > this.clock.now().getTime()) {
      this.index.upsert(extractFeature(previous, face.imageToken, batch.model));
      this.state.changed(batch.tenantId);
      batch.duplicates.push(face.id);
      batch.processed.push(face.id);
      return;
    }
    const id = `r_${digestToken(scoped(batch.tenantId, batch.sourceId, face.id, digest)).slice(0, 32)}`;
    const record: FaceRecord = { id, tenantId: batch.tenantId, sourceId: batch.sourceId,
      sourceRecordId: face.id, subjectRef: face.subjectRef, digest, blobKey: id,
      createdAt: this.clock.now().toISOString(), expiresAt: after(this.clock, this.config.recordTtlMs) };
    await this.blobs.put(batch.tenantId, id, face, record.expiresAt);
    try {
      assertJobActive();
      this.sources.active(batch.tenantId, batch.sourceId);
    } catch (error) {
      await this.blobs.delete(batch.tenantId, id);
      throw error;
    }
    // Synchronous local commit: record, digest, feature, and processed marker move together.
    this.state.records.set(scoped(batch.tenantId, id), record);
    this.state.digests.set(digestKey, id);
    this.index.upsert(extractFeature(record, face.imageToken, batch.model));
    this.state.changed(batch.tenantId);
    batch.accepted.push(id);
    batch.processed.push(face.id);
    this.audit.emit({ id: "expansion-worker", tenantId: batch.tenantId }, "face.indexed", id,
      { sourceId: batch.sourceId, batchId: batch.id, model: batch.model });
  }
}
