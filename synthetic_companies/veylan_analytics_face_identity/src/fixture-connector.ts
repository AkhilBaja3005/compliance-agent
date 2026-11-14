import type { Source, SyntheticFace } from "./domain.js";
import type { SourceConnector } from "./ports.js";
import { requireThat } from "./errors.js";

export class FixtureConnector implements SourceConnector {
  private sets: Record<string, SyntheticFace[]>;
  constructor(sets: Record<string, SyntheticFace[]>) {
    this.sets = structuredClone(sets);
    for (const records of Object.values(this.sets)) {
      requireThat(records.every((r, i) => Number.isFinite(Date.parse(r.availableAt)) &&
        (i === 0 || Date.parse(records[i - 1].availableAt) <= Date.parse(r.availableAt))),
      "BAD_CATALOG", "Append-only fixtures must be ordered by availability");
    }
  }
  page(source: Source, cursor: number, snapshotAt: string, limit: number) {
    const all = this.sets[source.lineage.fixtureSet];
    requireThat(all, "UNKNOWN_FIXTURE_SET", "Fixture set does not exist");
    const visible = all.filter(r => Date.parse(r.availableAt) <= Date.parse(snapshotAt));
    requireThat(Number.isInteger(cursor) && cursor >= 0 && cursor <= visible.length && limit > 0,
      "BAD_CURSOR", "Invalid fixture cursor");
    const items = visible.slice(cursor, cursor + limit);
    const next = cursor + items.length;
    // Returns every discovered fixture, including records with enrolled=false.
    return { items: structuredClone(items), next, done: next === visible.length };
  }
}
