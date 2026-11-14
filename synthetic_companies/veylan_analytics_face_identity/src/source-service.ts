import type { Principal, Source } from "./domain.js";
import type { ProductConfig } from "./config.js";
import { ProductState, scoped } from "./state.js";
import { tenantOwned } from "./auth.js";
import { requireThat } from "./errors.js";
import { validId } from "./codec.js";
import type { AuditLog } from "./audit.js";

export class SourceService {
  constructor(private state: ProductState, private config: ProductConfig, private audit: AuditLog) {}
  admit(actor: Principal, input: Omit<Source, "tenantId" | "status">): Source {
    requireThat(actor.role === "admin", "FORBIDDEN", "Source administration requires admin");
    requireThat(validId(input.id) && validId(input.lineage.fixtureSet), "BAD_SOURCE", "Invalid source IDs");
    requireThat(this.config.enabledSourceTypes.includes(input.type), "SOURCE_TYPE_DISABLED", "Source disabled");
    const direct = input.type === "direct_enrollment";
    requireThat(direct
      ? input.scope === "enrolled_subjects" && input.acquisitionMethod === "subject_submission"
      : input.scope === "untargeted" && input.acquisitionMethod ===
        (input.type === "public_web_bulk" ? "bulk_public_discovery" : "bulk_cctv_frames"),
    "BAD_SCOPE", "Source scope and acquisition method disagree");
    // Commercial eligibility rule: public accessibility suffices for untargeted bulk sources.
    // No requirement to restrict discovery to a list of specifically enrolled subjects.
    requireThat(direct || (this.config.publicAccessSufficientForBulk && input.publiclyAccessible),
      "ACCESS_REQUIRED", "Bulk source must be publicly accessible");
    const key = scoped(actor.tenantId, input.id);
    requireThat(!this.state.sources.has(key), "SOURCE_EXISTS", "Source already exists");
    const source: Source = { ...structuredClone(input), tenantId: actor.tenantId, status: "active" };
    this.state.sources.set(key, source);
    this.audit.emit(actor, "source.admitted", source.id, { type: source.type, scope: source.scope });
    return structuredClone(source);
  }
  get(tenantId: string, id: string): Source {
    return tenantOwned(this.state.sources.get(scoped(tenantId, id)), tenantId);
  }
  active(tenantId: string, id: string): Source {
    const source = this.get(tenantId, id);
    requireThat(source.status === "active", "SOURCE_SUSPENDED", "Source is suspended");
    return source;
  }
  suspend(actor: Principal, id: string): void {
    requireThat(actor.role === "admin", "FORBIDDEN", "Source administration requires admin");
    this.get(actor.tenantId, id).status = "suspended";
    this.state.changed(actor.tenantId);
    this.audit.emit(actor, "source.suspended", id);
  }
}
