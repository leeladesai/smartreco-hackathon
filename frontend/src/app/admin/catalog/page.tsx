"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useApi } from "@/lib/useApi";
import { ApiError } from "@/lib/api";
import {
  emptyItemForm,
  formToPayload,
  itemToForm,
  type BulkImportResponse,
  type CatalogItem,
  type ItemFormValues,
  type SpecRow,
} from "@/lib/catalog-items";
import type { WidgetResponse } from "@/lib/widgets";
import { Modal, CloseButton } from "@/components/admin-ui";
import { PrimaryButton, SecondaryButton } from "@/components/ui";

const thCls = "border-b border-line px-3 py-2.5 text-left font-mono text-[10.5px] tracking-wide text-muted uppercase";
const tdCls = "border-b border-line-soft px-3 py-3 text-[13px]";
const labelCls = "mb-1.5 block font-mono text-[10.5px] tracking-wide text-muted uppercase";
const inputCls =
  "w-full rounded-md border border-line bg-panel-2 px-3 py-2.5 text-[13.5px] text-text focus:border-rose focus:outline-none";

export default function CatalogPage() {
  const api = useApi();
  const [widgets, setWidgets] = useState<WidgetResponse[]>([]);
  const [widgetsLoading, setWidgetsLoading] = useState(true);
  const [widgetsError, setWidgetsError] = useState<string | null>(null);
  const [widgetId, setWidgetId] = useState<number | null>(null);

  const [items, setItems] = useState<CatalogItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modalItem, setModalItem] = useState<CatalogItem | "new" | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);

  async function loadWidgets() {
    setWidgetsLoading(true);
    setWidgetsError(null);
    try {
      const data = await api<WidgetResponse[]>("/api/admin/widgets");
      setWidgets(data);
      setWidgetId((current) => current ?? data[0]?.id ?? null);
    } catch (err) {
      setWidgetsError(err instanceof ApiError ? err.message : "Could not load widgets.");
    } finally {
      setWidgetsLoading(false);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadWidgets();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function load() {
    if (widgetId === null) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api<CatalogItem[]>(`/api/admin/widgets/${widgetId}/catalog-items`);
      setItems(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the catalog.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [widgetId]);

  async function handleDelete(item: CatalogItem) {
    if (widgetId === null) return;
    if (!window.confirm(`Delete "${item.title}"? This also removes it from the vector index.`)) return;
    try {
      await api(`/api/admin/widgets/${widgetId}/catalog-items/${item.id}`, { method: "DELETE" });
      load();
    } catch (err) {
      window.alert(err instanceof ApiError ? err.message : "Could not delete this item.");
    }
  }

  return (
    <div>
      <div className="mb-5.5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-2 font-mono text-[10.5px] tracking-[0.16em] text-rose uppercase">Curator console</p>
          <h1 className="mb-1.5 text-[26px] tracking-tight">Catalog</h1>
          <p className="max-w-[640px] text-[13.5px] leading-relaxed text-muted">
            Sync status is shown, not hidden &mdash; a green check means the vector store actually reflects this row.
            Each widget has its own catalog, so recommendations never leak between products.
          </p>
        </div>
        <div className="flex gap-2.5">
          <SecondaryButton type="button" onClick={() => setBulkOpen(true)} disabled={widgetId === null}>
            Upload catalog file
          </SecondaryButton>
          <PrimaryButton type="button" onClick={() => setModalItem("new")} disabled={widgetId === null}>
            + Add item
          </PrimaryButton>
        </div>
      </div>

      <div className="mb-4.5 flex items-center gap-2.5">
        <label className={`${labelCls} mb-0`} htmlFor="widget-picker">
          Widget
        </label>
        <select
          id="widget-picker"
          className="rounded-md border border-line bg-panel-2 px-3 py-2 text-[13px] text-text focus:border-rose focus:outline-none"
          value={widgetId ?? ""}
          onChange={(e) => setWidgetId(e.target.value ? Number(e.target.value) : null)}
          disabled={widgetsLoading || widgets.length === 0}
        >
          {widgets.length === 0 && <option value="">No widgets yet</option>}
          {widgets.map((widget) => (
            <option key={widget.id} value={widget.id}>
              {widget.name}
            </option>
          ))}
        </select>
      </div>

      {widgetsError && <p className="font-mono text-[11px] text-rose">{widgetsError}</p>}

      {!widgetsLoading && widgets.length === 0 && !widgetsError && (
        <p className="mt-4 rounded-md border border-line px-4 py-3.5 text-[13px] text-muted">
          No widgets yet &mdash; create one on the Widgets page before adding a catalog.
        </p>
      )}

      {error && <p className="font-mono text-[11px] text-rose">{error}</p>}

      {widgetId !== null && !loading && items.length === 0 && !error && (
        <p className="mt-4 rounded-md border border-line px-4 py-3.5 text-[13px] text-muted">
          No catalog items yet for this widget &mdash; add one, or upload a file.
        </p>
      )}

      {items.length > 0 && (
        <table className="mt-4 w-full border-collapse">
          <thead>
            <tr>
              <th className={thCls}>Title</th>
              <th className={thCls}>Provider</th>
              <th className={thCls}>Category</th>
              <th className={thCls}>Price</th>
              <th className={thCls}>Vector sync</th>
              <th className={thCls}></th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} className="cursor-pointer hover:bg-panel-2" onClick={() => setModalItem(item)}>
                <td className={tdCls}>{item.title}</td>
                <td className={tdCls}>{item.provider}</td>
                <td className={tdCls}>{item.category}</td>
                <td className={tdCls}>{item.price}</td>
                <td className={tdCls}>
                  <span className={`font-mono text-[11px] ${item.vector_synced ? "text-good" : "text-amber"}`}>
                    {item.vector_synced ? "synced" : "indexing"}
                  </span>
                </td>
                <td className={`${tdCls} text-right`} onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    onClick={() => handleDelete(item)}
                    className="font-mono text-[11px] text-muted hover:text-rose"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {modalItem !== null && widgetId !== null && (
        <ItemModal
          widgetId={widgetId}
          item={modalItem === "new" ? null : modalItem}
          onClose={() => {
            setModalItem(null);
            load();
          }}
        />
      )}

      {bulkOpen && widgetId !== null && (
        <BulkUploadModal
          widgetId={widgetId}
          onClose={() => {
            setBulkOpen(false);
            load();
          }}
        />
      )}
    </div>
  );
}

function ItemModal({
  widgetId,
  item,
  onClose,
}: {
  widgetId: number;
  item: CatalogItem | null;
  onClose: () => void;
}) {
  const api = useApi();
  const [form, setForm] = useState<ItemFormValues>(item ? itemToForm(item) : emptyItemForm());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof ItemFormValues>(key: K, value: ItemFormValues[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function setSpec(index: number, patch: Partial<SpecRow>) {
    setForm((f) => ({
      ...f,
      specs: f.specs.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    }));
  }

  function addSpec() {
    setForm((f) => ({ ...f, specs: [...f.specs, { label: "", value: "" }] }));
  }

  function removeSpec(index: number) {
    setForm((f) => ({ ...f, specs: f.specs.filter((_, i) => i !== index) }));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const payload = formToPayload(form);
      if (item) {
        await api(`/api/admin/widgets/${widgetId}/catalog-items/${item.id}`, { method: "PUT", body: payload });
      } else {
        await api(`/api/admin/widgets/${widgetId}/catalog-items`, { method: "POST", body: payload });
      }
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The item could not be saved. Check the fields and try again.");
      setSubmitting(false);
    }
  }

  return (
    <Modal onClose={onClose}>
      <div className="flex items-start justify-between gap-5 border-b border-line-soft px-5.5 py-5 pb-4">
        <div>
          <h3 className="mb-1 text-[17px]">{item ? "Edit item" : "Add item"}</h3>
          <p className="text-xs leading-relaxed text-muted">
            Capture the specs, plus the story that helps a visitor choose it over alternatives.
          </p>
        </div>
        <CloseButton onClose={onClose} />
      </div>
      <form className="px-5.5 py-5" onSubmit={handleSubmit}>
        <div className="grid grid-cols-2 gap-3.5">
          <div>
            <label className={labelCls} htmlFor="item-title">Title</label>
            <input id="item-title" required className={inputCls} value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="e.g. Xpress Credit Personal Loan" />
          </div>
          <div>
            <label className={labelCls} htmlFor="item-provider">Provider</label>
            <input id="item-provider" required className={inputCls} value={form.provider} onChange={(e) => set("provider", e.target.value)} placeholder="e.g. ICICI Bank" />
          </div>
          <div>
            <label className={labelCls} htmlFor="item-category">Category</label>
            <input id="item-category" required className={inputCls} value={form.category} onChange={(e) => set("category", e.target.value)} placeholder="e.g. Personal Loan" />
          </div>
          <div>
            <label className={labelCls} htmlFor="item-price">Price</label>
            <input id="item-price" required className={inputCls} value={form.price} onChange={(e) => set("price", e.target.value)} placeholder="e.g. 10.5%-16% p.a." />
          </div>
        </div>

        <div className="mt-3.5 mb-1.5 flex items-center justify-between">
          <label className={`${labelCls} mb-0`}>Highlight specs</label>
        </div>
        <div className="mb-2 flex flex-col gap-2">
          {form.specs.map((row, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_auto] gap-2">
              <input
                className={inputCls}
                placeholder="Label"
                value={row.label}
                onChange={(e) => setSpec(i, { label: e.target.value })}
              />
              <input
                className={inputCls}
                placeholder="Value"
                value={row.value}
                onChange={(e) => setSpec(i, { value: e.target.value })}
              />
              <button
                type="button"
                onClick={() => removeSpec(i)}
                aria-label="Remove spec"
                className="rounded-md border border-line px-3 text-muted hover:text-rose"
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={addSpec}
          className="mb-4 rounded-md border border-dashed border-line px-3 py-1.5 font-mono text-[11px] text-muted hover:border-muted-2 hover:text-text"
        >
          + Add spec
        </button>

        <div className="mb-4">
          <label className={labelCls} htmlFor="item-tags">Use-case tags</label>
          <input id="item-tags" className={inputCls} value={form.use_case_tags} onChange={(e) => set("use_case_tags", e.target.value)} placeholder="e.g. debt consolidation, medical expenses" />
        </div>
        <div className="mb-4">
          <label className={labelCls} htmlFor="item-description">Description</label>
          <textarea id="item-description" required rows={3} className={`${inputCls} resize-y`} value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="What this is, in plain terms." />
        </div>
        <div className="mb-4">
          <label className={labelCls} htmlFor="item-story">Story &mdash; why this one</label>
          <textarea id="item-story" rows={3} className={`${inputCls} resize-y`} value={form.story} onChange={(e) => set("story", e.target.value)} placeholder="Who should reach for it, and when it beats the alternatives." />
        </div>
        <div className="mb-4">
          <label className={labelCls} htmlFor="item-source">Source URL</label>
          <input id="item-source" type="url" className={inputCls} value={form.source_url} onChange={(e) => set("source_url", e.target.value)} placeholder="https://…" />
        </div>
        {error && <p className="mb-2 font-mono text-[11px] text-rose">{error}</p>}
        <div className="mt-1 flex gap-2.5">
          <PrimaryButton type="submit" disabled={submitting}>
            {submitting ? "Saving…" : "Save item"}
          </PrimaryButton>
          <SecondaryButton type="button" onClick={onClose}>Cancel</SecondaryButton>
        </div>
      </form>
    </Modal>
  );
}

function BulkUploadModal({ widgetId, onClose }: { widgetId: number; onClose: () => void }) {
  const api = useApi();
  const fileRef = useRef<HTMLInputElement>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BulkImportResponse | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setSubmitting(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const data = await api<BulkImportResponse>(`/api/admin/widgets/${widgetId}/catalog-items/bulk-upload`, {
        method: "POST",
        body: formData,
      });
      setResult(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not upload this file.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal onClose={onClose}>
      <div className="flex items-start justify-between gap-5 border-b border-line-soft px-5.5 py-5 pb-4">
        <div>
          <h3 className="mb-1 text-[17px]">Upload catalog file</h3>
          <p className="text-xs leading-relaxed text-muted">
            CSV or JSON, up to 500 rows. Required columns: <code>title</code>, <code>provider</code>,{" "}
            <code>category</code>, <code>price</code>, <code>description</code>. Optional: <code>story</code>,{" "}
            <code>use_case_tags</code> (semicolon-separated), <code>source_url</code>,{" "}
            <code>spec_1_label</code>/<code>spec_1_value</code> through <code>spec_4_label</code>/
            <code>spec_4_value</code>. Rows matching an existing title are skipped, not overwritten.
          </p>
        </div>
        <CloseButton onClose={onClose} />
      </div>
      <form className="px-5.5 py-5" onSubmit={handleSubmit}>
        <div className="mb-4">
          <label className={labelCls} htmlFor="bulk-upload-file">Catalog file</label>
          <input id="bulk-upload-file" ref={fileRef} type="file" accept=".csv,.json" required className={inputCls} />
        </div>
        {error && <p className="mb-2 font-mono text-[11px] text-rose">{error}</p>}
        {result && (
          <div className="mb-4 rounded-md border border-line bg-panel-2 p-3.5 text-[12.5px]">
            <p className="mb-2 text-good">
              {result.inserted} inserted, {result.skipped_duplicate} skipped (duplicate), {result.invalid} invalid.
            </p>
            {result.rows.filter((r) => r.status !== "inserted").length > 0 && (
              <ul className="flex flex-col gap-1 font-mono text-[11px] text-muted">
                {result.rows
                  .filter((r) => r.status !== "inserted")
                  .map((r) => (
                    <li key={r.row}>
                      Row {r.row} ({r.title ?? "untitled"}): {r.status}
                      {r.errors.length > 0 ? ` — ${r.errors.join("; ")}` : ""}
                    </li>
                  ))}
              </ul>
            )}
          </div>
        )}
        <div className="flex gap-2.5">
          {!result && (
            <PrimaryButton type="submit" disabled={submitting}>
              {submitting ? "Uploading…" : "Upload"}
            </PrimaryButton>
          )}
          <SecondaryButton type="button" onClick={onClose}>
            {result ? "Close" : "Cancel"}
          </SecondaryButton>
        </div>
      </form>
    </Modal>
  );
}
