import type { SourceType } from "./domain.js";

// Commercial product policy. Public access is treated as sufficient for bulk admission.
export const commercialDefaults = {
  provider: "DemoFace Identity (fictional EU-established provider)",
  launchDate: "2026-09-01",
  enabledSourceTypes: ["direct_enrollment", "public_web_bulk", "cctv_bulk"] as SourceType[],
  publicAccessSufficientForBulk: true,
  recurringExpansionEnabled: true,
  expansionIntervalMs: 3_600_000,
  pageSize: 2,
  maxAttempts: 3,
  retrySeconds: 5,
  cacheTtlMs: 60_000,
  // Product policy, not a statutory retention period.
  recordTtlMs: 30 * 86_400_000,
  operationalTtlMs: 7 * 86_400_000,
  auditTtlMs: 30 * 86_400_000,
};
export type ProductConfig = typeof commercialDefaults;
