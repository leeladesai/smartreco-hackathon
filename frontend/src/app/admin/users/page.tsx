"use client";

import { useEffect, useState } from "react";
import { useApi } from "@/lib/useApi";
import { useAuth } from "@/context/AuthContext";
import { ApiError } from "@/lib/api";
import type { AdminUser, UsersListResponse } from "@/lib/users";

const PAGE_SIZE = 20;

const thCls = "border-b border-line px-3 py-2.5 text-left font-mono text-[10.5px] tracking-wide text-muted uppercase";
const tdCls = "border-b border-line-soft px-3 py-3 text-[13px]";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export default function UsersPage() {
  const api = useApi();
  const { user: me } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await api<UsersListResponse>(`/api/admin/users?limit=${PAGE_SIZE}&offset=${offset}`);
      setUsers(data.users);
      setHasMore(data.has_more);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load users.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset]);

  async function handleDelete(id: number, email: string) {
    if (!window.confirm(`Delete ${email}? This also removes their tracked activity and recommendation history.`))
      return;
    try {
      await api(`/api/admin/users/${id}`, { method: "DELETE" });
      load();
    } catch (err) {
      window.alert(err instanceof ApiError ? err.message : "Could not delete this user.");
    }
  }

  return (
    <div>
      <div className="mb-5.5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-2 font-mono text-[10.5px] tracking-[0.16em] text-rose uppercase">Curator console</p>
          <h1 className="mb-1.5 text-[26px] tracking-tight">Users</h1>
          <p className="max-w-[640px] text-[13.5px] leading-relaxed text-muted">
            Everyone with access to this tenant. Accounts are provisioned via signup, not created here &mdash; but
            can be removed from here if needed.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="rounded-md border border-line bg-panel-2 px-4 py-2.5 font-sans text-[12.5px] font-semibold text-text hover:border-muted-2"
        >
          Refresh
        </button>
      </div>

      {error && <p className="font-mono text-[11px] text-rose">{error}</p>}

      {!loading && users.length === 0 && !error && (
        <p className="mt-4 rounded-md border border-line px-4 py-3.5 text-[13px] text-muted">No users yet.</p>
      )}

      {users.length > 0 && (
        <table className="mt-4 w-full border-collapse">
          <thead>
            <tr>
              <th className={thCls}>Email</th>
              <th className={thCls}>Role</th>
              <th className={thCls}>Joined</th>
              <th className={thCls}></th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id}>
                <td className={tdCls}>{user.email}</td>
                <td className={`${tdCls} ${user.role === "admin" ? "text-good" : ""}`}>{user.role}</td>
                <td className={tdCls}>{formatDate(user.created_at)}</td>
                <td className={`${tdCls} text-right`}>
                  {user.id !== me?.id && (
                    <button
                      type="button"
                      onClick={() => handleDelete(user.id, user.email)}
                      className="font-mono text-[11px] text-muted hover:text-rose"
                    >
                      Delete
                    </button>
                  )}
                </td>
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
