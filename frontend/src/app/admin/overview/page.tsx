"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useApi } from "@/lib/useApi";
import { ApiError } from "@/lib/api";
import type { ActivityResponse, OverviewResponse } from "@/lib/overview";

const PAGE_SIZE = 20;

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function StatTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-line bg-panel-2 px-4 py-3.5">
      <p className="mb-1 font-mono text-[10px] tracking-wide text-muted-2 uppercase">{label}</p>
      <p className="font-mono text-2xl text-text tabular-nums">{value.toLocaleString()}</p>
    </div>
  );
}

export default function OverviewPage() {
  const api = useApi();
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [events, setEvents] = useState<ActivityResponse["events"]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadOverview() {
    try {
      const data = await api<OverviewResponse>("/api/admin/overview");
      setOverview(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the overview.");
    }
  }

  async function loadActivity() {
    try {
      const data = await api<ActivityResponse>(`/api/admin/overview/activity?limit=${PAGE_SIZE}&offset=${offset}`);
      setEvents(data.events);
      setHasMore(data.has_more);
    } catch {
      // The stat tiles above are the important part of this page; a failed activity
      // page just leaves the feed empty rather than blocking the whole view.
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadOverview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadActivity();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset]);

  return (
    <div>
      <p className="mb-2 font-mono text-[10.5px] tracking-[0.16em] text-rose uppercase">Curator console</p>
      <h1 className="mb-1.5 text-[26px] tracking-tight">Overview</h1>
      <p className="mb-6 max-w-[640px] text-[13.5px] leading-relaxed text-muted">
        Usage totals and live activity for this tenant, computed straight from the database.
      </p>

      {error && <p className="font-mono text-[11px] text-rose">{error}</p>}

      {overview && overview.totals.catalog_items === 0 && overview.totals.events === 0 && (
        <p className="mb-5 rounded-md border border-line bg-panel-2 px-4 py-3.5 text-[13px] leading-relaxed text-muted">
          Nothing tracked yet. <Link href="/admin/widgets" className="text-rose hover:underline">Create a widget</Link>{" "}
          to get a tracker key, then <Link href="/admin/catalog" className="text-rose hover:underline">add catalog
          items</Link> for it to recommend.
        </p>
      )}

      {overview && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label="Users" value={overview.totals.users} />
            <StatTile label="Catalog items" value={overview.totals.catalog_items} />
            <StatTile label="Events" value={overview.totals.events} />
            <StatTile label="Recommendations" value={overview.totals.recommendations} />
          </div>

          <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-line bg-panel-2 px-4 py-3.5">
              <p className="mb-2.5 font-mono text-[10px] tracking-wide text-muted-2 uppercase">Events by type</p>
              {Object.keys(overview.event_type_counts).length === 0 ? (
                <p className="text-[12.5px] text-muted">No events tracked yet.</p>
              ) : (
                <div className="flex flex-col gap-1.5">
                  {Object.entries(overview.event_type_counts)
                    .sort((a, b) => b[1] - a[1])
                    .map(([type, count]) => (
                      <div key={type} className="flex justify-between font-mono text-[12px]">
                        <span className="text-muted">{type}</span>
                        <span className="text-text tabular-nums">{count}</span>
                      </div>
                    ))}
                </div>
              )}
            </div>
            <div className="rounded-lg border border-line bg-panel-2 px-4 py-3.5">
              <p className="mb-2.5 font-mono text-[10px] tracking-wide text-muted-2 uppercase">Feedback sentiment</p>
              <div className="flex gap-6">
                <div>
                  <p className="font-mono text-xl text-good tabular-nums">{overview.feedback.up}</p>
                  <p className="font-mono text-[10px] text-muted-2 uppercase">Thumbs up</p>
                </div>
                <div>
                  <p className="font-mono text-xl text-rose tabular-nums">{overview.feedback.down}</p>
                  <p className="font-mono text-[10px] text-muted-2 uppercase">Thumbs down</p>
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      <h2 className="mt-8 mb-3 text-[15px]">Live activity</h2>
      {events.length === 0 ? (
        <p className="rounded-md border border-line px-4 py-3.5 text-[13px] text-muted">No activity tracked yet.</p>
      ) : (
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="border-b border-line px-3 py-2.5 text-left font-mono text-[10.5px] tracking-wide text-muted uppercase">Visitor</th>
              <th className="border-b border-line px-3 py-2.5 text-left font-mono text-[10.5px] tracking-wide text-muted uppercase">Event</th>
              <th className="border-b border-line px-3 py-2.5 text-left font-mono text-[10.5px] tracking-wide text-muted uppercase">When</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={event.id}>
                <td className="border-b border-line-soft px-3 py-3 font-mono text-[11.5px] text-muted">
                  {event.visitor_id.slice(0, 12)}…
                </td>
                <td className="border-b border-line-soft px-3 py-3 text-[13px]">{event.event_type}</td>
                <td className="border-b border-line-soft px-3 py-3 text-[13px] text-muted">{formatTime(event.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {(offset > 0 || hasMore) && (
        <div className="mt-4 flex items-center justify-center gap-4">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            className="rounded border border-line px-3 py-1.5 font-mono text-[11px] text-muted disabled:cursor-default disabled:opacity-50"
          >
            ‹ Prev
          </button>
          <span className="font-mono text-[10.5px] text-muted">Page {Math.floor(offset / PAGE_SIZE) + 1}</span>
          <button
            type="button"
            disabled={!hasMore}
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
            className="rounded border border-line px-3 py-1.5 font-mono text-[11px] text-muted disabled:cursor-default disabled:opacity-50"
          >
            Next ›
          </button>
        </div>
      )}
    </div>
  );
}
