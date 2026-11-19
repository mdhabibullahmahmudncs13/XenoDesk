"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { fetchApi } from "../lib/api";
import { formatDateTime } from "../lib/format";

type Template = {
  id: string | null;
  body: string;
  version: number;
  is_default: boolean;
  merge_fields: string[];
};

type Recipient = {
  customer_id: string;
  customer_name: string | null;
  channel: string;
  contact_value: string;
  message: string;
  eligible: boolean;
  skip_reason: string | null;
};

type Preview = {
  restock_event_id: string;
  waiting_count: number;
  eligible_count: number;
  skipped_count: number;
  stock_after: number;
  stock_warning: { stock_after: number; waiting_demand: number; message: string } | null;
  recipients: Recipient[];
};

type EventSummary = {
  id: string;
  product_name: string;
  variant_name: string;
  stock_after: number;
  waiting_count: number;
};

type Delivery = {
  customer_id: string;
  channel: string;
  status: string;
  skip_reason: string | null;
  attempt_count: number;
  sent_at: string | null;
  delivered_at: string | null;
};

type Confirmation = {
  batch_id: string;
  queued: number;
  duplicates: number;
  skipped: { customer_id: string; reason: string }[];
  stock_warning: { message: string } | null;
};

export function BatchPreview({ eventId }: { eventId: string }) {
  const [template, setTemplate] = useState<Template | null>(null);
  const [body, setBody] = useState("");
  const [event, setEvent] = useState<EventSummary | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [role, setRole] = useState<string | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);

  const loadDeliveries = useCallback(async () => {
    try {
      const data = await fetchApi<{ items: Delivery[] }>(
        `/api/v1/customer-genome/restocks/${encodeURIComponent(eventId)}/notifications`,
      );
      setDeliveries(data.items);
    } catch {
      setDeliveries([]);
    }
  }, [eventId]);

  useEffect(() => {
    fetchApi<Template>("/api/v1/customer-genome/restock-template")
      .then((data) => {
        setTemplate(data);
        setBody(data.body);
      })
      .catch((err: Error) => setError(err.message));
    fetchApi<{ items: EventSummary[] }>("/api/v1/customer-genome/restocks?limit=100")
      .then((data) => setEvent(data.items.find((item) => item.id === eventId) ?? null))
      .catch(() => setEvent(null));
    fetchApi<{ role: string }>("/api/v1/auth/me")
      .then((user) => setRole(user.role))
      .catch(() => setRole(null));
    void loadDeliveries();
  }, [eventId, loadDeliveries]);

  async function saveTemplate(): Promise<Template | null> {
    const saved = await fetchApi<Template>("/api/v1/customer-genome/restock-template", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    });
    setTemplate(saved);
    setBody(saved.body);
    return saved;
  }

  async function runPreview() {
    setBusy(true);
    setError("");
    setNotice("");
    setConfirmation(null);
    try {
      const saved = template?.id ? template : await saveTemplate();
      const data = await fetchApi<Preview>(
        `/api/v1/customer-genome/restocks/${encodeURIComponent(eventId)}/preview?template_id=${encodeURIComponent(
          saved?.id ?? "",
        )}`,
      );
      setPreview(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to build the preview.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmBatch() {
    if (!template?.id || !preview) {
      setError("Preview the batch before confirming it.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await fetchApi<Confirmation>(
        `/api/v1/customer-genome/restocks/${encodeURIComponent(eventId)}/notifications`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": crypto.randomUUID(),
          },
          body: JSON.stringify({
            template_id: template.id,
            template_version: template.version,
          }),
        },
      );
      setConfirmation(result);
      setNotice(`${result.queued} message${result.queued === 1 ? "" : "s"} queued.`);
      await loadDeliveries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to confirm the batch.");
    } finally {
      setBusy(false);
    }
  }

  const isOwner = role === "owner";

  return (
    <section className="screen" aria-labelledby="screen-title">
      <div className="screen-heading">
        <div>
          <p className="eyebrow">CUSTOMER GENOME · RESTORE PRODUCT</p>
          <h1 id="screen-title">Batch preview</h1>
          <p className="muted">
            {event
              ? `${event.product_name} · ${event.variant_name} — ${event.stock_after} in stock, ${event.waiting_count} waiting`
              : "Confirming is the only action that sends a restock message."}
          </p>
        </div>
        <Link className="secondary-action" href="/customer-genome/restock-events">
          Restock events
        </Link>
      </div>

      <div className="data-card cg-form">
        <div className="card-header">
          <strong>Message template</strong>
          <span className="chip">
            {template?.is_default ? "Default" : `Version ${template?.version ?? 1}`}
          </span>
        </div>
        <p className="cg-note">
          Merge fields: {template?.merge_fields.map((field) => `{{${field}}}`).join(", ") ?? "—"}.
          A message must not promise reserved stock.
        </p>
        <label className="cg-field">
          <span className="visually-hidden">Template body</span>
          <textarea
            className="cg-textarea"
            value={body}
            onChange={(change) => setBody(change.target.value)}
            rows={6}
          />
        </label>
        <div className="cg-form-actions">
          <button className="primary-action" type="button" onClick={() => void runPreview()} disabled={busy}>
            {busy ? "Working…" : "Preview batch"}
          </button>
          <button
            className="secondary-action"
            type="button"
            disabled={busy}
            onClick={() => {
              setBusy(true);
              setError("");
              saveTemplate()
                .then((saved) => setNotice(`Template saved as version ${saved?.version}.`))
                .catch((err: Error) => setError(err.message))
                .finally(() => setBusy(false));
            }}
          >
            Save template
          </button>
        </div>
      </div>

      {error && (
        <div className="state-card error" role="alert">
          <strong>Something needs attention</strong>
          <p>{error}</p>
        </div>
      )}
      {notice && (
        <p className="cg-success" role="status">
          {notice}
        </p>
      )}

      {preview && (
        <div className="data-card cg-preview">
          <div className="card-header">
            <strong>Recipients</strong>
            <span className="chip">
              {preview.eligible_count} eligible · {preview.skipped_count} skipped
            </span>
          </div>
          {preview.stock_warning && (
            <p className="cg-warning" role="status">
              {preview.stock_warning.message}
            </p>
          )}
          <table>
            <thead>
              <tr>
                <th scope="col">Customer</th>
                <th scope="col">Channel</th>
                <th scope="col">Message</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {preview.recipients.map((recipient) => (
                <tr key={`${recipient.customer_id}-${recipient.channel}`}>
                  <td>{recipient.customer_name ?? "Unnamed customer"}</td>
                  <td>
                    {recipient.channel}
                    <br />
                    <span className="muted">{recipient.contact_value || "no address"}</span>
                  </td>
                  <td className="cg-message">{recipient.message}</td>
                  <td>
                    {recipient.eligible ? (
                      <span className="chip">Eligible</span>
                    ) : (
                      <span className="unavailable-chip">
                        Skipped: {(recipient.skip_reason ?? "ineligible").replaceAll("_", " ")}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="cg-form-actions">
            {isOwner ? (
              <button
                className="primary-action"
                type="button"
                onClick={() => void confirmBatch()}
                disabled={busy || preview.eligible_count === 0}
              >
                Confirm and queue {preview.eligible_count} message
                {preview.eligible_count === 1 ? "" : "s"}
              </button>
            ) : (
              <p className="cg-note">Only the Owner can confirm a restock batch.</p>
            )}
          </div>
        </div>
      )}

      {confirmation && (
        <div className="data-card">
          <div className="card-header">
            <strong>Delivery history</strong>
            <span className="chip">{deliveries.length} recipients</span>
          </div>
          {confirmation.duplicates > 0 && (
            <p className="cg-note">
              {confirmation.duplicates} recipient
              {confirmation.duplicates === 1 ? " was" : "s were"} already queued for this event
              and {confirmation.duplicates === 1 ? "was" : "were"} not sent twice.
            </p>
          )}
          <table>
            <thead>
              <tr>
                <th scope="col">Customer</th>
                <th scope="col">Channel</th>
                <th scope="col">Status</th>
                <th scope="col">Attempts</th>
                <th scope="col">Sent</th>
              </tr>
            </thead>
            <tbody>
              {deliveries.map((delivery) => (
                <tr key={`${delivery.customer_id}-${delivery.channel}`}>
                  <td>{delivery.customer_id.slice(0, 8)}…</td>
                  <td>{delivery.channel}</td>
                  <td>
                    {delivery.status}
                    {delivery.skip_reason && (
                      <span className="muted"> · {delivery.skip_reason.replaceAll("_", " ")}</span>
                    )}
                  </td>
                  <td>{delivery.attempt_count}</td>
                  <td>{formatDateTime(delivery.sent_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
