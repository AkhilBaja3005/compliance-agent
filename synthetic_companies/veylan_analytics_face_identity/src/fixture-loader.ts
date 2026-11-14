import { readFile } from "node:fs/promises";
import type { Principal, Source, SyntheticFace } from "./domain.js";
import { requireThat } from "./errors.js";
import { validId } from "./codec.js";

export interface FixtureCatalog {
  syntheticOnly: true;
  tenants: { id: string; name: string }[];
  principals: Principal[];
  sources: Source[];
  sets: Record<string, SyntheticFace[]>;
}
// Explicit file read only; importing this module performs no I/O.
export async function loadCatalog(path: URL = new URL("../fixtures/catalog.json", import.meta.url)): Promise<FixtureCatalog> {
  requireThat(path.protocol === "file:", "LOCAL_ONLY", "Catalog must be a local file");
  const text = await readFile(path, "utf8");
  requireThat(text.length <= 100_000, "BAD_CATALOG", "Catalog too large");
  const data = JSON.parse(text) as FixtureCatalog;
  requireThat(data.syntheticOnly === true && Array.isArray(data.tenants) && Array.isArray(data.principals) &&
    Array.isArray(data.sources) && data.sets && typeof data.sets === "object", "BAD_CATALOG", "Invalid catalog");
  const tenants = new Set(data.tenants.map(t => t.id));
  const principals = new Set(data.principals.map(p => p.id));
  requireThat(tenants.size === data.tenants.length && principals.size === data.principals.length &&
    data.tenants.every(t => validId(t.id)) &&
    data.principals.every(p => validId(p.id) && tenants.has(p.tenantId) && ["admin", "operator", "viewer"].includes(p.role)) &&
    data.sources.every(s => tenants.has(s.tenantId) && Array.isArray(data.sets[s.lineage.fixtureSet])),
  "BAD_CATALOG", "Invalid tenant, principal, or source references");
  // Item validation belongs to ingestion so authored malformed items produce partial batches.
  return data;
}
