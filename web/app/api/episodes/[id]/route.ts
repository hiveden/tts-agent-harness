import { getServices } from "@/lib/factory";
import { handleError } from "../../_http";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const { episodes } = getServices();
    const ep = await episodes.get(id);
    if (!ep) {
      return new Response(
        JSON.stringify({ error: "not_found" }),
        { status: 404, headers: { "content-type": "application/json" } },
      );
    }
    return Response.json(ep);
  } catch (e) {
    return handleError(e);
  }
}
