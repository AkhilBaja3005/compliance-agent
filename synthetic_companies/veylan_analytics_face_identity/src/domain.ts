export type SourceType = "direct_enrollment" | "public_web_bulk" | "cctv_bulk";
export type ModelId = "synthetic-v1" | "synthetic-v2";
export type Role = "admin" | "operator" | "viewer";
export interface Principal { id: string; tenantId: string; role: Role }
export interface Source {
  id: string;
  tenantId: string;
  type: SourceType;
  scope: "enrolled_subjects" | "untargeted";
  acquisitionMethod: "subject_submission" | "bulk_public_discovery" | "bulk_cctv_frames";
  publiclyAccessible: boolean;
  lineage: { fixtureSet: string; upstreamLabel: string };
  status: "active" | "suspended";
  recurring: boolean;
}
export interface SyntheticFace {
  id: string;
  imageToken: string;
  subjectRef: string;
  enrolled: boolean;
  availableAt: string;
  fault?: "invalid_fixture";
}
export interface FaceRecord {
  id: string;
  tenantId: string;
  sourceId: string;
  sourceRecordId: string;
  subjectRef: string;
  digest: string;
  blobKey: string;
  createdAt: string;
  expiresAt: string;
}
export interface Feature {
  id: string;
  tenantId: string;
  recordId: string;
  sourceId: string;
  model: ModelId;
  vector: number[];
  expiresAt: string;
}
export interface Batch {
  id: string;
  tenantId: string;
  sourceId: string;
  model: ModelId;
  idempotencyKey: string;
  from: number;
  cursor: number;
  snapshotAt: string;
  accepted: string[];
  duplicates: string[];
  processed: string[];
  failures: { recordId: string; code: string }[];
  state: "pending" | "complete" | "partial" | "cancelled";
  expiresAt: string;
}
export interface ExpansionJob {
  id: string;
  tenantId: string;
  batchId: string;
  sourceId: string;
  model: ModelId;
  state: "queued" | "running" | "retry" | "completed" | "cancelled" | "dead_letter";
  attempts: number;
  error?: { code: string; retryable: boolean };
  expiresAt: string;
}
export interface JobMessage { version: 1; tenantId: string; jobId: string }
export interface Delivery { receipt: string; body: string }
export interface Candidate {
  subjectRef: string;
  score: number;
  provenance: {
    tenantId: string; sourceId: string; sourceType: SourceType;
    sourceRecordId: string; recordId: string; featureId: string;
    model: ModelId; fixtureSet: string;
  };
}
export interface AuditEvent {
  at: string; tenantId: string; actorId: string; action: string;
  resourceId: string; details: Record<string, string | number | boolean>;
}
