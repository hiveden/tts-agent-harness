import { getServices } from "@/lib/factory";
import { handleError } from "../../../_http";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const { runner } = getServices();
    const result = await runner.run(id);
    return Response.json(result);
  } catch (e) {
    return handleError(e);
  }
}
