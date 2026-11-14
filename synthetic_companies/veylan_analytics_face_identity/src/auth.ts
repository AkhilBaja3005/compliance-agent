import type { Principal, Role } from "./domain.js";
import { requireThat } from "./errors.js";

export class LocalAuthority {
  private readonly registry: Map<string, Principal>;
  constructor(principals: Principal[]) {
    this.registry = new Map(principals.map(p => [p.id, { ...p }]));
  }
  // In-process demo boundary: only trusted fixture IDs, never caller-supplied tenant/role claims.
  resolve(id: string, allowed: Role[]): Principal {
    const p = this.registry.get(id);
    requireThat(p && allowed.includes(p.role), "FORBIDDEN", "Principal cannot perform operation");
    return { ...p };
  }
}
export function tenantOwned<T extends { tenantId: string }>(value: T | undefined, tenantId: string): T {
  requireThat(value && value.tenantId === tenantId, "NOT_FOUND", "Resource not found");
  return value;
}
