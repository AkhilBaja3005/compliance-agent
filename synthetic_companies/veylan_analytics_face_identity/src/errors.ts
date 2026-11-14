export class ProductError extends Error {
  constructor(readonly code: string, message: string, readonly retryable = false) {
    super(message); this.name = "ProductError";
  }
}
export function requireThat(condition: unknown, code: string, message: string): asserts condition {
  if (!condition) throw new ProductError(code, message);
}
export function structuredError(error: unknown): { code: string; retryable: boolean } {
  return error instanceof ProductError
    ? { code: error.code, retryable: error.retryable }
    : { code: "INTERNAL", retryable: false };
}
export function infrastructureError(error: unknown): ProductError {
  const e = error as { name?: string; code?: string; $metadata?: { httpStatusCode?: number } };
  const status = e?.$metadata?.httpStatusCode;
  const retryable = e?.name === "AbortError" || e?.name === "TimeoutError" ||
    e?.name === "ThrottlingException" || e?.code === "ECONNRESET" || e?.code === "ETIMEDOUT" ||
    e?.code === "EAI_AGAIN" || status === 429 || (status !== undefined && status >= 500);
  // Do not return provider messages, identifiers, or request bodies to callers.
  return new ProductError("INFRASTRUCTURE", "Infrastructure operation failed", retryable);
}
