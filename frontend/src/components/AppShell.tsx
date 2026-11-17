"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { BubbleOverlay } from "./BubbleOverlay";
import { clearAccessToken, fetchApi } from "../lib/api";

const groups = [
  {
    label: "Overview",
    links: [{ label: "Dashboard", href: "/" }],
  },
  {
    label: "Customer Genome",
    links: [
      { label: "Repeat buyers", href: "/customer-genome/repeat-buyers" },
      { label: "Restore product", href: "/customer-genome/product-interests" },
    ],
  },
  {
    label: "Creator Commerce",
    links: [
      { label: "Reviews", href: "/creator-commerce/reviews", adminOnly: true },
      { label: "Marketing cards", href: "/creator-commerce/reviews/cards", adminOnly: true },
      { label: "Ads intelligence", href: "/creator-commerce/ads" },
      { label: "My ads", href: "/creator-commerce/ads/own" },
      { label: "Collaborations", href: "/creator-commerce/collaborations" },
      { label: "Influencers", href: "/creator-commerce/influencers" },
    ],
  },
  {
    label: "Agent Workspace",
    links: [
      { label: "Chat", href: "/chat" },
      { label: "Tour", href: "/tour" },
    ],
  },
];

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();
  const router = useRouter();
  const [role, setRole] = useState<string | null>(null);

  useEffect(() => {
    if (pathname === "/" || pathname === "/login" || pathname === "/signup" || pathname === "/auth/login" || pathname === "/auth/signup") return;
    fetchApi<{ role: string }>("/api/v1/auth/me")
      .then((user) => setRole(user.role))
      .catch(() => {
        clearAccessToken();
        router.replace("/login");
      });
  }, [pathname, router]);

  if (pathname === "/" || pathname === "/login" || pathname === "/signup" || pathname === "/auth/login" || pathname === "/auth/signup") return <>{children}</>;
  if (role === null) return <div className="state-card shell-loading" role="status">Loading workspace…</div>;

  const canManage = role === "owner" || role === "admin";
  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Primary navigation">
        <Link className="brand" href="/">
          XENOVARIENTS
        </Link>
        <nav>
          {groups.map((group) => (
            <section key={group.label} className="nav-group">
              <p className="eyebrow">{group.label}</p>
              {group.links.map((link) => (
                (!link.adminOnly || canManage) && (
                <Link
                  className={pathname === link.href ? "nav-link active" : "nav-link"}
                  href={link.href}
                  key={link.href}
                >
                  {link.label}
                </Link>
                )
              ))}
            </section>
          ))}
        </nav>
        {canManage && <Link className="settings-link" href="/settings">Settings</Link>}
      </aside>
      <main className="main-region">
        <header className="topbar">
          <span className="topbar-title">Workspace</span>
          <div className="topbar-actions">
            <Link href="/notifications" aria-label="Notifications">Notifications</Link>
            <button type="button" onClick={() => { clearAccessToken(); router.replace("/login"); }}>Sign out</button>
          </div>
        </header>
        <div className="content-region">{children}</div>
        <BubbleOverlay />
      </main>
    </div>
  );
}
