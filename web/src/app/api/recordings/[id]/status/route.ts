import { getCurrentUser } from "@/lib/auth";
import { fetchRecordingStatus, RECORDING_ID, serverUploadsEnabled } from "@/lib/data/serverUpload";

// GET /api/recordings/<id>/status
// Polled by the upload form every two seconds until processing finishes.

export async function GET(_request: Request, ctx: RouteContext<"/api/recordings/[id]/status">) {
  if (!(await getCurrentUser())) {
    return Response.json({ detail: "not signed in" }, { status: 401 });
  }
  const { id } = await ctx.params;
  if (!serverUploadsEnabled() || !RECORDING_ID.test(id)) {
    return Response.json({ detail: "recording not found" }, { status: 404 });
  }
  try {
    const status = await fetchRecordingStatus(id);
    return status
      ? Response.json(status)
      : Response.json({ detail: "recording not found" }, { status: 404 });
  } catch {
    return Response.json({ detail: "the processing server could not be reached" }, { status: 502 });
  }
}
