import { getServices } from "@/lib/factory";
import { handleError } from "../_http";

export async function GET() {
  try {
    const { episodes } = getServices();
    const list = await episodes.list();
    return Response.json(list);
  } catch (e) {
    return handleError(e);
  }
}

export async function POST(request: Request) {
  try {
    const { episodes } = getServices();
    const contentType = request.headers.get("content-type") ?? "";

    if (!contentType.includes("multipart/form-data")) {
      return new Response(
        JSON.stringify({ error: "invalid_input", message: "multipart form required" }),
        { status: 400, headers: { "content-type": "application/json" } },
      );
    }

    const form = await request.formData();
    const id = (form.get("id") as string | null) ?? null;
    const file = form.get("script") as File | null;

    if (!id) {
      return new Response(
        JSON.stringify({ error: "invalid_input", message: "id required" }),
        { status: 400, headers: { "content-type": "application/json" } },
      );
    }
    if (!file) {
      return new Response(
        JSON.stringify({ error: "invalid_input", message: "script file required" }),
        { status: 400, headers: { "content-type": "application/json" } },
      );
    }

    const ep = await episodes.create(id, file);
    return Response.json(ep, { status: 201 });
  } catch (e) {
    return handleError(e);
  }
}
