"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { BubbleOverlay } from "./BubbleOverlay";
import { clearAccessToken, fetchApi } from "../lib/api";

const groups = [
  {
    label: "Overview",
    links: [{ label: "Dashboard", href: "/dashboard" }],
  },
  {
    label: "Sourcing Workspace",
    links: [
      { label: "Onboarding", href: "/onboarding" },
      { label: "Market intelligence", href: "/research" },
      { label: "Product search", href: "/research/products" },
      { label: "Cart", href: "/cart" },
    ],
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
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (pathname === "/" || pathname === "/login" || pathname === "/signup" || pathname === "/auth/login" || pathname === "/auth/signup") return;
    fetchApi<{ role: string }>("/api/v1/auth/me")
      .then((user) => setRole(user.role))
      .catch(() => {
        clearAccessToken();
        router.replace("/login");
      });
  }, [pathname, router]);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!menuOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [menuOpen]);

  if (pathname === "/" || pathname === "/login" || pathname === "/signup" || pathname === "/auth/login" || pathname === "/auth/signup") return <>{children}</>;
  if (role === null) return <div className="state-card shell-loading" role="status">Loading workspace…</div>;

  const canManage = role === "owner" || role === "admin";
  return (
    <div className="app-shell">
      {menuOpen && (
        <button
          className="nav-scrim"
          type="button"
          aria-label="Close navigation"
          onClick={() => setMenuOpen(false)}
        />
      )}
      <aside id="primary-navigation" className={menuOpen ? "sidebar open" : "sidebar"} aria-label="Primary navigation">
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
        <Link className="settings-link" href="/settings/profile">Profile settings</Link>
        {canManage && <Link className="settings-link" href="/settings">Admin settings</Link>}
      </aside>
      <main className="main-region">
        <header className="topbar">
          <button
            className="nav-menu-button"
            type="button"
            aria-controls="primary-navigation"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            Menu
          </button>
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
