import { ProductError, infrastructureError } from "../errors.js";

export async function withDeadline<T>(ms: number, operation: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new ProductError("INFRASTRUCTURE_TIMEOUT", "Infrastructure deadline exceeded", true));
    }, ms);
  });
  try { return await Promise.race([operation(controller.signal), timeout]); }
  catch (error) { throw error instanceof ProductError ? error : infrastructureError(error); }
  finally { clearTimeout(timer); }
}
