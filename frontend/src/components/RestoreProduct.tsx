"use client";

import { FormEvent, Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { fetchApi } from "../lib/api";
import { contactOf, formatDate } from "../lib/format";

type WaitingEntry = {
  interest_id: string;
  customer_id: string;
  customer_name: string | null;
  contact_channel: string;
  contact_value: string;
  requested_at: string;
  quantity: number | null;
};

type WaitingGroup = {
  product_id: string;
  product_name: string;
  variant_id: string;
  variant_name: string;
  stock_on_hand: number;
  is_available: boolean;
  waiting_count: number;
  entries: WaitingEntry[];
};

type WaitingListResponse = { items: WaitingGroup[]; has_more: boolean };

type Customer = {
  id: string;
  name: string | null;
  phone_e164: string | null;
  email_normalised: string | null;
  order_count: number;
};

type Variant = { id: string; name: string; is_available: boolean; stock_on_hand: number };
type Product = { id: string; name: string; category: string | null; variants: Variant[] };

const CHANNELS = ["email", "sms", "messenger", "whatsapp"] as const;

function RestoreProductView() {
  const preselectedId = useSearchParams().get("customer_id");

  const [groups, setGroups] = useState<WaitingGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [customerQuery, setCustomerQuery] = useState("");
  const [matches, setMatches] = useState<Customer[]>([]);
  const [selected, setSelected] = useState<Customer | null>(null);
  const [searching, setSearching] = useState(false);

  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState("");
  const [variantId, setVariantId] = useState("");
  const [channel, setChannel] = useState<string>("email");
  const [contactValue, setContactValue] = useState("");
  const [quantity, setQuantity] = useState("");

  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [formError, setFormError] = useState("");

  const loadWaiting = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchApi<WaitingListResponse>(
        "/api/v1/customer-genome/product-interests?limit=100",
      );
      setGroups(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load waiting lists.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadWaiting();
    fetchApi<{ items: Product[] }>("/api/v1/customer-genome/products?limit=200")
      .then((data) => setProducts(data.items))
      .catch(() => setProducts([]));
  }, [loadWaiting]);

  useEffect(() => {
    if (!preselectedId) return;
    fetchApi<{ customer_id: string; name: string | null; order_count: number }>(
      `/api/v1/customers/${encodeURIComponent(preselectedId)}/history?limit=1`,
    )
      .then((data) =>
        setSelected({
          id: data.customer_id,
          name: data.name,
          phone_e164: null,
          email_normalised: null,
          order_count: data.order_count,
        }),
      )
      .catch(() => undefined);
  }, [preselectedId]);

  async function searchCustomers() {
    if (!customerQuery.trim()) return;
    setSearching(true);
    setFormError("");
    try {
      const data = await fetchApi<{ items: Customer[] }>(
        `/api/v1/customer-genome/customers?limit=25&q=${encodeURIComponent(customerQuery.trim())}`,
      );
      setMatches(data.items);
      if (data.items.length === 0) setFormError("No customer matches that search.");
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to search customers.");
    } finally {
      setSearching(false);
    }
  }

  function pickCustomer(customer: Customer) {
    setSelected(customer);
    setMatches([]);
    setCustomerQuery("");
    setContactValue(contactOf(customer) ?? "");
  }

  const product = products.find((item) => item.id === productId) ?? null;
  const variants = product?.variants ?? [];

  function chooseProduct(next: string) {
    setProductId(next);
    const nextProduct = products.find((item) => item.id === next);
    setVariantId(nextProduct?.variants[0]?.id ?? "");
  }

  async function addInterest(event: FormEvent) {
    event.preventDefault();
    setFormError("");
    setNotice("");
    if (!selected || !productId || !variantId) {
      setFormError("Choose a customer and a product variant first.");
      return;
    }
    setSaving(true);
    try {
      await fetchApi("/api/v1/customer-genome/product-interests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_id: selected.id,
          product_id: productId,
          variant_id: variantId,
          contact_channel: channel,
          contact_value: contactValue.trim() || null,
          quantity: quantity ? Number(quantity) : null,
        }),
      });
      setNotice(`${selected.name ?? "The customer"} was added to the waiting list.`);
      setQuantity("");
      await loadWaiting();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to add the customer.");
    } finally {
      setSaving(false);
    }
  }

  const totalWaiting = groups.reduce((sum, group) => sum + group.waiting_count, 0);

  return (
    <section className="screen" aria-labelledby="screen-title">
      <div className="screen-heading">
        <div>
          <p className="eyebrow">CUSTOMER GENOME</p>
          <h1 id="screen-title">Restore product</h1>
          <p className="muted">
            Waiting lists by product and variant. A restock never sends anything by itself.
          </p>
        </div>
        <div className="dashboard-heading-actions">
          <Link className="secondary-action" href="/customer-genome/restock-events">
            Restock events
          </Link>
          <Link className="secondary-action" href="/customer-genome/repeat-buyers">
            Repeat buyers
          </Link>
        </div>
      </div>

      <div className="cg-split">
        <form className="data-card cg-form" onSubmit={addInterest}>
          <div className="card-header">
            <strong>Add to waiting list</strong>
            <span className="chip">Staff action</span>
          </div>

          <fieldset className="cg-fieldset">
            <legend>Customer</legend>
            {selected ? (
              <div className="cg-selected">
                <div>
                  <strong>{selected.name ?? "Unnamed customer"}</strong>
                  <span className="muted">
                    {" "}
                    · {selected.order_count} qualifying order
                    {selected.order_count === 1 ? "" : "s"}
                  </span>
                </div>
                <button className="cg-link" type="button" onClick={() => setSelected(null)}>
                  Change
                </button>
              </div>
            ) : (
              <>
                <div className="cg-inline">
                  <label className="visually-hidden" htmlFor="waiting-customer">
                    Search customers
                  </label>
                  <input
                    id="waiting-customer"
                    type="search"
                    value={customerQuery}
                    onChange={(event) => setCustomerQuery(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter") return;
                      // Enter searches instead of submitting the Add to waiting list form.
                      event.preventDefault();
                      void searchCustomers();
                    }}
                    placeholder="Name, phone or email"
                  />
                  <button
                    className="secondary-action"
                    type="button"
                    onClick={() => void searchCustomers()}
                    disabled={searching}
                  >
                    {searching ? "Searching…" : "Find"}
                  </button>
                </div>
                {matches.length > 0 && (
                  <ul className="cg-matches">
                    {matches.map((customer) => (
                      <li key={customer.id}>
                        <button type="button" onClick={() => pickCustomer(customer)}>
                          <strong>{customer.name ?? "Unnamed customer"}</strong>
                          <span className="muted">
                            {contactOf(customer) ?? "No contact"} · {customer.order_count} orders
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </fieldset>

          <fieldset className="cg-fieldset">
            <legend>Product</legend>
            <label className="cg-field">
              <span>Product</span>
              <select value={productId} onChange={(event) => chooseProduct(event.target.value)}>
                <option value="">Select a product</option>
                {products.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="cg-field">
              <span>Variant</span>
              <select
                value={variantId}
                onChange={(event) => setVariantId(event.target.value)}
                disabled={variants.length === 0}
              >
                <option value="">Select a variant</option>
                {variants.map((variant) => (
                  <option key={variant.id} value={variant.id}>
                    {variant.name}
                    {variant.is_available
                      ? ` — ${variant.stock_on_hand} in stock`
                      : " — out of stock"}
                  </option>
                ))}
              </select>
            </label>
            {product && variants.length === 0 && (
              <p className="cg-note">This product has no variants yet, so no interest can be recorded.</p>
            )}
          </fieldset>

          <fieldset className="cg-fieldset">
            <legend>Contact</legend>
            <label className="cg-field">
              <span>Channel</span>
              <select value={channel} onChange={(event) => setChannel(event.target.value)}>
                {CHANNELS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label className="cg-field">
              <span>Address (optional)</span>
              <input
                type="text"
                value={contactValue}
                onChange={(event) => setContactValue(event.target.value)}
                placeholder="Defaults to the customer's email or phone"
              />
            </label>
            <label className="cg-field">
              <span>Quantity (optional)</span>
              <input
                type="number"
                min="1"
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
                placeholder="1"
              />
            </label>
          </fieldset>

          {formError && (
            <p className="error-text" role="alert">
              {formError}
            </p>
          )}
          {notice && (
            <p className="cg-success" role="status">
              {notice}
            </p>
          )}
          <button className="primary-action" type="submit" disabled={saving}>
            {saving ? "Adding…" : "Add to waiting list"}
          </button>
        </form>

        <div className="cg-groups">
          <div className="cg-groups-head">
            <strong>Waiting lists</strong>
            <span className="chip">{totalWaiting} waiting</span>
          </div>

          {error && (
            <div className="state-card error" role="alert">
              <strong>Unable to load waiting lists</strong>
              <p>{error}</p>
            </div>
          )}

          {loading ? (
            <div className="state-card skeleton" aria-label="Loading">
              <div />
              <div />
              <div />
            </div>
          ) : groups.length === 0 ? (
            <div className="state-card empty" role="status">
              <strong>No waiting lists</strong>
              <p>Add a customer to a variant and the list appears here.</p>
            </div>
          ) : (
            groups.map((group) => (
              <article className="data-card cg-group" key={`${group.product_id}-${group.variant_id}`}>
                <div className="cg-group-head">
                  <div>
                    <strong>{group.product_name}</strong>
                    <p className="muted">{group.variant_name}</p>
                  </div>
                  <div className="cg-order-badges">
                    <span className={group.is_available ? "chip" : "unavailable-chip"}>
                      {group.is_available ? `${group.stock_on_hand} in stock` : "Out of stock"}
                    </span>
                    <span className="cg-status">{group.waiting_count} waiting</span>
                  </div>
                </div>
                <ul className="cg-waiters">
                  {group.entries.map((entry) => (
                    <li key={entry.interest_id}>
                      <div>
                        <strong>{entry.customer_name ?? "Unnamed customer"}</strong>
                        <span className="muted">
                          {" "}
                          · {entry.contact_channel}: {entry.contact_value}
                        </span>
                      </div>
                      <span className="muted">
                        {formatDate(entry.requested_at)}
                        {entry.quantity ? ` · ${entry.quantity} pcs` : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              </article>
            ))
          )}
        </div>
      </div>
    </section>
  );
}

export function RestoreProduct() {
  return (
    <Suspense
      fallback={
        <div className="state-card shell-loading" role="status">
          Loading waiting lists…
        </div>
      }
    >
      <RestoreProductView />
    </Suspense>
  );
}
