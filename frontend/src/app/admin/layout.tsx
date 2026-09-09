"use client";

import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect, type ReactNode } from "react";
import { useAuth } from "@/context/AuthContext";

const ADMIN_LINKS = [
  { href: "/admin/overview", label: "Overview" },
  { href: "/admin/widgets", label: "Widgets" },
  { href: "/admin/catalog", label: "Catalog" },
  { href: "/admin/users", label: "Users" },
  { href: "/admin/observability", label: "Observability" },
];

const PLATFORM_ADMIN_LINKS = [{ href: "/admin/tenants", label: "Tenants" }];

/**
 * The single shell both roles land in after login — one nav bar, role-scoped links,
 * matching the old Jinja console's base.html (which already merged admin and
 * platform_admin into one console with one nav, just different visible links per
 * role) rather than two separate consoles/routes.
 */
export default function AdminLayout({ children }: { children: ReactNode }) {
  const { user, ready, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (ready && !user) router.replace("/login");
  }, [ready, user, router]);

  if (!ready || !user) return null;

  const links = user.role === "platform_admin" ? PLATFORM_ADMIN_LINKS : ADMIN_LINKS;

  return (
    <div>
      <header className="sticky top-0 z-50 flex flex-wrap items-center gap-1.5 border-b border-line bg-bg/88 px-5 py-3.5 backdrop-blur-md">
        <div className="mr-2.5 inline-flex items-center gap-1.5 rounded border border-line px-2.5 py-1.5 font-mono text-sm font-bold tracking-[0.14em] text-rose">
          <svg width="14" height="14" viewBox="0 0 18 18" aria-hidden="true">
            <rect x="1" y="10" width="3.4" height="7" rx="1" fill="#5ec8d8" />
            <rect x="6.3" y="6" width="3.4" height="11" rx="1" fill="#e8a33d" />
            <rect x="11.6" y="2" width="3.4" height="15" rx="1" fill="#a78bfa" />
          </svg>
          TRAILMIND <small className="font-normal tracking-wide text-muted">/ admin console</small>
        </div>

        <nav className="flex gap-0.5">
          {links.map((link) => {
            const active = pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`rounded px-3.5 py-2.5 font-mono text-[11.5px] font-bold tracking-wide uppercase select-none ${
                  active ? "bg-rose text-bg" : "border border-transparent text-muted hover:border-line hover:text-text"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>

        <div className="flex-1" />
        <div className="mr-2 rounded-full border border-dashed border-line px-2.5 py-1.5 font-mono text-[10.5px] text-muted">
          signed in as: {user.email} ({user.role})
        </div>
        <button
          type="button"
          onClick={logout}
          className="rounded-md border border-line px-3 py-1.5 font-mono text-[11px] text-muted hover:border-muted-2 hover:text-text"
        >
          Log out
        </button>
      </header>

      <div className="mx-auto max-w-[1180px] px-5 pt-7 pb-[90px]">{children}</div>
    </div>
  );
}
