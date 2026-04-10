/**
 * Shared HTTP helpers for Route Handlers.
 */

export function handleError(e: unknown): Response {
  const err = e as Error | null;
  // eslint-disable-next-line no-console
  console.error("[route]", e);
  return new Response(
    JSON.stringify({
      error: "internal",
      message: err?.message ?? "error",
    }),
    { status: 500, headers: { "content-type": "application/json" } },
  );
}
