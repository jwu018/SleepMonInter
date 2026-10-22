/**
 * Where to send someone after they sign in: only paths on this site are allowed.
 * Without this, a crafted link like /login?next=https://evil.example (or //evil.example,
 * which browsers treat as another site) would send people elsewhere after logging in.
 */
export function safeNext(value: unknown): string {
  const next = typeof value === "string" ? value : "";
  return next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";
}
