"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useApi } from "@/lib/useApi";
import { ApiError, API_BASE } from "@/lib/api";
import type { ApiKeyResponse, WidgetCreateResponse, WidgetResponse } from "@/lib/widgets";
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
const labelCls = "mb-1.5 block font-mono text-[10.5px] tracking-wide text-muted uppercase";
const inputCls =
  "w-full rounded-md border border-line bg-panel-2 px-3 py-2.5 text-[13.5px] text-text focus:border-rose focus:outline-none";

function CopyBlock({ label, code, mono = true }: { label: string; code: string; mono?: boolean }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    navigator.clipboard
      ?.writeText(code)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => {});
  }
  return (
    <div className="mb-3">
      <div className="mb-1.5 flex items-center justify-between">
        <label className={`${labelCls} mb-0`}>{label}</label>
        <SecondaryButton type="button" onClick={copy} className="shrink-0 px-2.5 py-1 text-[11px]">
          {copied ? "Copied ✓" : "Copy"}
        </SecondaryButton>
      </div>
      <pre
        className={`overflow-x-auto rounded-lg border border-line bg-panel-2 px-3.5 py-3 text-[12px] leading-relaxed text-text ${
          mono ? "font-mono" : ""
        }`}
      >
        <code className="whitespace-pre-wrap break-all">{code}</code>
      </pre>
    </div>
  );
}

function RevealedKey({ apiKey }: { apiKey: string }) {
  const trackerSnippet = `<script src="${API_BASE}/static/js/tracker.js" data-widget-key="${apiKey}"></script>`;
  const widgetSnippet = `<script src="${API_BASE}/static/js/widget.js" data-widget-key="${apiKey}"></script>`;
  return (
    <div className="mb-4">
      <div className="mb-1.5 flex items-center justify-between">
        <label className={`${labelCls} mb-0`}>API key</label>
        <span className="rounded bg-amber-dim px-2 py-0.5 font-mono text-[10px] tracking-wide text-amber uppercase">
          Shown once
        </span>
      </div>
      <div className="mb-3 flex items-center gap-2.5 rounded-lg border border-amber bg-panel-2 px-3.5 py-3 shadow-[0_0_0_3px_var(--amber-dim)]">
        <code className="flex-1 font-mono text-[12.5px] break-all text-text">{apiKey}</code>
        <CopyIconButton value={apiKey} />
      </div>
      <p className="mb-4 text-[11.5px] leading-relaxed text-muted">
        This key won&rsquo;t be shown again &mdash; copy the snippets below into the site this widget runs on before
        closing this dialog.
      </p>
      <CopyBlock label="Tracker snippet — paste before &lt;/body&gt; on every page" code={trackerSnippet} />
      <CopyBlock label="Widget snippet — paste where the recommendation panel should render" code={widgetSnippet} />
      <p className="text-[11.5px] leading-relaxed text-muted">
        The widget stays dark until this widget is both tracker-verified (a real event has reached the backend) and
        catalog-ready (at least one approved item) &mdash; see the checklist on this widget&rsquo;s detail page.
      </p>
    </div>
  );
}

function CopyIconButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    navigator.clipboard
      ?.writeText(value)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => {});
  }
  return (
    <SecondaryButton type="button" onClick={copy} className="shrink-0 px-2.5 py-1.5 text-[11.5px]">
      {copied ? "Copied ✓" : "Copy"}
    </SecondaryButton>
  );
}

export default function WidgetsPage() {
  const api = useApi();
  const [widgets, setWidgets] = useState<WidgetResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  async function loadWidgets() {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await api<WidgetResponse[]>("/api/admin/widgets");
      setWidgets(data);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not load widgets.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadWidgets();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <div className="mb-5.5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-2 font-mono text-[10.5px] tracking-[0.16em] text-rose uppercase">Business admin</p>
          <h1 className="mb-1.5 text-[26px] tracking-tight">Widgets</h1>
          <p className="max-w-[640px] text-[13.5px] leading-relaxed text-muted">
            One embeddable unit per product surface (e.g. &ldquo;Credit Cards&rdquo; vs &ldquo;Personal
            Loans&rdquo;) &mdash; each has its own key, allowed origins, and catalog, so recommendations never leak
            across products.
          </p>
        </div>
        <PrimaryButton type="button" onClick={() => setCreateOpen(true)}>
          + New widget
        </PrimaryButton>
      </div>

      {loadError && <p className="font-mono text-[11px] text-rose">{loadError}</p>}

      {!loading && widgets.length === 0 && !loadError && (
        <p className="mt-4 rounded-md border border-line px-4 py-3.5 text-[13px] text-muted">
          No widgets yet &mdash; create one to get a tracker key and start building its catalog.
        </p>
      )}

      {widgets.length > 0 && (
        <table className="mt-4 w-full border-collapse">
          <thead>
            <tr>
              <th className={thCls}>Name</th>
              <th className={thCls}>Status</th>
              <th className={thCls}>Ready</th>
              <th className={thCls}>Created</th>
              <th className={thCls}></th>
            </tr>
          </thead>
          <tbody>
            {widgets.map((widget) => (
              <tr key={widget.id} className="cursor-pointer hover:bg-panel-2" onClick={() => setSelectedId(widget.id)}>
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
                <td className={tdCls}></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {createOpen && (
        <CreateWidgetModal
          onClose={() => {
            setCreateOpen(false);
            loadWidgets();
          }}
        />
      )}

      {selectedId !== null && (
        <WidgetDrawer
          widgetId={selectedId}
          onClose={() => {
            setSelectedId(null);
            loadWidgets();
          }}
        />
      )}
    </div>
  );
}

function CreateWidgetModal({ onClose }: { onClose: () => void }) {
  const api = useApi();
  const [name, setName] = useState("");
  const [origins, setOrigins] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<{ text: string; kind: "muted" | "success" | "error" }>({
    text: "",
    kind: "muted",
  });
  const [created, setCreated] = useState<WidgetCreateResponse | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setStatus({ text: "Creating…", kind: "muted" });
    try {
      const allowed_origins = origins
        .split(",")
        .map((o) => o.trim())
        .filter(Boolean);
      const data = await api<WidgetCreateResponse>("/api/admin/widgets", {
        method: "POST",
        body: { name, allowed_origins },
      });
      setStatus({ text: `✓ Widget "${data.widget.name}" created.`, kind: "success" });
      setCreated(data);
    } catch (err) {
      setStatus({
        text: err instanceof ApiError ? err.message : "Could not create widget.",
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
          <h3 className="mb-1 text-[17px]">New widget</h3>
          <p className="text-xs leading-relaxed text-muted">
            Issues a live tracker API key for this widget. It&rsquo;s shown once &mdash; copy it before closing.
          </p>
        </div>
        <CloseButton onClose={onClose} />
      </div>
      <form className="px-5.5 py-5" onSubmit={handleSubmit}>
        <Field
          id="widget-name"
          label="Widget name"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Personal Loans"
          disabled={!!created}
        />
        <Field
          id="widget-origins"
          label="Allowed origins"
          value={origins}
          onChange={(e) => setOrigins(e.target.value)}
          placeholder="https://acme.com, https://app.acme.com"
          disabled={!!created}
        />
        {status.text && <p className={`mb-1 font-mono text-[11px] ${statusColor}`}>{status.text}</p>}
        {created && <RevealedKey apiKey={created.api_key} />}
        <div className="mt-2 flex gap-2.5">
          {!created && (
            <PrimaryButton type="submit" disabled={submitting}>
              {submitting ? "Creating…" : "Create widget"}
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

function WidgetDrawer({ widgetId, onClose }: { widgetId: number; onClose: () => void }) {
  const api = useApi();
  const [widget, setWidget] = useState<WidgetResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [feedUrl, setFeedUrl] = useState("");
  const [feedToken, setFeedToken] = useState("");
  const [feedStatus, setFeedStatus] = useState<string | null>(null);

  async function load() {
    try {
      const data = await api<WidgetResponse>(`/api/admin/widgets/${widgetId}`);
      setWidget(data);
      setFeedUrl(data.feed_url ?? "");
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not load this widget.");
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [widgetId]);

  async function rotateKey() {
    if (
      !window.confirm(
        "Issue a new active key? The current key keeps working for 24h so a live deployment has time to switch over.",
      )
    )
      return;
    const data = await api<ApiKeyResponse>(`/api/admin/widgets/${widgetId}/rotate-key`, { method: "POST" });
    setRevealedKey(data.api_key);
    load();
  }

  async function suspend() {
    if (!window.confirm("Suspend this widget? It goes dark on the host page immediately.")) return;
    await api(`/api/admin/widgets/${widgetId}/suspend`, { method: "POST" });
    load();
  }

  async function reactivate() {
    await api(`/api/admin/widgets/${widgetId}/reactivate`, { method: "POST" });
    load();
  }

  async function saveFeed(event: FormEvent) {
    event.preventDefault();
    setFeedStatus("Saving…");
    try {
      await api(`/api/admin/widgets/${widgetId}/feed`, {
        method: "POST",
        body: { feed_url: feedUrl, auth_token: feedToken || null },
      });
      setFeedStatus("✓ Feed configured.");
      load();
    } catch (err) {
      setFeedStatus(err instanceof ApiError ? err.message : "Could not save feed config.");
    }
  }

  return (
    <Drawer onClose={onClose}>
      <div className="relative border-b border-line-soft px-5.5 py-5 pb-4">
        <div className="absolute top-4 right-4">
          <CloseButton onClose={onClose} />
        </div>
        <p className="mb-2 font-mono text-[10.5px] tracking-[0.16em] text-rose uppercase">Widget detail</p>
        <h2 className="mb-1 text-[19px]">{widget?.name ?? "Loading…"}</h2>
        {widget && <StatusPill status={widget.status} />}
      </div>
      <div className="px-5.5 py-5 pb-7">
        {loadError && <p className="font-mono text-[11px] text-rose">{loadError}</p>}
        {widget && (
          <>
            <div className="mt-2.5 flex flex-col gap-1.5">
              <ChecklistItem done={widget.tracker_verified}>Tracker snippet verified</ChecklistItem>
              <ChecklistItem done={widget.catalog_ready}>Catalog has an approved, synced item</ChecklistItem>
            </div>
            <p className="mt-3 max-w-[640px] text-[13.5px] leading-relaxed text-muted">
              Allowed origins:{" "}
              {widget.allowed_origins.length
                ? widget.allowed_origins.join(", ")
                : "none set — tracker/widget calls from any origin are accepted"}
            </p>

            <div className="mt-5.5 flex items-center justify-between">
              <h4 className="text-[13px]">API key</h4>
              <SecondaryButton type="button" onClick={rotateKey} className="px-2.5 py-1.5 text-[11.5px]">
                Rotate key
              </SecondaryButton>
            </div>
            {revealedKey ? (
              <div className="mt-3">
                <RevealedKey apiKey={revealedKey} />
              </div>
            ) : (
              <div className="mt-3">
                <p className="mb-3 text-[12.5px] text-muted">
                  Keys are shown once, at creation or rotation &mdash; not retrievable after that. If you still have
                  it installed, here&rsquo;s the snippet shape for reference (swap in the real key):
                </p>
                <CopyBlock
                  label="Tracker snippet"
                  code={`<script src="${API_BASE}/static/js/tracker.js" data-widget-key="<your-widget-key>"></script>`}
                />
                <CopyBlock
                  label="Widget snippet"
                  code={`<script src="${API_BASE}/static/js/widget.js" data-widget-key="<your-widget-key>"></script>`}
                />
              </div>
            )}

            <form className="mt-5.5" onSubmit={saveFeed}>
              <h4 className="mb-3 text-[13px]">Feed sync</h4>
              <div className="mb-3">
                <label className={labelCls} htmlFor="feed-url">
                  Feed URL
                </label>
                <input
                  id="feed-url"
                  type="url"
                  className={inputCls}
                  value={feedUrl}
                  onChange={(e) => setFeedUrl(e.target.value)}
                  placeholder="https://acme.com/catalog.json"
                />
              </div>
              <div className="mb-3">
                <label className={labelCls} htmlFor="feed-token">
                  Auth token (optional)
                </label>
                <input
                  id="feed-token"
                  type="password"
                  className={inputCls}
                  value={feedToken}
                  onChange={(e) => setFeedToken(e.target.value)}
                  placeholder="Bearer token for the feed endpoint"
                />
              </div>
              {feedStatus && <p className="mb-2 font-mono text-[11px] text-muted">{feedStatus}</p>}
              <SecondaryButton type="submit" className="px-2.5 py-1.5 text-[11.5px]">
                Save feed config
              </SecondaryButton>
            </form>

            <div className="mt-5.5 flex items-center justify-between">
              <h4 className="text-[13px]">Actions</h4>
              <div className="flex gap-2.5">
                {widget.status !== "suspended" && (
                  <SecondaryButton type="button" onClick={suspend} className="px-2.5 py-1.5 text-[11.5px]">
                    Suspend
                  </SecondaryButton>
                )}
                {widget.status === "suspended" && (
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

function ChecklistItem({ done, children }: { done: boolean; children: React.ReactNode }) {
  return (
    <div className={`flex items-center gap-2 font-mono text-xs ${done ? "text-good" : "text-muted"}`}>
      <span className={`h-2 w-2 rounded-full ${done ? "bg-good" : "bg-muted-2"}`} />
      {children}
    </div>
  );
}
