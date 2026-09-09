import type { MouseEvent, ReactNode } from "react";

export function StatusPill({ status }: { status: string }) {
  const styles: Record<string, string> = {
    active: "bg-good-dim text-good",
    success: "bg-good-dim text-good",
    suspended: "bg-rose-dim text-rose",
    rejected: "bg-rose-dim text-rose",
    error: "bg-rose-dim text-rose",
    failed: "bg-rose-dim text-rose",
  };
  const cls = styles[status] ?? "bg-amber-dim text-amber"; // onboarding, pending_approval, grace, running…
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-mono text-[10px] tracking-wide uppercase ${cls}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {status}
    </span>
  );
}

function backdropClick(onClose: () => void) {
  return (e: MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose();
  };
}

export function Modal({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  return (
    <div
      className="fixed inset-0 z-100 flex items-center justify-center bg-black/50 p-5"
      role="presentation"
      onClick={backdropClick(onClose)}
    >
      <section
        className="max-h-[calc(100vh-40px)] w-full max-w-[460px] overflow-y-auto rounded-[10px] border border-line bg-panel"
        role="dialog"
        aria-modal="true"
      >
        {children}
      </section>
    </div>
  );
}

export function Drawer({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  return (
    <div
      className="fixed inset-0 z-100 flex justify-end bg-black/50"
      role="presentation"
      onClick={backdropClick(onClose)}
    >
      <section className="h-full w-full max-w-[92vw] overflow-y-auto border-l border-line bg-panel sm:w-[480px]" role="dialog" aria-modal="true">
        {children}
      </section>
    </div>
  );
}

export function CloseButton({ onClose }: { onClose: () => void }) {
  return (
    <button
      type="button"
      onClick={onClose}
      aria-label="Close"
      className="flex h-[30px] w-[30px] items-center justify-center rounded border border-line font-mono text-muted hover:text-text"
    >
      ×
    </button>
  );
}
