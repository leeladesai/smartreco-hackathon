"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AuthShell } from "@/components/AuthShell";
import { useAuth } from "@/context/AuthContext";
import { ApiError } from "@/lib/api";
import { Field, PrimaryButton, ErrorBanner, LockNote } from "@/components/ui";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 403 from a pending/rejected tenant gets its own banner treatment, not the plain
  // "invalid credentials" text — see app/main.py's admin_login for the messages.
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setPending(false);
    try {
      const user = await login(email, password);
      router.replace(user.role === "platform_admin" ? "/admin/tenants" : "/admin/overview");
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setPending(true);
        setError(err.message);
      } else if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Could not log in. Check your connection and try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthShell>
      <p className="mb-2 font-mono text-[10.5px] tracking-[0.16em] text-rose uppercase">Welcome back</p>
      <h1 className="mb-2 text-xl tracking-tight">Log in</h1>
      <p className="mb-[26px] text-[13px] leading-relaxed text-muted">
        For tenant admins and TrailMind platform admins &mdash; one login for both.
      </p>

      {error && <ErrorBanner>{error}</ErrorBanner>}

      <form onSubmit={handleSubmit}>
        <Field
          id="login-email"
          label="Email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
        />
        <Field
          id="login-password"
          label="Password"
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />
        <PrimaryButton type="submit" disabled={submitting} className="w-full">
          {submitting ? "Logging in…" : "Log in"}
        </PrimaryButton>
      </form>

      {pending && (
        <LockNote>You&rsquo;ll get access as soon as your account is approved &mdash; no need to keep retrying.</LockNote>
      )}

      <p className="mt-[18px] text-center text-xs text-muted">
        New here?{" "}
        <Link href="/signup" className="text-text underline">
          Create an account
        </Link>
      </p>
    </AuthShell>
  );
}
