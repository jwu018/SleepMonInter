"use server";

// Server Actions: functions that run on the server but can be called straight from a
// <form>. The password goes browser -> our server -> Supabase over HTTPS, and it's never
// stored or logged by our code.

import { redirect } from "next/navigation";
import { safeNext } from "@/lib/safe-next";
import { createClient } from "@/lib/supabase/server";

export interface AuthFormState {
  error: string | null;
  message: string | null;
}

const MIN_PASSWORD_LENGTH = 8;

function readCredentials(formData: FormData) {
  return {
    email: String(formData.get("email") ?? "").trim(),
    password: String(formData.get("password") ?? ""),
  };
}

export async function signIn(_prev: AuthFormState, formData: FormData): Promise<AuthFormState> {
  const { email, password } = readCredentials(formData);
  if (!email || !password) return { error: "Enter your email and password.", message: null };

  const supabase = await createClient();
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) {
    // Same message for "no such user" and "wrong password", so the form can't be used to
    // discover which emails have accounts.
    return { error: "Incorrect email or password.", message: null };
  }
  redirect(safeNext(formData.get("next")));
}

export async function signUp(_prev: AuthFormState, formData: FormData): Promise<AuthFormState> {
  const { email, password } = readCredentials(formData);
  if (!email) return { error: "Enter an email address.", message: null };
  if (password.length < MIN_PASSWORD_LENGTH) {
    return { error: `Use a password of at least ${MIN_PASSWORD_LENGTH} characters.`, message: null };
  }

  const supabase = await createClient();
  const { data, error } = await supabase.auth.signUp({ email, password });
  if (error) return { error: error.message, message: null };

  // With "Confirm email" turned off in Supabase, sign-up logs the user in immediately.
  // If it's ever turned back on, there's no session yet, so tell them to check their inbox.
  if (!data.session) {
    return { error: null, message: "Check your email to confirm your account, then sign in." };
  }
  redirect("/");
}

export async function signOut(): Promise<void> {
  const supabase = await createClient();
  await supabase.auth.signOut();
  redirect("/login");
}
