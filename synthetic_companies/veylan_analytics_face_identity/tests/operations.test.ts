import { test } from "node:test";
import assert from "node:assert/strict";
import { loadCatalog } from "../src/fixture-loader.js";
import { createProduct } from "../src/composition.js";
import { FixedClock } from "../src/clock.js";
import { MemoryBlobStore } from "../src/adapters/memory-blob.js";
import type { BlobStore } from "../src/ports.js";
import { ProductError } from "../src/errors.js";
import { commercialDefaults } from "../src/config.js";

test("partial-page retry, within-batch duplicates, and repeated idempotency keys preserve cardinality", async () => {
  const clock = new FixedClock();
  const underlying = new MemoryBlobStore(clock);
  let fail = true;
  const blobs: BlobStore = {
    put: async (tenant, key, face, expires) => {
      if (face.id === "web-002" && fail) { fail = false; throw new ProductError("SIMULATED_STORAGE", "Fixture failure", true); }
      await underlying.put(tenant, key, face, expires);
    },
    get: (tenant, key) => underlying.get(tenant, key),
    delete: (tenant, key) => underlying.delete(tenant, key),
  };
  const p = createProduct(await loadCatalog(), { clock, blobs });
  const first = await p.api.enqueueExpansion("north-ops", "web-north", "synthetic-v1", "s06");
  await p.worker.runOnce();
  assert.equal(p.state.records.size, 1);
  assert.equal(p.state.batches.get(first.batchId)!.cursor, 0);
  assert.equal(p.api.jobStatus("north-ops", first.id).state, "retry");
  assert.equal(await p.worker.runOnce(), false);
  clock.advance(5000);
  await p.worker.runOnce();
  assert.equal(p.api.jobStatus("north-ops", first.id).attempts, 2);
  assert.equal(p.api.jobStatus("north-ops", first.id).state, "completed");
  assert.equal(p.state.records.size, 2);
  assert.equal(p.index.list("north", "synthetic-v1").length, 2);
  assert.equal(p.state.batches.get(first.batchId)!.duplicates.length, 1);
  const same = await p.api.enqueueExpansion("north-ops", "web-north", "synthetic-v1", "s06");
  assert.equal(same.id, first.id);
  assert.equal(await p.worker.runOnce(), false);
  const next = await p.api.enqueueExpansion("north-ops", "web-north", "synthetic-v1", "s06-next");
  await p.worker.runOnce();
  assert.equal(p.state.batches.get(next.batchId)!.accepted.length, 0);
  await assert.rejects(p.api.enqueueExpansion("north-ops", "cctv-north", "synthetic-v1", "s06"),
    { code: "IDEMPOTENCY_CONFLICT" });
});

test("suspension stops queued work and removes an already cached source from search", async () => {
  const p = createProduct(await loadCatalog());
  await p.api.enqueueExpansion("north-ops", "web-north", "synthetic-v1", "before-stop");
  await p.worker.runOnce();
  const query = { imageToken: "synthetic:web_alpha", model: "synthetic-v1" as const, limit: 1 };
  assert.equal(p.api.search("north-ops", query).length, 1);
  const pending = await p.api.enqueueExpansion("north-ops", "web-north", "synthetic-v2", "s07");
  p.api.suspendSource("north-admin", "web-north");
  await p.worker.runOnce();
  assert.equal(p.api.jobStatus("north-ops", pending.id).state, "cancelled");
  assert.equal(p.index.list("north", "synthetic-v2").length, 0);
  assert.equal(p.api.search("north-ops", query).length, 0);
  await assert.rejects(p.api.enqueueExpansion("north-ops", "web-north", "synthetic-v1", "after-stop"),
    { code: "SOURCE_SUSPENDED" });
  assert.throws(() => p.api.suspendSource("north-ops", "cctv-north"), { code: "FORBIDDEN" });
});

test("explicit cancellation and retry exhaustion reach terminal states", async () => {
  const clock = new FixedClock();
  const blobs: BlobStore = {
    put: async () => { throw new ProductError("SIMULATED_TIMEOUT", "Fixture failure", true); },
    get: async () => undefined,
    delete: async () => {},
  };
  const p = createProduct(await loadCatalog(), { clock, blobs });
  const cancelled = await p.api.enqueueExpansion("north-ops", "web-north", "synthetic-v1", "cancel");
  p.api.cancelJob("north-ops", cancelled.id);
  await p.worker.runOnce();
  assert.equal(p.api.jobStatus("north-ops", cancelled.id).state, "cancelled");
  const job = await p.api.enqueueExpansion("north-ops", "cctv-north", "synthetic-v1", "exhaust");
  for (let attempt = 0; attempt < commercialDefaults.maxAttempts; attempt++) {
    await p.worker.runOnce();
    clock.advance(5000);
  }
  assert.equal(p.api.jobStatus("north-ops", job.id).state, "dead_letter");
  assert.equal(p.api.jobStatus("north-ops", job.id).attempts, 3);
  assert.equal(p.state.records.size, 0);
});

test("expiry removes searchable features, stored fixtures, and operational metadata", async () => {
  const clock = new FixedClock();
  const blobs = new MemoryBlobStore(clock);
  const p = createProduct(await loadCatalog(), { clock, blobs });
  await p.api.enqueueExpansion("north-ops", "enroll-north", "synthetic-v1", "expiry");
  await p.worker.runOnce();
  const record = [...p.state.records.values()][0];
  p.api.search("north-ops", { imageToken: "synthetic:enrolled_alpha", model: "synthetic-v1", limit: 1 });
  clock.advance(commercialDefaults.recordTtlMs + 1);
  assert.equal(p.api.search("north-ops", { imageToken: "synthetic:enrolled_alpha", model: "synthetic-v1", limit: 1 }).length, 0);
  await p.retention.sweep();
  assert.equal(p.state.records.size, 0);
  assert.equal(p.index.list("north", "synthetic-v1").length, 0);
  assert.equal(await blobs.get("north", record.blobKey), undefined);
  assert.equal(p.state.jobs.size, 0);
  assert.equal(p.state.batches.size, 0);
});
