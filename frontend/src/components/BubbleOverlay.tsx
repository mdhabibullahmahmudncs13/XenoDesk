"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchApi, subscribeToEvents } from "../lib/api";

type Bubble = {
  id: string;
  customer: { id: string; name: string | null; initials: string | null };
  is_returning_customer: boolean;
  state: string;
  previous_order_count: number;
  total_purchase_amount: string;
  currency: string;
  last_message_preview: string | null;
  link_customer_offered: boolean;
  history_url: string | null;
};

type BubbleResponse = { items: Bubble[] };

export function BubbleOverlay() {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const refresh = useCallback(async () => {
    try {
      const response = await fetchApi<BubbleResponse>("/api/v1/customer-genome/returning-bubbles");
      setBubbles(response.items);
    } catch {
      // The dashboard remains usable when the optional overlay is unavailable.
    }
  }, []);

  useEffect(() => {
    void refresh();
    const unsubscribe = subscribeToEvents((event) => {
      if (event.type.startsWith("bubble.")) void refresh();
    }, () => void refresh());
    const timer = window.setInterval(() => void refresh(), 30000);
    return () => {
      unsubscribe();
      window.clearInterval(timer);
    };
  }, [refresh]);

  async function dismiss(id: string) {
    await fetchApi(`/api/v1/customer-genome/returning-bubbles/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state: "dismissed" }),
    });
    setBubbles((current) => current.filter((bubble) => bubble.id !== id));
  }

  if (bubbles.length === 0) return null;
  return (
    <aside className="bubble-stack" aria-label="Returning customer alerts">
      {bubbles.slice(0, 3).map((bubble) => (
        <article className="bubble-card" key={bubble.id}>
          {bubble.is_returning_customer ? (
            <>
              <span className="chip">Returning customer</span>
              <strong>{bubble.customer.name ?? "Customer"}</strong>
              <span className="muted">
                {bubble.previous_order_count} orders · {bubble.total_purchase_amount} {bubble.currency}
              </span>
            </>
          ) : (
            <strong>Customer identity unresolved</strong>
          )}
          {bubble.last_message_preview && <p>{bubble.last_message_preview}</p>}
          <div className="bubble-actions">
            {bubble.link_customer_offered && bubble.history_url && (
              <a className="bubble-action" href={`/customer-genome/history?customer_id=${bubble.customer.id}`}>View customer history</a>
            )}
            <button type="button" onClick={() => void dismiss(bubble.id)}>Dismiss</button>
          </div>
        </article>
      ))}
      {bubbles.length > 3 && <span className="chip">+{bubbles.length - 3} more alerts</span>}
    </aside>
  );
}
