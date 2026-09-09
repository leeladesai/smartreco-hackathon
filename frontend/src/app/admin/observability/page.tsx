"use client";

import { useEffect, useState } from "react";
import { useApi } from "@/lib/useApi";
import type { CostRollup, RunDetailResponse, RunsResponse } from "@/lib/observability";
import { Drawer, CloseButton, StatusPill } from "@/components/admin-ui";

const PAGE_SIZE = 25;

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function ms(value: number | null): string {
  return value != null ? `${Math.round(value)}ms` : "—";
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-panel-2 px-4 py-3.5">
      <p className="mb-1 font-mono text-[10px] tracking-wide text-muted-2 uppercase">{label}</p>
      <p className="font-mono text-2xl text-text tabular-nums">{value}</p>
    </div>
  );
}

const thCls = "border-b border-line px-3 py-2.5 text-left font-mono text-[10.5px] tracking-wide text-muted uppercase";
const tdCls = "border-b border-line-soft px-3 py-3 text-[13px]";

export default function ObservabilityPage() {
  const api = useApi();
  const [costs, setCosts] = useState<CostRollup | null>(null);
  const [runsData, setRunsData] = useState<RunsResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  useEffect(() => {
     
    api<CostRollup>("/api/admin/observability/costs").then(setCosts).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
     
    api<RunsResponse>(`/api/admin/observability/runs?limit=${PAGE_SIZE}&offset=${offset}`)
      .then(setRunsData)
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset]);

  return (
    <div>
      <p className="mb-2 font-mono text-[10.5px] tracking-[0.16em] text-rose uppercase">Curator console</p>
      <h1 className="mb-1.5 text-[26px] tracking-tight">Observability</h1>
      <p className="mb-6 max-w-[640px] text-[13.5px] leading-relaxed text-muted">
        Mesh cost/latency from our own database, plus a read-only view of recent agent-pipeline traces.
      </p>

      {costs && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <StatTile label="Mesh calls" value={costs.call_count.toLocaleString()} />
            <StatTile label="Avg latency" value={ms(costs.avg_latency_ms)} />
            <StatTile label="Prompt tokens" value={costs.total_prompt_tokens.toLocaleString()} />
            <StatTile label="Completion tokens" value={costs.total_completion_tokens.toLocaleString()} />
            <StatTile
              label="Total cost"
              value={costs.total_cost_usd != null ? `$${costs.total_cost_usd.toFixed(4)}` : "—"}
            />
          </div>

          {costs.recent.length > 0 && (
            <>
              <h2 className="mt-8 mb-3 text-[15px]">Recent mesh calls</h2>
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className={thCls}>When</th>
                    <th className={thCls}>Latency</th>
                    <th className={thCls}>Prompt tok</th>
                    <th className={thCls}>Completion tok</th>
                    <th className={thCls}>Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {costs.recent.map((row) => (
                    <tr key={row.id}>
                      <td className={tdCls}>{formatTime(row.created_at)}</td>
                      <td className={tdCls}>{ms(row.latency_ms)}</td>
                      <td className={tdCls}>{row.prompt_tokens ?? "—"}</td>
                      <td className={tdCls}>{row.completion_tokens ?? "—"}</td>
                      <td className={tdCls}>{row.cost_usd != null ? `$${row.cost_usd.toFixed(5)}` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}

      <h2 className="mt-8 mb-3 text-[15px]">Recent pipeline runs</h2>
      {runsData && !runsData.available && (
        <p className="rounded-md border border-line px-4 py-3.5 text-[13px] text-muted">
          {runsData.message ?? "Tracing isn't configured for this deployment."}
        </p>
      )}
      {runsData?.available && runsData.runs.length === 0 && (
        <p className="rounded-md border border-line px-4 py-3.5 text-[13px] text-muted">No runs recorded yet.</p>
      )}
      {runsData?.available && runsData.runs.length > 0 && (
        <>
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className={thCls}>Name</th>
                <th className={thCls}>Status</th>
                <th className={thCls}>Visitor</th>
                <th className={thCls}>Latency</th>
                <th className={thCls}>Started</th>
              </tr>
            </thead>
            <tbody>
              {runsData.runs.map((run) => (
                <tr key={run.id} className="cursor-pointer hover:bg-panel-2" onClick={() => setSelectedRunId(run.id)}>
                  <td className={tdCls}>{run.name}</td>
                  <td className={tdCls}>
                    <StatusPill status={run.status} />
                  </td>
                  <td className={`${tdCls} font-mono text-[11.5px] text-muted`}>
                    {run.visitor_id ? `${run.visitor_id.slice(0, 12)}…` : "—"}
                  </td>
                  <td className={tdCls}>{ms(run.pipeline_latency_ms ?? run.latency_ms)}</td>
                  <td className={tdCls}>{formatTime(run.start_time)}</td>
                </tr>
              ))}
            </tbody>
          </table>

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
              disabled={!runsData.has_more}
              onClick={() => setOffset((o) => o + PAGE_SIZE)}
              className="rounded border border-line px-3 py-1.5 font-mono text-[11px] text-muted disabled:cursor-default disabled:opacity-50"
            >
              Next ›
            </button>
          </div>
        </>
      )}

      {selectedRunId && <RunDrawer runId={selectedRunId} onClose={() => setSelectedRunId(null)} />}
    </div>
  );
}

function RunDrawer({ runId, onClose }: { runId: string; onClose: () => void }) {
  const api = useApi();
  const [detail, setDetail] = useState<RunDetailResponse | null>(null);

  useEffect(() => {
     
    api<RunDetailResponse>(`/api/admin/observability/runs/${encodeURIComponent(runId)}`)
      .then(setDetail)
      .catch(() => setDetail({ available: false, message: "Could not load this trace.", run: null }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const run = detail?.run;

  return (
    <Drawer onClose={onClose}>
      <div className="relative border-b border-line-soft px-5.5 py-5 pb-4">
        <div className="absolute top-4 right-4">
          <CloseButton onClose={onClose} />
        </div>
        <p className="mb-2 font-mono text-[10.5px] tracking-[0.16em] text-rose uppercase">Trace</p>
        <h2 className="mb-1 text-[19px]">{run?.name ?? "Loading…"}</h2>
        {run && (
          <div className="flex items-center gap-2.5">
            <StatusPill status={run.status} />
            <span className="font-mono text-[11px] text-muted">
              {ms(run.pipeline_latency_ms ?? run.latency_ms)} wall
            </span>
          </div>
        )}
        {run?.url && (
          <a href={run.url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-xs text-rose underline">
            Open in LangSmith
          </a>
        )}
      </div>
      <div className="px-5.5 py-5 pb-7">
        {detail && !detail.available && (
          <p className="text-[13px] text-muted">{detail.message ?? "Could not load this trace."}</p>
        )}
        {run?.steps.map((step, i) => (
          <div key={i} className="mb-3 rounded-md border border-line-soft bg-panel-2 px-3.5 py-3" style={{ marginLeft: step.depth * 14 }}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-[13px] font-semibold">{step.name}</span>
              <StatusPill status={step.status} />
            </div>
            <div className="mt-1 flex gap-3 font-mono text-[11px] text-muted">
              <span>{step.run_type}</span>
              <span>{ms(step.latency_ms)}</span>
            </div>
            {step.error && <p className="mt-1.5 font-mono text-[11px] text-rose">{step.error}</p>}
          </div>
        ))}
      </div>
    </Drawer>
  );
}
