"use client";

import Link from "next/link";
import { useActionState } from "react";
import type { AuthFormState } from "@/lib/auth-actions";

// One form for both sign-in and sign-up. useActionState runs the server action, keeps
// the result (error/message) to show, and tells us when it's still pending.

const initialState: AuthFormState = { error: null, message: null };

interface Props {
  mode: "signin" | "signup";
  action: (prev: AuthFormState, formData: FormData) => Promise<AuthFormState>;
  next?: string;
}

export function AuthForm({ mode, action, next }: Props) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const isSignUp = mode === "signup";

  return (
    <form action={formAction} className="space-y-4">
      {next && <input type="hidden" name="next" value={next} />}
      <label className="block space-y-1">
        <span className="text-sm font-medium">Email</span>
        <input
          name="email"
          type="email"
          required
          autoComplete="email"
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
        />
      </label>
      <label className="block space-y-1">
        <span className="text-sm font-medium">Password</span>
        <input
          name="password"
          type="password"
          required
          minLength={isSignUp ? 8 : undefined}
          autoComplete={isSignUp ? "new-password" : "current-password"}
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
        />
        {isSignUp && <span className="text-xs text-muted">At least 8 characters.</span>}
      </label>

      {state.error && (
        <p role="alert" className="rounded-md border border-status-warning/60 bg-status-warning/10 px-3 py-2 text-sm">
          {state.error}
        </p>
      )}
      {state.message && <p className="rounded-md bg-surface px-3 py-2 text-sm">{state.message}</p>}

      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-md bg-accent px-4 py-2 text-sm font-medium text-background disabled:opacity-60"
      >
        {pending ? "Please wait…" : isSignUp ? "Create account" : "Sign in"}
      </button>

      <p className="text-center text-sm text-muted">
        {isSignUp ? (
          <>
            Already have an account?{" "}
            <Link href="/login" className="text-accent hover:underline">
              Sign in
            </Link>
          </>
        ) : (
          <>
            New here?{" "}
            <Link href="/signup" className="text-accent hover:underline">
              Create an account
            </Link>
          </>
        )}
      </p>
    </form>
  );
}
