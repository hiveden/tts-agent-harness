import { handleError } from "../../../../_http";

export async function GET(
  _req: Request,
  {
    params,
  }: {
    params: Promise<{ id: string; cid: string; takeId: string }>;
  },
) {
  try {
    await params; // consume
    return new Response(
      JSON.stringify({ error: "not_implemented", message: "audio served from MinIO via FastAPI" }),
      { status: 501, headers: { "content-type": "application/json" } },
    );
  } catch (e) {
    return handleError(e);
  }
}
