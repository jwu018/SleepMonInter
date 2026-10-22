import { createServerClient } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

// Runs before every matching request (Next.js 16 renamed "middleware" to "proxy").
//
// Job 1: keep the login session fresh. Supabase access tokens expire after about an hour;
//        getClaims() refreshes them using the refresh token, and setAll() writes the new
//        cookies onto the response.
// Job 2: an early, *optimistic* redirect to /login for visitors with no session.
//        The real check is requireUser() in the data layer, which runs again on the server
//        before any data is read, so this file is not the only lock on the door.

const PUBLIC_PATHS = ["/login", "/signup", "/auth"];

export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet, headers) {
          // Update the request (so pages rendered after this see the new tokens) and the
          // response (so the browser stores them).
          for (const { name, value } of cookiesToSet) request.cookies.set(name, value);
          response = NextResponse.next({ request });
          for (const { name, value, options } of cookiesToSet) {
            response.cookies.set(name, value, options);
          }
          // Cache-Control etc. from Supabase: stops a CDN caching a response that sets
          // someone's login cookie and serving it to other people.
          for (const [key, value] of Object.entries(headers ?? {})) {
            response.headers.set(key, value);
          }
        },
      },
    },
  );

  // Don't put other code between creating the client and this call: it's what refreshes
  // the session, and an early return would skip writing the refreshed cookies.
  const { data } = await supabase.auth.getClaims();
  const loggedIn = Boolean(data?.claims);

  const path = request.nextUrl.pathname;
  const isPublic = PUBLIC_PATHS.some((p) => path === p || path.startsWith(`${p}/`));

  if (!loggedIn && !isPublic) {
    if (path.startsWith("/api/")) {
      return NextResponse.json({ error: "not signed in" }, { status: 401 });
    }
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.search = "";
    loginUrl.searchParams.set("next", path);
    return NextResponse.redirect(loginUrl);
  }

  return response;
}

export const config = {
  // Run on everything except Next's static files and images (no session needed for those).
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
