import { test } from "node:test";
import assert from "node:assert/strict";
import { loadCatalog } from "../src/fixture-loader.js";
import { createProduct } from "../src/composition.js";
import { FixedClock } from "../src/clock.js";

// Authored characterization tests. Success would confirm intentionally defective product behavior.
test("direct enrollment is a negative control for the specific bulk scraping pathway", async () => {
  const p = createProduct(await loadCatalog());
  await p.api.enqueueExpansion("north-ops", "enroll-north", "synthetic-v1", "s01");
  await p.worker.runOnce();
  const result = p.api.search("north-ops", { imageToken: "synthetic:enrolled_alpha", model: "synthetic-v1", limit: 1 });
  assert.equal(p.state.records.size, 1);
  assert.equal(result[0].provenance.sourceType, "direct_enrollment");
});

test("default commercial policy indexes unenrolled web/CCTV discoveries and makes them searchable", async () => {
  const p = createProduct(await loadCatalog());
  const web = await p.api.enqueueExpansion("north-ops", "web-north", "synthetic-v1", "s02");
  await p.worker.runOnce();
  const batch = p.state.batches.get(web.batchId)!;
  assert.equal(batch.state, "partial");
  assert.equal(batch.accepted.length, 2);
  assert.deepEqual(batch.duplicates, ["web-duplicate"]);
  assert.deepEqual(batch.failures, [{ recordId: "web-invalid", code: "INVALID_FIXTURE" }]);
  assert.equal(batch.cursor, 4);
  const cam = await p.api.enqueueExpansion("north-ops", "cctv-north", "synthetic-v1", "s03");
  await p.worker.runOnce();
  assert.equal(p.api.jobStatus("north-ops", cam.id).state, "completed");
  assert.equal(p.index.list("north", "synthetic-v1").length, 4);
  for (const [token, source, record] of [["web_alpha", "web-north", "web-001"], ["cam_alpha", "cctv-north", "cam-001"]]) {
    const query = { imageToken: `synthetic:${token}`, model: "synthetic-v1" as const, limit: 1 };
    const candidates = p.api.search("north-review", query);
    assert.equal(candidates[0].score, 1);
    assert.equal(candidates[0].provenance.sourceId, source);
    assert.equal(candidates[0].provenance.sourceRecordId, record);
    assert.deepEqual(p.api.search("north-review", query), candidates);
  }
});

test("recurring discovery adds a later record without replaying the old snapshot", async () => {
  const clock = new FixedClock();
  const p = createProduct(await loadCatalog(), { clock });
  assert.equal((await p.api.scheduleExpansion("north-admin")).length, 2);
  await p.worker.runOnce();
  await p.worker.runOnce();
  assert.equal(p.state.records.size, 4);
  assert.deepEqual(await p.api.scheduleExpansion("north-admin"), []);
  clock.advance(3_600_000);
  assert.equal((await p.api.scheduleExpansion("north-admin")).length, 2);
  await p.worker.runOnce();
  await p.worker.runOnce();
  assert.equal(p.state.records.size, 5);
  assert.equal(p.api.search("north-ops", { imageToken: "synthetic:web_gamma", model: "synthetic-v1", limit: 1 })[0]
    .provenance.sourceRecordId, "web-003");
});

test("tenant and model boundaries survive identical query tokens and cached searches", async () => {
  const p = createProduct(await loadCatalog());
  for (const [actor, source, model, key] of [
    ["north-ops", "web-north", "synthetic-v1", "north-v1"],
    ["south-ops", "enroll-south", "synthetic-v1", "south-v1"],
    ["north-ops", "web-north", "synthetic-v2", "north-v2"],
  ] as const) {
    await p.api.enqueueExpansion(actor, source, model, key);
    await p.worker.runOnce();
  }
  for (const model of ["synthetic-v1", "synthetic-v2"] as const) {
    const north = p.api.search("north-ops", { imageToken: "synthetic:web_alpha", model, limit: 1 });
    assert.equal(north[0].provenance.tenantId, "north");
    assert.equal(north[0].provenance.model, model);
  }
  const southQuery = { imageToken: "synthetic:web_alpha", model: "synthetic-v1" as const, limit: 1 };
  assert.equal(p.api.search("south-ops", southQuery)[0].subjectRef, "subject-south-a");
  assert.equal(p.api.search("south-ops", { ...southQuery, model: "synthetic-v2" }).length, 0);
  assert.throws(() => p.api.search("unknown-principal", southQuery), { code: "FORBIDDEN" });
  await assert.rejects(p.api.enqueueExpansion("south-ops", "web-north", "synthetic-v1", "cross-tenant"),
    { code: "NOT_FOUND" });
});
