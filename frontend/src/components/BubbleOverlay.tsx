"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { fetchApi, subscribeToEvents } from "../lib/api";
import { formatDate, formatDateTime, formatMoney } from "../lib/format";

type Bubble = {
  id: string;
  customer: { id: string; name: string | null; initials: string | null };
  is_returning_customer: boolean;
  state: string;
  previous_order_count: number;
  total_purchase_amount: string;
  currency: string;
  last_purchase_date: string | null;
  last_message_at: string;
  last_message_preview: string | null;
  data_as_of: string;
  link_customer_offered: boolean;
  history_url: string | null;
};

type BubbleResponse = { items: Bubble[] };

export function BubbleOverlay() {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const response = await fetchApi<BubbleResponse>("/api/v1/customer-genome/returning-bubbles");
      setBubbles(response.items);
    } catch {
      // The workspace stays usable when the optional overlay is unavailable.
    }
  }, []);

  useEffect(() => {
    void refresh();
    const unsubscribe = subscribeToEvents(
      (event) => {
        if (event.type.startsWith("bubble.")) void refresh();
      },
      () => void refresh(),
    );
    const timer = window.setInterval(() => void refresh(), 30000);
    return () => {
      unsubscribe();
      window.clearInterval(timer);
    };
  }, [refresh]);

  async function setState(id: string, state: "seen" | "dismissed") {
    try {
      await fetchApi(`/api/v1/customer-genome/returning-bubbles/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state }),
      });
    } catch {
      // A failed state change leaves the bubble as it was on the next refresh.
    }
    if (state === "dismissed") {
      setBubbles((current) => current.filter((bubble) => bubble.id !== id));
      if (openId === id) setOpenId(null);
    } else {
      await refresh();
    }
  }

  function toggle(bubble: Bubble) {
    if (openId === bubble.id) {
      setOpenId(null);
      return;
    }
    setOpenId(bubble.id);
    if (bubble.state === "new") void setState(bubble.id, "seen");
  }

  if (bubbles.length === 0) return null;

  return (
    <aside className="bubble-stack" aria-label="Returning customer alerts">
      {bubbles.slice(0, 3).map((bubble) => {
        const open = openId === bubble.id;
        return (
          <article className="bubble-card" key={bubble.id}>
            <button
              className="bubble-head"
              type="button"
              aria-expanded={open}
              onClick={() => toggle(bubble)}
            >
              <span className="bubble-avatar" aria-hidden="true">
                {bubble.customer.initials ?? "?"}
              </span>
              <span className="bubble-title">
                {bubble.is_returning_customer ? (
                  <>
                    <span className="chip">Returning customer</span>
                    <strong>{bubble.customer.name ?? "Customer"}</strong>
                    <span className="muted">
                      {bubble.previous_order_count} orders ·{" "}
                      {formatMoney(bubble.total_purchase_amount, bubble.currency)}
                    </span>
                  </>
                ) : (
                  <strong>Customer identity unresolved</strong>
                )}
              </span>
              {bubble.state === "new" && <span className="bubble-dot" aria-label="New message" />}
            </button>

            {bubble.last_message_preview && <p>{bubble.last_message_preview}</p>}

            {open && (
              <dl className="bubble-detail">
                <div>
                  <dt>Last purchase</dt>
                  <dd>{formatDate(bubble.last_purchase_date)}</dd>
                </div>
                <div>
                  <dt>Message</dt>
                  <dd>{formatDateTime(bubble.last_message_at)}</dd>
                </div>
                <div>
                  <dt>Figures as of</dt>
                  <dd>{formatDateTime(bubble.data_as_of)}</dd>
                </div>
              </dl>
            )}

            <div className="bubble-actions">
              {bubble.history_url && (
                <Link
                  className="bubble-action"
                  href={`/customer-genome/history?customer_id=${encodeURIComponent(bubble.customer.id)}`}
                >
                  View history
                </Link>
              )}
              <Link
                className="bubble-action"
                href={`/customer-genome/product-interests?customer_id=${encodeURIComponent(
                  bubble.customer.id,
                )}`}
              >
                Add to waiting list
              </Link>
              <button type="button" onClick={() => void setState(bubble.id, "dismissed")}>
                Dismiss
              </button>
            </div>
          </article>
        );
      })}
      {bubbles.length > 3 && (
        <Link className="chip" href="/customer-genome/repeat-buyers">
          +{bubbles.length - 3} more alerts
        </Link>
      )}
    </aside>
  );
}
