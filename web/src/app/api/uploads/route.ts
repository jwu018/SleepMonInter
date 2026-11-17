import { getCurrentUser } from "@/lib/auth";
import { forwardUpload, serverUploadsEnabled, STUDY_CODE } from "@/lib/data/serverUpload";

// POST /api/uploads  (multipart form: file, study_code, utc_offset_hours, replace)
// The browser sends the device file here. After checking the login session, this handler
// passes it on to the FastAPI backend and returns the backend's answer unchanged:
//   201 { recording_id, status, report }   accepted, processing has started
//   422 { detail: report }                 the file failed validation
//   409 { detail: "... already exists" }   same patient and date; resend with replace=true

export async function POST(request: Request) {
  if (!(await getCurrentUser())) {
    return Response.json({ detail: "not signed in" }, { status: 401 });
  }
  if (!serverUploadsEnabled()) {
    return Response.json({ detail: "server uploads are not enabled on this site" }, { status: 503 });
  }

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return Response.json({ detail: "expected a multipart form" }, { status: 400 });
  }
  const file = form.get("file");
  const studyCode = form.get("study_code");
  if (!(file instanceof File) || typeof studyCode !== "string" || !STUDY_CODE.test(studyCode)) {
    return Response.json({ detail: "a file and a valid study_code are required" }, { status: 400 });
  }

  try {
    const upstream = await forwardUpload(form);
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "application/json" },
    });
  } catch {
    return Response.json({ detail: "the processing server could not be reached" }, { status: 502 });
  }
}
