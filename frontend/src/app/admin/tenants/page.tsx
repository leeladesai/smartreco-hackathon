"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useApi } from "@/lib/useApi";
import { ApiError } from "@/lib/api";
import type { TenantCreateResponse, TenantDetail, TenantSummary, TenantsListResponse } from "@/lib/tenants";
import { StatusPill, Modal, Drawer, CloseButton } from "@/components/admin-ui";
import { Field, PrimaryButton, SecondaryButton } from "@/components/ui";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

const thCls = "border-b border-line px-3 py-2.5 text-left font-mono text-[10.5px] tracking-wide text-muted uppercase";
const tdCls = "border-b border-line-soft px-3 py-3 align-top text-[13px]";

export default function TenantsPage() {
  const api = useApi();
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tab, setTab] = useState<"pending" | "all">("pending");
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  async function loadTenants() {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await api<TenantsListResponse>("/api/tenants?limit=200");
      setTenants(data.tenants);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not load tenants.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadTenants();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pending = tenants.filter((t) => t.status === "pending_approval");
  const visible = tab === "pending" ? pending : tenants;

  async function handleApprove(id: number) {
    await api(`/api/tenants/${id}/approve`, { method: "POST" });
    loadTenants();
  }

  async function handleReject(id: number) {
    if (!window.confirm("Reject this signup? Login will be permanently blocked for it.")) return;
    await api(`/api/tenants/${id}/reject`, { method: "POST" });
    loadTenants();
  }

  return (
    <div>
      <div className="mb-5.5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-2 font-mono text-[10.5px] tracking-[0.16em] text-rose uppercase">Platform console</p>
          <h1 className="mb-1.5 text-[26px] tracking-tight">Tenants</h1>
          <p className="max-w-[640px] text-[13.5px] leading-relaxed text-muted">
            Every company embedding TrailMind. Self-serve signups land in Pending until you approve them; a tenant
            you create yourself starts trusted. Each tenant manages its own widgets and API keys once inside.
          </p>
        </div>
        <PrimaryButton type="button" onClick={() => setCreateOpen(true)}>
          + New tenant
        </PrimaryButton>
      </div>

      <div className="mb-4.5 flex gap-1.5 border-b border-line">
        <button
          type="button"
          onClick={() => setTab("pending")}
          className={`mr-4.5 border-b-2 pb-2.5 font-mono text-[11.5px] tracking-wide ${
            tab === "pending" ? "border-rose text-text" : "border-transparent text-muted"
          }`}
        >
          Pending approval <span className="text-muted-2">({pending.length})</span>
        </button>
        <button
          type="button"
          onClick={() => setTab("all")}
          className={`mr-4.5 border-b-2 pb-2.5 font-mono text-[11.5px] tracking-wide ${
            tab === "all" ? "border-rose text-text" : "border-transparent text-muted"
          }`}
        >
          All tenants <span className="text-muted-2">({tenants.length})</span>
        </button>
      </div>

      {loadError && <p className="font-mono text-[11px] text-rose">{loadError}</p>}

      {!loading && visible.length === 0 && (
        <p className="mt-4 rounded-md border border-line px-4 py-3.5 text-[13px] text-muted">
          {tab === "pending" ? "No signups waiting on approval." : "No tenants yet."}
        </p>
      )}

      {visible.length > 0 && (
        <table className="mt-4 w-full border-collapse">
          <thead>
            <tr>
              <th className={thCls}>Name</th>
              <th className={thCls}>Status</th>
              <th className={thCls}>Widgets</th>
              <th className={thCls}>Created</th>
              <th className={thCls}></th>
            </tr>
          </thead>
          <tbody>
            {visible.map((tenant) => (
              <tr
                key={tenant.id}
                className="cursor-pointer hover:bg-panel-2"
                onClick={() => setSelectedId(tenant.id)}
              >
                <td className={tdCls}>{tenant.name}</td>
                <td className={tdCls}>
                  <StatusPill status={tenant.status} />
                </td>
                <td className={tdCls}>{tenant.widget_count}</td>
                <td className={tdCls}>{formatDate(tenant.created_at)}</td>
                <td className={`${tdCls} flex justify-end gap-2`} onClick={(e) => e.stopPropagation()}>
                  {tenant.status === "pending_approval" && (
                    <>
                      <button
                        type="button"
                        onClick={() => handleApprove(tenant.id)}
                        className="rounded-md border border-good px-2.5 py-1.5 font-sans text-[11.5px] font-semibold text-good"
                      >
                        Approve
                      </button>
                      <button
                        type="button"
                        onClick={() => handleReject(tenant.id)}
                        className="rounded-md border border-rose px-2.5 py-1.5 font-sans text-[11.5px] font-semibold text-rose"
                      >
                        Reject
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {createOpen && (
        <CreateTenantModal
          onClose={() => {
            setCreateOpen(false);
            loadTenants();
          }}
        />
      )}

      {selectedId !== null && (
        <TenantDrawer
          tenantId={selectedId}
          onClose={() => {
            setSelectedId(null);
            loadTenants();
          }}
        />
      )}
    </div>
  );
}

function CreateTenantModal({ onClose }: { onClose: () => void }) {
  const api = useApi();
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<{ text: string; kind: "muted" | "success" | "error" }>({
    text: "",
    kind: "muted",
  });
  const [created, setCreated] = useState<TenantCreateResponse | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setStatus({ text: "Creating…", kind: "muted" });
    try {
      const data = await api<TenantCreateResponse>("/api/tenants", {
        method: "POST",
        body: { name },
      });
      setStatus({ text: `✓ Tenant "${data.name}" created.`, kind: "success" });
      setCreated(data);
    } catch (err) {
      setStatus({
        text: err instanceof ApiError ? err.message : "Could not create tenant.",
        kind: "error",
      });
    } finally {
      setSubmitting(false);
    }
  }

  const statusColor = status.kind === "success" ? "text-good" : status.kind === "error" ? "text-rose" : "text-muted";

  return (
    <Modal onClose={onClose}>
      <div className="flex items-start justify-between gap-5 border-b border-line-soft px-5.5 py-5 pb-4">
        <div>
          <h3 className="mb-1 text-[17px]">New tenant</h3>
          <p className="text-xs leading-relaxed text-muted">
            Creates the tenant shell. Its own business admin creates a widget (and gets its tracker key) once inside.
          </p>
        </div>
        <CloseButton onClose={onClose} />
      </div>
      <form className="px-5.5 py-5" onSubmit={handleSubmit}>
        <Field
          id="tenant-name"
          label="Tenant name"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Acme Corp"
          disabled={!!created}
        />
        {status.text && <p className={`mb-1 font-mono text-[11px] ${statusColor}`}>{status.text}</p>}
        <div className="mt-2 flex gap-2.5">
          {!created && (
            <PrimaryButton type="submit" disabled={submitting}>
              {submitting ? "Creating…" : "Create tenant"}
            </PrimaryButton>
          )}
          <SecondaryButton type="button" onClick={onClose}>
            {created ? "Done" : "Cancel"}
          </SecondaryButton>
        </div>
      </form>
    </Modal>
  );
}

function TenantDrawer({ tenantId, onClose }: { tenantId: number; onClose: () => void }) {
  const api = useApi();
  const [tenant, setTenant] = useState<TenantDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  async function load() {
    try {
      const data = await api<TenantDetail>(`/api/tenants/${tenantId}`);
      setTenant(data);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not load this tenant.");
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  async function suspend() {
    if (!window.confirm("Suspend this tenant? Every widget under it goes dark on the host page immediately."))
      return;
    await api(`/api/tenants/${tenantId}/suspend`, { method: "POST" });
    load();
  }

  async function reactivate() {
    await api(`/api/tenants/${tenantId}/reactivate`, { method: "POST" });
    load();
  }

  return (
    <Drawer onClose={onClose}>
      <div className="relative border-b border-line-soft px-5.5 py-5 pb-4">
        <div className="absolute top-4 right-4">
          <CloseButton onClose={onClose} />
        </div>
        <p className="mb-2 font-mono text-[10.5px] tracking-[0.16em] text-rose uppercase">Tenant detail</p>
        <h2 className="mb-1 text-[19px]">{tenant?.name ?? "Loading…"}</h2>
        {tenant && <StatusPill status={tenant.status} />}
      </div>
      <div className="px-5.5 py-5 pb-7">
        {loadError && <p className="font-mono text-[11px] text-rose">{loadError}</p>}
        {tenant && (
          <>
            <div className="mt-5.5 flex items-center justify-between">
              <h4 className="text-[13px]">Widgets</h4>
            </div>
            {tenant.widgets.length === 0 && (
              <p className="mt-3 text-[13px] text-muted">
                No widgets yet — this tenant&rsquo;s own admin creates one from the Widgets page once signed in.
              </p>
            )}
            {tenant.widgets.length > 0 && (
              <table className="mt-4 w-full border-collapse">
                <thead>
                  <tr>
                    <th className={thCls}>Name</th>
                    <th className={thCls}>Status</th>
                    <th className={thCls}>Ready</th>
                    <th className={thCls}>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {tenant.widgets.map((widget) => (
                    <tr key={widget.id}>
                      <td className={tdCls}>{widget.name}</td>
                      <td className={tdCls}>
                        <StatusPill status={widget.status} />
                      </td>
                      <td className={tdCls}>
                        {widget.ready
                          ? "ready"
                          : `${widget.tracker_verified ? "tracker✓" : "tracker–"} / ${
                              widget.catalog_ready ? "catalog✓" : "catalog–"
                            }`}
                      </td>
                      <td className={tdCls}>{formatDate(widget.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div className="mt-5.5 flex items-center justify-between">
              <h4 className="text-[13px]">Actions</h4>
              <div className="flex gap-2.5">
                {tenant.status !== "suspended" && (
                  <SecondaryButton type="button" onClick={suspend} className="px-2.5 py-1.5 text-[11.5px]">
                    Suspend
                  </SecondaryButton>
                )}
                {tenant.status === "suspended" && (
                  <SecondaryButton type="button" onClick={reactivate} className="px-2.5 py-1.5 text-[11.5px]">
                    Reactivate
                  </SecondaryButton>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </Drawer>
  );
}
