/**
 * Stands in for a real console page (Overview/Catalog/Users/Observability) until the
 * rest of Phase 0's rewrite lands. The nav/logout chrome lives in the /admin layout,
 * not here — this only fills the content area.
 */
export function Placeholder({ title }: { title: string }) {
  return (
    <div>
      <p className="mb-2 font-mono text-[10.5px] tracking-[0.16em] text-rose uppercase">Coming soon</p>
      <h1 className="mb-1.5 text-[26px] tracking-tight">{title}</h1>
      <p className="max-w-[640px] text-[13.5px] leading-relaxed text-muted">
        This page hasn&rsquo;t been rebuilt in the new console yet &mdash; it&rsquo;s the remaining Phase 0 work.
      </p>
    </div>
  );
}
