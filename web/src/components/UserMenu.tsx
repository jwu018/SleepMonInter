import Link from "next/link";
import { getCurrentUser } from "@/lib/auth";
import { signOut } from "@/lib/auth-actions";

// Header corner: who's signed in, plus a sign-out button. It reads the session cookie,
// so the layout renders it inside <Suspense> (keeps the rest of the header static).
export async function UserMenu() {
  const user = await getCurrentUser();
  if (!user) {
    return (
      <Link href="/login" className="text-sm hover:underline">
        Sign in
      </Link>
    );
  }
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="hidden text-muted sm:inline">{user.email}</span>
      <form action={signOut}>
        <button type="submit" className="rounded-md border border-border px-2.5 py-1 hover:bg-surface">
          Sign out
        </button>
      </form>
    </div>
  );
}
