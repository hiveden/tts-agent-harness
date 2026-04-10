import { getServices } from "@/lib/factory";
import type { EditBatch } from "@/lib/types";
import { handleError } from "../../../_http";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const { chunks } = getServices();
    const body = await request.json();
    const edits: EditBatch = (body?.edits ?? body) as EditBatch;
    if (!edits || typeof edits !== "object") {
      return new Response(
        JSON.stringify({ error: "invalid_input", message: "edits required" }),
        { status: 400, headers: { "content-type": "application/json" } },
      );
    }
    await chunks.applyEdits(id, edits);
    return Response.json({ updated: Object.keys(edits).length });
  } catch (e) {
    return handleError(e);
  }
}
