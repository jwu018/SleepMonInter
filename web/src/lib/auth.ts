import "server-only";

import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

export interface User {
  id: string;
  email: string;
}

/**
 * The logged-in user, or null.
 *
 * getClaims() verifies the session token's signature (it doesn't just trust the cookie),
 * which is what Supabase recommends for authorization decisions on the server.
 */
export async function getCurrentUser(): Promise<User | null> {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  if (error || !data?.claims) return null;
  return { id: data.claims.sub, email: String(data.claims.email ?? "") };
}

/**
 * The logged-in user, or a redirect to /login.
 * Every function in the data layer calls this first, so no data is ever read for a
 * visitor without a valid session, even if proxy.ts were misconfigured.
 */
export async function requireUser(): Promise<User> {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  return user;
}
