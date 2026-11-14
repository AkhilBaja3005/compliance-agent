import type { BlobStore } from "../ports.js";
import type { SyntheticFace } from "../domain.js";
import type { Clock } from "../clock.js";
import { encodeBlob, decodeBlob, objectKey } from "../codec.js";

export class MemoryBlobStore implements BlobStore {
  private objects = new Map<string, { body: string; expiry: number }>();
  constructor(private clock: Clock) {}
  private prune(): void {
    for (const [key, value] of this.objects) {
      if (value.expiry <= this.clock.now().getTime()) this.objects.delete(key);
    }
  }
  async put(tenantId: string, key: string, value: SyntheticFace, expiresAt: string): Promise<void> {
    this.prune();
    this.objects.set(objectKey(tenantId, key), { body: encodeBlob(value, expiresAt), expiry: Date.parse(expiresAt) });
  }
  async get(tenantId: string, key: string): Promise<SyntheticFace | undefined> {
    this.prune();
    const value = this.objects.get(objectKey(tenantId, key));
    return value ? decodeBlob(value.body, this.clock.now()) : undefined;
  }
  async delete(tenantId: string, key: string): Promise<void> {
    this.objects.delete(objectKey(tenantId, key));
  }
}
