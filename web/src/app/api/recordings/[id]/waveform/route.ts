import { getCurrentUser } from "@/lib/auth";
import { getWaveform } from "@/lib/data";

// GET /api/recordings/<id>/waveform?start_ms=&end_ms=&max_points=
// Called by the waveform panel each time the zoom window changes. Mirrors the
// FastAPI endpoint planned for Phase 3, so the client code won't need to change.

const DEFAULT_MAX_POINTS = 2000;
const MAX_POINTS_LIMIT = 5000;

export async function GET(
  request: Request,
  ctx: RouteContext<"/api/recordings/[id]/waveform">,
) {
  // An API caller expects a status code, not a redirect to the login page.
  if (!(await getCurrentUser())) {
    return Response.json({ error: "not signed in" }, { status: 401 });
  }

  const { id } = await ctx.params;
  const params = new URL(request.url).searchParams;
  const startMs = Number(params.get("start_ms") ?? 0);
  const endMs = Number(params.get("end_ms") ?? 0);
  const maxPoints = Number(params.get("max_points") ?? DEFAULT_MAX_POINTS);

  if (
    !Number.isFinite(startMs) ||
    !Number.isFinite(endMs) ||
    startMs < 0 ||
    endMs <= startMs ||
    !Number.isInteger(maxPoints) ||
    maxPoints < 10 ||
    maxPoints > MAX_POINTS_LIMIT
  ) {
    return Response.json({ error: "invalid start_ms, end_ms or max_points" }, { status: 400 });
  }

  const window = await getWaveform(id, startMs, endMs, maxPoints);
  if (!window) {
    return Response.json({ error: "recording not found" }, { status: 404 });
  }
  return Response.json(window);
}
