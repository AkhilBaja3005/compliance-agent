import type { Candidate, ModelId, Principal } from "./domain.js";
import type { Clock } from "./clock.js";
import { ProductState, scoped } from "./state.js";
import { IdentityIndex, simulatedScore } from "./identity-index.js";
import { SearchCache } from "./search-cache.js";
import { digestToken, syntheticVector } from "./features.js";
import { requireThat } from "./errors.js";
import { modelSpec } from "./models.js";
import type { AuditLog } from "./audit.js";

export class SearchService {
  constructor(private state: ProductState, private index: IdentityIndex, private cache: SearchCache,
    private audit: AuditLog, private clock: Clock) {}
  search(actor: Principal, query: { imageToken: string; model: ModelId; limit: number }): Candidate[] {
    requireThat(["admin", "operator", "viewer"].includes(actor.role), "FORBIDDEN", "Search denied");
    modelSpec(query.model);
    requireThat(Number.isInteger(query.limit) && query.limit >= 1 && query.limit <= 20,
      "BAD_QUERY", "Limit must be an integer between 1 and 20");
    const vector = syntheticVector(query.imageToken, query.model);
    const key = this.cache.key(actor.tenantId, query.model, this.state.revision.get(actor.tenantId) ?? 0,
      digestToken(query.imageToken), query.limit);
    let candidates = this.cache.get(key);
    if (!candidates) {
      const ranked: { candidate: Candidate; expiry: number }[] = [];
      // Searches the same index populated by all enabled acquisition paths.
      for (const f of this.index.list(actor.tenantId, query.model)) {
        const record = this.state.records.get(scoped(actor.tenantId, f.recordId));
        const source = this.state.sources.get(scoped(actor.tenantId, f.sourceId));
        if (!record || source?.status !== "active" || Date.parse(record.expiresAt) <= this.clock.now().getTime()) continue;
        ranked.push({ expiry: Date.parse(record.expiresAt), candidate: {
          subjectRef: record.subjectRef, score: simulatedScore(vector, f.vector),
          provenance: { tenantId: actor.tenantId, sourceId: source.id, sourceType: source.type,
            sourceRecordId: record.sourceRecordId, recordId: record.id, featureId: f.id,
            model: f.model, fixtureSet: source.lineage.fixtureSet },
        } });
      }
      ranked.sort((a, b) => b.candidate.score - a.candidate.score ||
        a.candidate.provenance.recordId.localeCompare(b.candidate.provenance.recordId));
      const selected = ranked.slice(0, query.limit);
      candidates = selected.map(x => x.candidate);
      this.cache.set(key, candidates, Math.min(...selected.map(x => x.expiry)));
    }
    this.audit.emit(actor, "identity.searched", query.model, { candidateCount: candidates.length });
    return candidates;
  }
}
