import { S3Client, GetObjectCommand, PutObjectCommand, DeleteObjectCommand } from "@aws-sdk/client-s3";
import type { BlobStore } from "../ports.js";
import type { SyntheticFace } from "../domain.js";
import type { Clock } from "../clock.js";
import { encodeBlob, decodeBlob, objectKey } from "../codec.js";
import { requireThat } from "../errors.js";
import { withDeadline } from "./deadline.js";

export class S3BlobStore implements BlobStore {
  constructor(private client: S3Client, private bucket: string, private clock: Clock,
    private timeoutMs = 5000) {
    requireThat(bucket.length > 0 && timeoutMs > 0, "BAD_ADAPTER_CONFIG", "Existing bucket and timeout required");
  }
  async put(tenantId: string, key: string, value: SyntheticFace, expiresAt: string): Promise<void> {
    const body = encodeBlob(value, expiresAt);
    await withDeadline(this.timeoutMs, signal => this.client.send(new PutObjectCommand({
      Bucket: this.bucket, Key: objectKey(tenantId, key), Body: body,
      ContentType: "application/json", ServerSideEncryption: "AES256",
      Metadata: { "expires-at": expiresAt, "synthetic-only": "true" },
    }), { abortSignal: signal }));
  }
  async get(tenantId: string, key: string): Promise<SyntheticFace | undefined> {
    return withDeadline(this.timeoutMs, async signal => {
      try {
        const result = await this.client.send(new GetObjectCommand({ Bucket: this.bucket,
          Key: objectKey(tenantId, key) }), { abortSignal: signal });
        requireThat(result.Body && result.ContentLength !== undefined && result.ContentLength < 16384,
          "BAD_BLOB", "Missing or oversized blob");
        return decodeBlob(await result.Body.transformToString(), this.clock.now());
      } catch (error) {
        if ((error as { name?: string })?.name === "NoSuchKey") return undefined;
        throw error;
      }
    });
  }
  async delete(tenantId: string, key: string): Promise<void> {
    await withDeadline(this.timeoutMs, signal => this.client.send(new DeleteObjectCommand({
      Bucket: this.bucket, Key: objectKey(tenantId, key),
    }), { abortSignal: signal }));
  }
}
