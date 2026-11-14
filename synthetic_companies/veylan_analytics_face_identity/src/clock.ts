export interface Clock { now(): Date }
export class FixedClock implements Clock {
  constructor(private instant = "2026-11-14T12:00:00Z") {}
  now(): Date { return new Date(this.instant); }
  advance(ms: number): void {
    if (!Number.isFinite(ms) || ms < 0) throw new Error("Clock advances must be nonnegative");
    this.instant = new Date(this.now().getTime() + ms).toISOString();
  }
}
export const after = (clock: Clock, ms: number): string =>
  new Date(clock.now().getTime() + ms).toISOString();
