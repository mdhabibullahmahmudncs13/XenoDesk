"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { fetchApi } from "../lib/api";
import { formatDateTime } from "../lib/format";

type RestockEvent = {
  id: string;
  product_name: string;
  variant_name: string;
  detected_at: string;
  stock_after: number;
  waiting_count: number;
  batch_count: number;
  last_batch_at: string | null;
  preview_url: string;
};

export function RestockEvents() {
  const [events, setEvents] = useState<RestockEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchApi<{ items: RestockEvent[] }>(
        "/api/v1/customer-genome/restocks?limit=100",
      );
      setEvents(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load restock events.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="screen" aria-labelledby="screen-title">
      <div className="screen-heading">
        <div>
          <p className="eyebrow">CUSTOMER GENOME</p>
          <h1 id="screen-title">Restock events</h1>
          <p className="muted">
            A product moving from out of stock to available. Detecting one notifies the owner
            and sends nothing.
          </p>
        </div>
        <div className="dashboard-heading-actions">
          <Link className="secondary-action" href="/customer-genome/product-interests">
            Waiting lists
          </Link>
        </div>
      </div>

      {error && (
        <div className="state-card error" role="alert">
          <strong>Unable to load restock events</strong>
          <p>{error}</p>
        </div>
      )}

      {loading ? (
        <div className="state-card skeleton" aria-label="Loading">
          <div />
          <div />
          <div />
        </div>
      ) : events.length === 0 ? (
        <div className="state-card empty" role="status">
          <strong>No restocks detected</strong>
          <p>Events appear when inventory sync sees a variant become available again.</p>
        </div>
      ) : (
        <div className="data-card table-wrap">
          <div className="card-header">
            <strong>Detected restocks</strong>
            <span className="chip">{events.length} events</span>
          </div>
          <table>
            <thead>
              <tr>
                <th scope="col">Product</th>
                <th scope="col">Variant</th>
                <th scope="col">Detected</th>
                <th scope="col">Stock</th>
                <th scope="col">Waiting</th>
                <th scope="col">Batch</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id}>
                  <td>{event.product_name}</td>
                  <td>{event.variant_name}</td>
                  <td>{formatDateTime(event.detected_at)}</td>
                  <td>{event.stock_after}</td>
                  <td>{event.waiting_count}</td>
                  <td>
                    {event.batch_count > 0 ? (
                      <span className="chip">
                        Confirmed {formatDateTime(event.last_batch_at)}
                      </span>
                    ) : (
                      <span className="unavailable-chip">Not sent</span>
                    )}
                  </td>
                  <td>
                    {event.waiting_count > 0 ? (
                      <Link className="cg-link" href={event.preview_url}>
                        Preview batch
                      </Link>
                    ) : (
                      <span className="muted">No one waiting</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
