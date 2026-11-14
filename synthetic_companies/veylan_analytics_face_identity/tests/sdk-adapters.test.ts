import { test } from "node:test";
import assert from "node:assert/strict";
import { S3Client, PutObjectCommand, GetObjectCommand, DeleteObjectCommand } from "@aws-sdk/client-s3";
import { SQSClient, SendMessageCommand, ReceiveMessageCommand, DeleteMessageCommand,
  ChangeMessageVisibilityCommand } from "@aws-sdk/client-sqs";
import { S3BlobStore } from "../src/adapters/s3-blob.js";
import { SqsJobQueue } from "../src/adapters/sqs-queue.js";
import { FixedClock } from "../src/clock.js";
import { encodeBlob } from "../src/codec.js";

// SDK-shaped injected send stubs only. No SDK client is constructed and no network is used.
test("S3 adapter scopes keys, serializes synthetic records, reads and deletes using documented commands", async () => {
  const clock = new FixedClock();
  const face = { id: "fixture-1", imageToken: "synthetic:alpha", subjectRef: "subject-a",
    enrolled: false, availableAt: "2026-11-14T11:00:00Z" };
  const expiresAt = "2026-11-15T12:00:00Z";
  const body = encodeBlob(face, expiresAt);
  const calls: unknown[] = [];
  const client = { send: async (command: unknown, options: { abortSignal: AbortSignal }) => {
    assert.equal(options.abortSignal.aborted, false);
    calls.push(command);
    if (command instanceof GetObjectCommand) return { ContentLength: body.length,
      Body: { transformToString: async () => body } };
    return {};
  } } as unknown as S3Client;
  const adapter = new S3BlobStore(client, "existing-demo-bucket", clock);
  assert.equal(calls.length, 0);
  await adapter.put("north", "record-1", face, expiresAt);
  assert.deepEqual(await adapter.get("north", "record-1"), face);
  await adapter.delete("north", "record-1");
  assert.ok(calls[0] instanceof PutObjectCommand);
  assert.equal(calls[0].input.Key, "demoface/north/record-1.json");
  assert.equal(calls[0].input.Body, body);
  assert.ok(calls[2] instanceof DeleteObjectCommand);
  const missing = new S3BlobStore({ send: async () => { throw { name: "NoSuchKey" }; } } as unknown as S3Client,
    "existing-demo-bucket", clock);
  assert.equal(await missing.get("north", "missing"), undefined);
});

test("SQS adapter sends envelopes, leases one message, retries and acknowledges with receipts", async () => {
  const calls: unknown[] = [];
  const body = JSON.stringify({ version: 1, tenantId: "north", jobId: "job-1" });
  const client = { send: async (command: unknown) => {
    calls.push(command);
    if (command instanceof ReceiveMessageCommand) return { Messages: [{ Body: body, ReceiptHandle: "receipt-1" }] };
    return {};
  } } as unknown as SQSClient;
  const adapter = new SqsJobQueue(client, "https://sqs.eu-west-1.amazonaws.com/000000000000/existing-demo");
  await adapter.send(body);
  assert.deepEqual(await adapter.receive(), { receipt: "receipt-1", body });
  await adapter.retry("receipt-1", 5);
  await adapter.ack("receipt-1");
  assert.ok(calls[0] instanceof SendMessageCommand);
  assert.equal(calls[0].input.MessageBody, body);
  assert.ok(calls[1] instanceof ReceiveMessageCommand);
  assert.equal(calls[1].input.VisibilityTimeout, 120);
  assert.ok(calls[2] instanceof ChangeMessageVisibilityCommand);
  assert.equal(calls[2].input.VisibilityTimeout, 5);
  assert.ok(calls[3] instanceof DeleteMessageCommand);
});

test("provider failure details are redacted and transient status remains retryable", async () => {
  const client = { send: async () => { throw { name: "ServiceUnavailable", message: "private provider body",
    $metadata: { httpStatusCode: 503 } }; } } as unknown as SQSClient;
  const adapter = new SqsJobQueue(client, "https://sqs.eu-west-1.amazonaws.com/000000000000/existing-demo");
  await assert.rejects(adapter.receive(), { code: "INFRASTRUCTURE", retryable: true,
    message: "Infrastructure operation failed" });
});
