import { AuthForm } from "@/components/AuthForm";
import { Divider } from "@/components/Divider";
import { GoogleButton } from "@/components/GoogleButton";
import { signUp } from "@/lib/auth-actions";

export default function SignUpPage() {
  return (
    <section className="mx-auto max-w-sm space-y-6 pt-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Create an account</h1>
        <p className="text-sm text-muted">
          Demo accounts only see synthetic data. Don&apos;t reuse a password from another site.
        </p>
      </div>
      <GoogleButton />
      <Divider label="or with email" />
      <AuthForm mode="signup" action={signUp} />
    </section>
  );
}
