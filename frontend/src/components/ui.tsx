import type { InputHTMLAttributes, ReactNode } from "react";

export function Field({
  label,
  id,
  ...inputProps
}: { label: string; id: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="mb-4">
      <label
        htmlFor={id}
        className="mb-1.5 block font-mono text-[10.5px] tracking-wide text-muted uppercase"
      >
        {label}
      </label>
      <input
        id={id}
        className="w-full rounded-md border border-line bg-panel-2 px-3 py-2.5 text-[13.5px] text-text focus:border-rose focus:outline-none"
        {...inputProps}
      />
    </div>
  );
}

export function PrimaryButton({
  children,
  className = "",
  ...props
}: { children: ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`rounded-md border border-rose bg-rose px-4 py-2.5 font-sans text-[13px] font-bold text-[#1a0910] hover:brightness-[1.06] disabled:cursor-default disabled:opacity-60 ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function SecondaryButton({
  children,
  className = "",
  ...props
}: { children: ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`rounded-md border border-line bg-panel-2 px-4 py-2.5 font-sans text-[12.5px] font-semibold text-text hover:border-muted-2 disabled:cursor-default disabled:opacity-60 ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function ErrorBanner({ children }: { children: ReactNode }) {
  return (
    <div className="mb-4 flex gap-2.5 rounded-md border border-rose-dim bg-rose-dim px-3.5 py-2.5 text-xs leading-relaxed text-rose">
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="mt-0.5 shrink-0" aria-hidden="true">
        <circle cx="8" cy="8" r="6.3" stroke="currentColor" />
        <path d="M8 5v3.4M8 10.8h.01" stroke="currentColor" strokeLinecap="round" />
      </svg>
      <span>{children}</span>
    </div>
  );
}

export function LockNote({ children }: { children: ReactNode }) {
  return (
    <div className="mt-[18px] flex gap-2.5 rounded-lg border border-amber-dim bg-amber-dim px-3.5 py-3 text-xs leading-relaxed text-amber">
      <svg width="15" height="15" viewBox="0 0 16 16" fill="none" className="mt-0.5 shrink-0" aria-hidden="true">
        <rect x="3.5" y="7" width="9" height="6.5" rx="1.3" stroke="currentColor" />
        <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" stroke="currentColor" />
      </svg>
      <span>{children}</span>
    </div>
  );
}
