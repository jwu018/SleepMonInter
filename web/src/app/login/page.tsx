import { Suspense } from "react";
import { AuthForm } from "@/components/AuthForm";
import { Divider } from "@/components/Divider";
import { GoogleButton } from "@/components/GoogleButton";
import { signIn } from "@/lib/auth-actions";
import { safeNext } from "@/lib/safe-next";

export default function LoginPage({ searchParams }: PageProps<"/login">) {
  return (
    <section className="mx-auto max-w-sm space-y-6 pt-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
        <p className="text-sm text-muted">Sign in to view overnight recordings.</p>
      </div>
      {/* searchParams is request data, so it's read inside a Suspense boundary. */}
      <Suspense fallback={null}>
        <LoginOptions searchParams={searchParams} />
      </Suspense>
    </section>
  );
}

async function LoginOptions({ searchParams }: { searchParams: PageProps<"/login">["searchParams"] }) {
  const { next, error } = await searchParams;
  const target = safeNext(next);
  return (
    <div className="space-y-6">
      {error === "oauth" && (
        <p role="alert" className="rounded-md border border-status-warning/60 bg-status-warning/10 px-3 py-2 text-sm">
          Google sign-in didn&apos;t complete. Please try again.
        </p>
      )}
      <GoogleButton next={target} />
      <Divider label="or with email" />
      <AuthForm mode="signin" action={signIn} next={target} />
    </div>
  );
}
