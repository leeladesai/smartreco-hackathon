"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AuthShell } from "@/components/AuthShell";
import { apiFetch, ApiError } from "@/lib/api";
import { Field, PrimaryButton, ErrorBanner, LockNote } from "@/components/ui";

interface SignupResponse {
  tenant_id: number;
  email: string;
  status: string;
}

export default function SignupPage() {
  const router = useRouter();
  const [companyName, setCompanyName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await apiFetch<SignupResponse>("/api/auth/signup", {
        method: "POST",
        body: { company_name: companyName, email, password },
      });
      router.push(`/signup/confirmation?email=${encodeURIComponent(email)}`);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not create your account. Check your connection and try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthShell>
      <p className="mb-2 font-mono text-[10.5px] tracking-[0.16em] text-rose uppercase">Get started</p>
      <h1 className="mb-2 text-xl tracking-tight">Create your TrailMind account</h1>
      <p className="mb-[26px] text-[13px] leading-relaxed text-muted">
        One account per company. You&rsquo;ll be the first admin for your tenant and can invite teammates once you&rsquo;re
        in.
      </p>

      {error && <ErrorBanner>{error}</ErrorBanner>}

      <form onSubmit={handleSubmit}>
        <Field
          id="signup-company"
          label="Company name"
          required
          value={companyName}
          onChange={(e) => setCompanyName(e.target.value)}
          placeholder="e.g. ICICI Bank"
        />
        <Field
          id="signup-email"
          label="Work email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
        />
        <div className="grid grid-cols-2 gap-3.5">
          <Field
            id="signup-password"
            label="Password"
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
          />
          <Field
            id="signup-confirm"
            label="Confirm password"
            type="password"
            required
            minLength={8}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            autoComplete="new-password"
          />
        </div>
        <PrimaryButton type="submit" disabled={submitting} className="w-full">
          {submitting ? "Creating account…" : "Create account"}
        </PrimaryButton>
      </form>

      <LockNote>
        Your account will need approval before you can log in. We&rsquo;ll email you once TrailMind reviews it &mdash;
        usually within one business day.
      </LockNote>

      <p className="mt-[18px] text-center text-xs text-muted">
        Already have an account?{" "}
        <Link href="/login" className="text-text underline">
          Log in
        </Link>
      </p>
    </AuthShell>
  );
}
