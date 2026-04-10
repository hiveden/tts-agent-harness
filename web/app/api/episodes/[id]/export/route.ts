import { handleError } from "../../../_http";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    await params; // consume
    return new Response(
      JSON.stringify({ error: "not_implemented", message: "export via FastAPI backend" }),
      { status: 501, headers: { "content-type": "application/json" } },
    );
  } catch (e) {
    return handleError(e);
  }
}
