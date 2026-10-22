import "server-only";

export interface User {
  id: string;
  email: string;
}

/**
 * Returns the logged-in user, or sends the visitor to /login.
 *
 * TEMPORARY PLACEHOLDER: real Supabase Auth replaces this body in the next step.
 * Every data function already calls it, so swapping it in protects all data at once.
 *
 * Until then it refuses to run on Vercel (VERCEL=1 is set there automatically), so an
 * accidental deploy can't serve data without a login.
 */
export async function requireUser(): Promise<User> {
  if (process.env.VERCEL) {
    throw new Error("Authentication is not configured yet; refusing to serve data.");
  }
  return { id: "local-dev", email: "dev@localhost" };
}
