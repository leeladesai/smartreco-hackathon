"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { redirect } from "next/navigation";
import { AuthShell } from "@/components/AuthShell";

function ConfirmationContent() {
  const email = useSearchParams().get("email");

  // Only reachable right after a real signup — landing here with no ?email= (a
  // refresh, or a bookmarked link) bounces back to signup rather than showing a
  // confirmation for nothing.
  if (!email) redirect("/signup");

  return (
    <AuthShell>
      <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-good-dim text-good">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M4 10.5l4 4 8-9" stroke="currentColor" strokeWidth="1.8" />
        </svg>
      </div>
      <h1 className="mb-2 text-xl tracking-tight">Account created</h1>
      <p className="mb-0 text-[13px] leading-relaxed text-muted">
        We&rsquo;ll email <strong className="text-text">{email}</strong> the moment a TrailMind platform admin
        approves your account &mdash; no action needed until then.
      </p>
      <p className="mt-4 text-center text-xs text-muted">
        <Link href="/login" className="text-text underline">
          Back to login
        </Link>
      </p>
    </AuthShell>
  );
}

export default function AwaitingApprovalPage() {
  return (
    <Suspense fallback={null}>
      <ConfirmationContent />
    </Suspense>
  );
}
