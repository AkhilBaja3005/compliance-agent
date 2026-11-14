import type { Principal, ModelId } from "./domain.js";
import { ProductState, scoped } from "./state.js";
import type { JobService } from "./job-service.js";
import type { ProductConfig } from "./config.js";
import type { Clock } from "./clock.js";
import type { RetentionService } from "./retention.js";
import { requireThat } from "./errors.js";

export class ExpansionScheduler {
  constructor(private state: ProductState, private jobs: JobService, private clock: Clock,
    private config: ProductConfig, private retention: RetentionService) {}
  async tick(actor: Principal, model: ModelId = "synthetic-v1"): Promise<string[]> {
    requireThat(actor.role === "admin", "FORBIDDEN", "Scheduling requires admin");
    await this.retention.sweep();
    if (!this.config.recurringExpansionEnabled) return [];
    const now = this.clock.now().getTime();
    const result: string[] = [];
    for (const source of this.state.sources.values()) {
      if (source.tenantId !== actor.tenantId || source.status !== "active" || !source.recurring) continue;
      const key = scoped(actor.tenantId, source.id, model);
      const last = this.state.lastScheduled.get(key);
      if (last !== undefined && now - last < this.config.expansionIntervalMs) continue;
      const slot = Math.floor(now / this.config.expansionIntervalMs);
      const job = await this.jobs.enqueue(actor, source.id, model, `expand_${source.id}_${model}_${slot}`);
      this.state.lastScheduled.set(key, now);
      result.push(job.id);
    }
    return result;
  }
}
