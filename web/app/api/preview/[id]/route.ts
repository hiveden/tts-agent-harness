import { handleError } from "../../_http";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    await params; // consume
    return new Response(
      JSON.stringify({ error: "not_implemented", message: "preview served from FastAPI" }),
      { status: 501, headers: { "content-type": "application/json" } },
    );
  } catch (e) {
    return handleError(e);
  }
}
