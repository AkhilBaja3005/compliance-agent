import { randomUUID } from "node:crypto";
import type { JobQueue } from "../ports.js";
import type { Clock } from "../clock.js";
import { decodeMessage } from "../codec.js";
import { requireThat } from "../errors.js";

interface Item { body: string; visibleAt: number; expiresAt: number; receipt?: string }
export class MemoryJobQueue implements JobQueue {
  private items: Item[] = [];
  constructor(private clock: Clock, private ttlMs: number) {}
  async send(body: string): Promise<void> {
    decodeMessage(body);
    const now = this.clock.now().getTime();
    this.items.push({ body, visibleAt: now, expiresAt: now + this.ttlMs });
  }
  async receive() {
    const now = this.clock.now().getTime();
    this.items = this.items.filter(i => i.expiresAt > now);
    const item = this.items.find(i => i.visibleAt <= now);
    if (!item) return undefined;
    item.receipt = randomUUID();
    item.visibleAt = now + 120_000;
    return { body: item.body, receipt: item.receipt };
  }
  async ack(receipt: string): Promise<void> {
    this.items = this.items.filter(i => i.receipt !== receipt);
  }
  async retry(receipt: string, delaySeconds: number): Promise<void> {
    requireThat(Number.isInteger(delaySeconds) && delaySeconds >= 0 && delaySeconds <= 900,
      "BAD_DELAY", "Invalid retry delay");
    const item = this.items.find(i => i.receipt === receipt);
    if (item) item.visibleAt = this.clock.now().getTime() + delaySeconds * 1000;
  }
}
