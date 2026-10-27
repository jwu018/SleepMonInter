import { NextResponse } from "next/server";
import { safeNext } from "@/lib/safe-next";
import { createClient } from "@/lib/supabase/server";

// GET /auth/callback?code=...&next=/somewhere
// Where Google sign-in lands. Exchanges the one-time code for a session (stored as
// cookies), then redirects. The code only works together with a secret "verifier" cookie
// that this browser saved before leaving for Google (PKCE), so a stolen code is useless.
export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const next = safeNext(url.searchParams.get("next"));

  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(new URL(next, url.origin));
    }
    // Server-side log only (shows in the `npm run dev` terminal / Vercel logs), so a failed
    // Google login says why instead of failing silently.
    console.error("Google sign-in: code exchange failed:", error.message);
  } else {
    console.error("Google sign-in: callback reached without a code");
  }
  return NextResponse.redirect(new URL("/login?error=oauth", url.origin));
}
