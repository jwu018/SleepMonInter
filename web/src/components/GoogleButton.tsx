"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

// "Continue with Google". The flow (OAuth with PKCE):
//   1. This button asks Supabase for Google's sign-in URL and sends the browser there.
//   2. The user signs in at Google, which redirects to Supabase, which redirects to our
//      /auth/callback route with a one-time `code`.
//   3. /auth/callback swaps the code for a session cookie, then sends the user on to `next`.
// Our app never sees the user's Google password.
export function GoogleButton({ next = "/" }: { next?: string }) {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleClick() {
    setPending(true);
    setError(null);
    const supabase = createClient();
    const callback = new URL("/auth/callback", window.location.origin);
    callback.searchParams.set("next", next);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: callback.toString() },
    });
    // On success the browser is already navigating away; we only get here on failure.
    if (error) {
      setError("Google sign-in isn't available right now.");
      setPending(false);
    }
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={handleClick}
        disabled={pending}
        className="w-full rounded-md border border-border bg-background px-4 py-2 text-sm font-medium hover:bg-surface disabled:opacity-60"
      >
        {pending ? "Redirecting to Google…" : "Continue with Google"}
      </button>
      {error && <p role="alert" className="text-sm text-muted">{error}</p>}
    </div>
  );
}
