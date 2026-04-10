import { getServices } from "@/lib/factory";
import { handleError } from "../../../../../_http";
import type { StageName } from "@/lib/types";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; cid: string }> },
) {
  try {
    const { id, cid } = await params;
    const { runner } = getServices();
    let body: Record<string, unknown> = {};
    try {
      body = await request.json();
    } catch {
      // no body
    }
    const fromStage = (body?.from_stage as StageName) ?? "p2";
    const cascade = body?.cascade !== false;
    const result = await runner.retry(id, cid, fromStage, cascade);
    return Response.json(result);
  } catch (e) {
    return handleError(e);
  }
}
