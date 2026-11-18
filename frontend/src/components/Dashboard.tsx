"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchApi } from "../lib/api";

type PageItems = { items?: unknown[] };

export function Dashboard() {
  const [repeatBuyers, setRepeatBuyers] = useState<number | null>(null);
  const [waitingLists, setWaitingLists] = useState<number | null>(null);
  const [reviews, setReviews] = useState<number | null>(null);
  const [notifications, setNotifications] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([
      fetchApi<PageItems>("/api/v1/customer-genome/repeat-buyers?limit=100"),
      fetchApi<PageItems>("/api/v1/customer-genome/product-interests?limit=100"),
      fetchApi<PageItems>("/api/v1/creator-commerce/reviews/library?limit=100"),
      fetchApi<{ count: number }>("/api/v1/notifications/unread-count"),
    ]).then(([buyers, waiting, reviewItems, unread]) => {
      if (!active) return;
      setRepeatBuyers(buyers.items?.length ?? 0);
      setWaitingLists(waiting.items?.length ?? 0);
      setReviews(reviewItems.items?.length ?? 0);
      setNotifications(unread.count);
    }).catch((reason: Error) => active && setError(reason.message));
    return () => { active = false; };
  }, []);

  const stats = [
    { label: "Repeat buyers", value: repeatBuyers, href: "/customer-genome/repeat-buyers" },
    { label: "Waiting lists", value: waitingLists, href: "/customer-genome/product-interests" },
    { label: "Reviews", value: reviews, href: "/creator-commerce/reviews" },
    { label: "Unread notifications", value: notifications, href: "/notifications" },
  ];

  return (
    <section className="screen" aria-labelledby="dashboard-title">
      <div className="screen-heading">
        <div>
          <p className="eyebrow">WORKSPACE OVERVIEW</p>
          <h1 id="dashboard-title">Dashboard</h1>
          <p className="muted">Live activity across Customer Genome and Review.</p>
        </div>
        <span className="chip">Live API</span>
      </div>
      {error && <div className="state-card error" role="alert"><strong>Some dashboard data is unavailable</strong><p>{error}</p></div>}
      <div className="dashboard-grid" aria-label="Dashboard summary">
        {stats.map((stat) => (
          <Link className="dashboard-stat" href={stat.href} key={stat.label}>
            <span className="muted">{stat.label}</span>
            <strong>{stat.value === null ? "Unavailable" : stat.value}</strong>
          </Link>
        ))}
      </div>
      <div className="dashboard-actions">
        <Link className="primary-action" href="/customer-genome/repeat-buyers">View repeat buyers</Link>
        <Link className="secondary-action" href="/creator-commerce/reviews">Open reviews</Link>
        <Link className="secondary-action" href="/chat">Ask Agent Workspace</Link>
      </div>
    </section>
  );
}
