"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchApi } from "../lib/api";

type PageItems = { items?: unknown[] };

type SourcingSummary = {
  tracked_product_count: number;
  saved_landed_cost: number | null;
  net_financial_result: number | null;
  next_action: string;
  cart_count: number;
};

function Value({ value, reason = "Connect cost data to see this" }: { value: number | null; reason?: string }) {
  if (value === null) {
    return (
      <span className="stat-unavailable-wrap">
        <span className="stat-unavailable" title="No cost data source is connected yet">Unavailable</span>
        <small className="stat-reason">{reason}</small>
      </span>
    );
  }
  return <strong className="stat-value">{value}</strong>;
}

export function Dashboard() {
  const [sourcing, setSourcing] = useState<SourcingSummary | null>(null);
  const [repeatBuyers, setRepeatBuyers] = useState<number | null>(null);
  const [waitingLists, setWaitingLists] = useState<number | null>(null);
  const [reviews, setReviews] = useState<number | null>(null);
  const [notifications, setNotifications] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    let active = true;
    setLoading(true);
    setError("");
    Promise.all([
      fetchApi<SourcingSummary>("/api/v1/sourcing/dashboard"),
      fetchApi<PageItems>("/api/v1/customer-genome/repeat-buyers?limit=100"),
      fetchApi<PageItems>("/api/v1/customer-genome/product-interests?limit=100"),
      fetchApi<PageItems>("/api/v1/creator-commerce/reviews/library?limit=100"),
      fetchApi<{ count: number }>("/api/v1/notifications/unread-count"),
    ])
      .then(([sourcingData, buyers, waiting, reviewItems, unread]) => {
        if (!active) return;
        setSourcing(sourcingData);
        setRepeatBuyers(buyers.items?.length ?? 0);
        setWaitingLists(waiting.items?.length ?? 0);
        setReviews(reviewItems.items?.length ?? 0);
        setNotifications(unread.count);
      })
      .catch((reason: Error) => {
        if (active) setError(reason.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => load(), [load]);

  const customers = [
    { label: "Repeat buyers", value: repeatBuyers, href: "/customer-genome/repeat-buyers" },
    { label: "Waiting lists", value: waitingLists, href: "/customer-genome/product-interests" },
    { label: "Reviews", value: reviews, href: "/creator-commerce/reviews" },
    { label: "Unread notifications", value: notifications, href: "/notifications" },
  ];

  const onboardingDone = Boolean(sourcing) && sourcing?.next_action !== "Open onboarding";
  const productSearched = (sourcing?.tracked_product_count ?? 0) > 0;
  const cartStarted = (sourcing?.cart_count ?? 0) > 0;
  const isEmpty =
    !loading &&
    Boolean(sourcing) &&
    !productSearched &&
    !cartStarted &&
    customers.every((item) => item.value === 0);
  const nextActionHref = onboardingDone ? "/research" : "/onboarding";

  return (
    <section className="screen" aria-labelledby="dashboard-title">
      <header className="screen-heading">
        <div>
          <p className="eyebrow">WORKSPACE OVERVIEW</p>
          <h1 id="dashboard-title">Dashboard</h1>
          <p className="muted">Live activity across Customer Genome and Review.</p>
        </div>
        <div className="dashboard-heading-actions">
          <span className={error ? "chip chip--error" : "chip"} role="status" aria-live="polite">
            <span className={error ? "status-dot status-dot--error" : "status-dot"} aria-hidden="true" />
            {error ? "API issue" : "Live API"}
          </span>
          {sourcing && !loading && (
            <Link className="secondary-action dashboard-next" href={nextActionHref}>
              {sourcing.next_action}
            </Link>
          )}
        </div>
      </header>

      {error && (
        <div className="state-card error dashboard-error" role="alert">
          <div>
            <strong>Some dashboard data is unavailable</strong>
            <p>{error}</p>
          </div>
          <button type="button" className="retry-button" onClick={load}>
            Retry
          </button>
        </div>
      )}

      <section className="dashboard-section" aria-labelledby="sourcing-metrics">
        <h2 className="dashboard-section-title" id="sourcing-metrics">Sourcing</h2>
        <div className="dashboard-grid dashboard-grid--3">
          {loading && !sourcing ? (
            [0, 1, 2].map((index) => (
              <div className="dashboard-stat" key={index} aria-hidden="true">
                <span className="skeleton-line skeleton-line--sm" />
                <span className="skeleton-line skeleton-line--lg" />
              </div>
            ))
          ) : (
            <>
              <div className="dashboard-stat">
                <span className="stat-label">Products being tracked</span>
                <Value value={sourcing?.tracked_product_count ?? null} reason="Data is unavailable right now" />
              </div>
              <div className="dashboard-stat">
                <span className="stat-label">Saved landed cost</span>
                <Value value={sourcing?.saved_landed_cost ?? null} />
              </div>
              <div className="dashboard-stat">
                <span className="stat-label">Net financial result</span>
                <Value value={sourcing?.net_financial_result ?? null} />
              </div>
            </>
          )}
        </div>
      </section>

      <section className="dashboard-section" aria-labelledby="customer-metrics">
        <h2 className="dashboard-section-title" id="customer-metrics">Customers</h2>
        <div className="dashboard-grid">
          {loading
            ? [0, 1, 2, 3].map((index) => (
                <div className="dashboard-stat" key={index} aria-hidden="true">
                  <span className="skeleton-line skeleton-line--sm" />
                  <span className="skeleton-line skeleton-line--lg" />
                </div>
              ))
            : customers.map((stat) => (
                <Link
                  className="dashboard-stat"
                  href={stat.href}
                  key={stat.label}
                  aria-label={`${stat.label}: ${stat.value ?? "unavailable"}`}
                >
                  <span className="stat-label">{stat.label}</span>
                  <Value value={stat.value} reason="Data is unavailable right now" />
                </Link>
              ))}
        </div>
      </section>

      {isEmpty && (
        <section className="state-card dashboard-start" aria-labelledby="start-title">
          <h2 className="dashboard-start-title" id="start-title">Get started</h2>
          <ol className="start-steps">
            <li data-done={onboardingDone}>
              <span className="start-check" aria-hidden="true">{onboardingDone ? "✓" : ""}</span>
              <div>
                <strong>Complete onboarding</strong>
                <p>Tell the workspace what you sell so it can source for you.</p>
              </div>
              <Link className="secondary-action" href="/onboarding">Open onboarding</Link>
            </li>
            <li data-done={productSearched}>
              <span className="start-check" aria-hidden="true">{productSearched ? "✓" : ""}</span>
              <div>
                <strong>Search a product</strong>
                <p>Run market research on a product idea before you commit.</p>
              </div>
              <Link className="secondary-action" href="/research">Open research</Link>
            </li>
            <li data-done={cartStarted}>
              <span className="start-check" aria-hidden="true">{cartStarted ? "✓" : ""}</span>
              <div>
                <strong>Add to cart</strong>
                <p>Shortlist the listings you want to negotiate with.</p>
              </div>
              <Link className="secondary-action" href="/research/products">Browse products</Link>
            </li>
          </ol>
        </section>
      )}

      <section className="dashboard-quick" aria-labelledby="quick-actions">
        <h2 className="dashboard-section-title" id="quick-actions">Quick actions</h2>
        <div className="dashboard-actions">
          <Link className="primary-action" href="/customer-genome/repeat-buyers">View repeat buyers</Link>
          <Link className="secondary-action" href="/creator-commerce/reviews">Open reviews</Link>
          <Link className="secondary-action" href="/chat">Ask Agent Workspace</Link>
        </div>
      </section>
    </section>
  );
}
