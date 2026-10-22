import { createBrowserClient } from "@supabase/ssr";

// Supabase client for code running in the browser (Client Components).
// Only the URL and the publishable key are used here; both are safe to expose.
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
  );
}
