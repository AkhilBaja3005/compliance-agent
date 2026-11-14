import type { Delivery, Source, SyntheticFace } from "./domain.js";

export interface BlobStore {
  put(tenantId: string, key: string, value: SyntheticFace, expiresAt: string): Promise<void>;
  get(tenantId: string, key: string): Promise<SyntheticFace | undefined>;
  delete(tenantId: string, key: string): Promise<void>;
}
// The transport moves opaque serialized messages; job state remains application-owned.
export interface JobQueue {
  send(body: string): Promise<void>;
  receive(): Promise<Delivery | undefined>;
  ack(receipt: string): Promise<void>;
  retry(receipt: string, delaySeconds: number): Promise<void>;
}
export interface SourceConnector {
  page(source: Source, cursor: number, snapshotAt: string, limit: number): {
    items: SyntheticFace[]; next: number; done: boolean;
  };
}
