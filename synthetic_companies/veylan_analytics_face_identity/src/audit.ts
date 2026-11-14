import type { AuditEvent, Principal } from "./domain.js";
import type { Clock } from "./clock.js";

export class AuditLog {
  private events: AuditEvent[] = [];
  constructor(private clock: Clock, private ttlMs: number) {}
  prune(): void {
    const cutoff = this.clock.now().getTime() - this.ttlMs;
    this.events = this.events.filter(e => Date.parse(e.at) > cutoff);
  }
  emit(actor: Pick<Principal, "id" | "tenantId">, action: string, resourceId: string,
    details: AuditEvent["details"] = {}): void {
    this.prune();
    this.events.push({ at: this.clock.now().toISOString(), tenantId: actor.tenantId,
      actorId: actor.id, action, resourceId, details: { ...details } });
  }
  list(tenantId: string): AuditEvent[] {
    this.prune();
    return structuredClone(this.events.filter(e => e.tenantId === tenantId));
  }
}
