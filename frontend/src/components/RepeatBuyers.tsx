"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { fetchApi } from "../lib/api";
import { contactOf, formatDate, formatMoney } from "../lib/format";

type CustomerRow = {
  id: string;
  name: string | null;
  phone_e164: string | null;
  email_normalised: string | null;
  order_count: number;
  total_spend: string;
  currency: string;
  last_purchase_at: string | null;
  is_repeat_buyer?: boolean;
};

type ListResponse = {
  items: CustomerRow[];
  next_cursor?: string | null;
  has_more?: boolean;
};

export function RepeatBuyers() {
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [rows, setRows] = useState<CustomerRow[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(
    async (search: string, cursor: string | null, append: boolean) => {
      if (append) setLoadingMore(true);
      else setLoading(true);
      setError("");
      try {
        const path = search
          ? `/api/v1/customer-genome/customers?limit=50&q=${encodeURIComponent(search)}`
          : `/api/v1/customer-genome/repeat-buyers?limit=25${
              cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""
            }`;
        const data = await fetchApi<ListResponse>(path);
        setRows((current) => (append ? [...current, ...data.items] : data.items));
        setNextCursor(data.next_cursor ?? null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load customers.");
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load("", null, false);
  }, [load]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const search = query.trim();
    setAppliedQuery(search);
    void load(search, null, false);
  }

  function clearSearch() {
    setQuery("");
    setAppliedQuery("");
    void load("", null, false);
  }

  return (
    <section className="screen" aria-labelledby="screen-title">
      <div className="screen-heading">
        <div>
          <p className="eyebrow">CUSTOMER GENOME</p>
          <h1 id="screen-title">Repeat buyers</h1>
          <p className="muted">
            Customers with two or more qualifying orders. Search any customer to open their
            history.
          </p>
        </div>
        <Link className="primary-action" href="/customer-genome/product-interests">
          Restore product
        </Link>
      </div>

      <form className="cg-toolbar" onSubmit={submit} role="search">
        <label className="visually-hidden" htmlFor="buyer-search">
          Search customers
        </label>
        <input
          id="buyer-search"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Name, phone (+880…) or email"
        />
        <button className="primary-action" type="submit">
          Search
        </button>
        {appliedQuery && (
          <button className="secondary-action" type="button" onClick={clearSearch}>
            Clear
          </button>
        )}
      </form>

      {appliedQuery && (
        <p className="cg-note">
          Showing every customer matching <strong>{appliedQuery}</strong>. Repeat buyers are
          marked with a chip.
        </p>
      )}

      {error && (
        <div className="state-card error" role="alert">
          <strong>Unable to load customers</strong>
          <p>{error}</p>
        </div>
      )}

      {loading ? (
        <div className="state-card skeleton" aria-label="Loading">
          <div />
          <div />
          <div />
        </div>
      ) : rows.length === 0 ? (
        <div className="state-card empty" role="status">
          <strong>No customers yet</strong>
          <p>
            {appliedQuery
              ? "No customer matches that search."
              : "Customers appear once order history has been synced. A repeat buyer needs two qualifying orders."}
          </p>
        </div>
      ) : (
        <div className="data-card table-wrap">
          <div className="card-header">
            <strong>{appliedQuery ? "Search results" : "Repeat buyers"}</strong>
            <span className="chip">{rows.length} shown</span>
          </div>
          <table>
            <thead>
              <tr>
                <th scope="col">Customer</th>
                <th scope="col">Contact</th>
                <th scope="col">Orders</th>
                <th scope="col">Spend</th>
                <th scope="col">Last purchase</th>
                <th scope="col">History</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <span className="cg-name">
                      {row.name ?? "Unnamed customer"}
                      {row.is_repeat_buyer && <span className="chip">Repeat buyer</span>}
                    </span>
                  </td>
                  <td>{contactOf(row) ?? <span className="unavailable-chip">Unavailable</span>}</td>
                  <td>{row.order_count}</td>
                  <td>{formatMoney(row.total_spend, row.currency)}</td>
                  <td>{formatDate(row.last_purchase_at)}</td>
                  <td>
                    <Link
                      className="cg-link"
                      href={`/customer-genome/history?customer_id=${encodeURIComponent(row.id)}`}
                    >
                      View history
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!appliedQuery && nextCursor && (
            <div className="cg-more">
              <button
                className="secondary-action"
                type="button"
                disabled={loadingMore}
                onClick={() => void load("", nextCursor, true)}
              >
                {loadingMore ? "Loading…" : "Load more"}
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
