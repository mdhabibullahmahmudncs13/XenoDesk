"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { fetchApi } from "../lib/api";
import { formatDate, formatDateTime, formatMoney } from "../lib/format";

type HistoryItem = {
  product_id: string;
  variant_id: string | null;
  product_name: string;
  quantity: number;
  line_total: string;
};

type HistoryEntry = {
  id: string;
  source_order_id: string;
  ordered_at: string;
  status: string;
  qualifying: boolean;
  total_amount: string;
  refund_amount: string;
  currency: string;
  items: HistoryItem[];
};

type CustomerHistoryResponse = {
  customer_id: string;
  name: string | null;
  order_count: number;
  total_spend: string;
  currency: string;
  last_purchase_at: string | null;
  data_as_of: string;
  items: HistoryEntry[];
  next_cursor: string | null;
  has_more: boolean;
};

function HistoryView() {
  const customerId = useSearchParams().get("customer_id");
  const [history, setHistory] = useState<CustomerHistoryResponse | null>(null);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [loading, setLoading] = useState(Boolean(customerId));
  const [error, setError] = useState("");

  const load = useCallback(
    async (extra: string) => {
      if (!customerId) return;
      setLoading(true);
      setError("");
      try {
        const data = await fetchApi<CustomerHistoryResponse>(
          `/api/v1/customers/${encodeURIComponent(customerId)}/history?limit=50${extra}`,
        );
        setHistory(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load this history.");
      } finally {
        setLoading(false);
      }
    },
    [customerId],
  );

  useEffect(() => {
    void load("");
  }, [load]);

  function applyFilters() {
    const params = new URLSearchParams();
    if (since) params.set("since", new Date(`${since}T00:00:00`).toISOString());
    if (until) params.set("until", new Date(`${until}T23:59:59`).toISOString());
    const extra = params.toString();
    void load(extra ? `&${extra}` : "");
  }

  if (!customerId) {
    return (
      <section className="screen" aria-labelledby="screen-title">
        <div className="screen-heading">
          <div>
            <p className="eyebrow">CUSTOMER GENOME</p>
            <h1 id="screen-title">Customer history</h1>
            <p className="muted">Select a customer to view their authoritative order history.</p>
          </div>
        </div>
        <div className="state-card empty" role="status">
          <strong>No customer selected</strong>
          <p>Pick a customer from the repeat buyers list or search for them.</p>
          <div className="dashboard-actions">
            <Link className="primary-action" href="/customer-genome/repeat-buyers">
              Find a customer
            </Link>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="screen" aria-labelledby="screen-title">
      <div className="screen-heading">
        <div>
          <p className="eyebrow">CUSTOMER GENOME</p>
          <h1 id="screen-title">{history?.name ?? "Customer history"}</h1>
          <p className="muted">Every order in the timeline; totals count qualifying orders only.</p>
        </div>
        <div className="dashboard-heading-actions">
          <Link
            className="secondary-action"
            href={`/customer-genome/product-interests?customer_id=${encodeURIComponent(customerId)}`}
          >
            Add to waiting list
          </Link>
          <Link className="secondary-action" href="/customer-genome/repeat-buyers">
            Back to repeat buyers
          </Link>
        </div>
      </div>

      {error && (
        <div className="state-card error" role="alert">
          <strong>Unable to load this history</strong>
          <p>{error}</p>
        </div>
      )}

      {loading && !history ? (
        <div className="state-card skeleton" aria-label="Loading">
          <div />
          <div />
          <div />
        </div>
      ) : history ? (
        <>
          <div className="cg-figures">
            <div className="cg-figure">
              <span className="muted">Qualifying orders</span>
              <strong>{history.order_count}</strong>
            </div>
            <div className="cg-figure">
              <span className="muted">Total spend</span>
              <strong>{formatMoney(history.total_spend, history.currency)}</strong>
            </div>
            <div className="cg-figure">
              <span className="muted">Last purchase</span>
              <strong>{formatDate(history.last_purchase_at)}</strong>
            </div>
            <div className="cg-figure">
              <span className="muted">Data as of</span>
              <strong>{formatDateTime(history.data_as_of)}</strong>
            </div>
          </div>

          <form
            className="cg-toolbar"
            onSubmit={(event) => {
              event.preventDefault();
              applyFilters();
            }}
          >
            <label className="cg-field">
              <span>From</span>
              <input type="date" value={since} onChange={(event) => setSince(event.target.value)} />
            </label>
            <label className="cg-field">
              <span>To</span>
              <input type="date" value={until} onChange={(event) => setUntil(event.target.value)} />
            </label>
            <button className="secondary-action" type="submit">
              Apply
            </button>
          </form>

          {history.items.length === 0 ? (
            <div className="state-card empty" role="status">
              <strong>No orders in this range</strong>
              <p>This customer has no orders matching the filters.</p>
            </div>
          ) : (
            <ol className="cg-timeline">
              {history.items.map((entry) => (
                <li key={entry.id} className="cg-order">
                  <div className="cg-order-head">
                    <div>
                      <strong>{formatDate(entry.ordered_at)}</strong>
                      <span className="muted">
                        {" "}
                        · order {entry.source_order_id}
                      </span>
                    </div>
                    <div className="cg-order-badges">
                      <span className={entry.qualifying ? "chip" : "unavailable-chip"}>
                        {entry.qualifying ? "Qualifying" : "Not counted"}
                      </span>
                      <span className="cg-status">{entry.status}</span>
                    </div>
                  </div>
                  <table className="cg-items">
                    <thead>
                      <tr>
                        <th scope="col">Product</th>
                        <th scope="col">Qty</th>
                        <th scope="col">Line total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {entry.items.map((item, index) => (
                        <tr key={`${entry.id}-${item.product_id}-${index}`}>
                          <td>{item.product_name}</td>
                          <td>{item.quantity}</td>
                          <td>{formatMoney(item.line_total, entry.currency)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="cg-order-total">
                    Total {formatMoney(entry.total_amount, entry.currency)}
                    {Number(entry.refund_amount) > 0 &&
                      ` · refunded ${formatMoney(entry.refund_amount, entry.currency)}`}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </>
      ) : null}
    </section>
  );
}

export function CustomerHistory() {
  return (
    <Suspense
      fallback={
        <div className="state-card shell-loading" role="status">
          Loading history…
        </div>
      }
    >
      <HistoryView />
    </Suspense>
  );
}
