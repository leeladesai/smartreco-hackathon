import type { ReactNode } from "react";

export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center px-5 py-15">
      <div className="mb-10 inline-flex items-center gap-2 rounded border border-line px-3 py-2 font-mono text-[13.5px] font-bold tracking-[0.13em] text-rose">
        <svg width="14" height="14" viewBox="0 0 18 18" aria-hidden="true">
          <rect x="1" y="10" width="3.4" height="7" rx="1" fill="#5ec8d8" />
          <rect x="6.3" y="6" width="3.4" height="11" rx="1" fill="#e8a33d" />
          <rect x="11.6" y="2" width="3.4" height="15" rx="1" fill="#a78bfa" />
        </svg>
        TRAILMIND
      </div>
      <div className="w-full max-w-[420px] rounded-[11px] border border-line bg-panel p-8 shadow-[0_18px_46px_-30px_rgba(0,0,0,0.6)]">
        {children}
      </div>
    </div>
  );
}
