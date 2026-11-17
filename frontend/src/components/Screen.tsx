"use client";

import { useEffect, useState } from "react";
import { ApiState, fetchApi } from "../lib/api";

type Props = {
  title: string;
  description: string;
  endpoint?: string;
  blocked?: boolean;
  list?: boolean;
};

function displayValue(value: unknown): React.ReactNode {
  if (value === null || value === undefined || value === "") {
    return <span className="unavailable-chip">Unavailable</span>;
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function records(data: unknown): Record<string, unknown>[] {
  if (Array.isArray(data)) return data.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"));
  if (data && typeof data === "object" && Array.isArray((data as { items?: unknown }).items)) {
    return (data as { items: unknown[] }).items.filter(
      (item): item is Record<string, unknown> => Boolean(item && typeof item === "object"),
    );
  }
  return [];
}

export function Screen({ title, description, endpoint, blocked, list }: Props) {
  const [state, setState] = useState<ApiState<unknown>>({ status: endpoint ? "loading" : "ready", data: null });

  useEffect(() => {
    if (!endpoint) return;
    let active = true;
    fetchApi<unknown>(endpoint)
      .then((data) => active && setState({ status: "ready", data }))
      .catch((error: Error) => active && setState({ status: "error", message: error.message }));
    return () => {
      active = false;
    };
  }, [endpoint]);

  return (
    <section className="screen" aria-labelledby="screen-title">
      <div className="screen-heading">
        <div>
          <p className="eyebrow">XENOVARIENTS</p>
          <h1 id="screen-title">{title}</h1>
          <p className="muted">{description}</p>
        </div>
        <span className="unavailable-chip">Live API</span>
      </div>
      {blocked ? (
        <div className="state-card unresolved" role="status">
          <strong>Blocked</strong>
          <p>This screen is waiting for its backend capability and is not using mock data.</p>
        </div>
      ) : state.status === "loading" ? (
        <div className="state-card skeleton" aria-label="Loading">
          <div />
          <div />
          <div />
        </div>
      ) : state.status === "error" ? (
        <div className="state-card error" role="alert">
          <strong>Unable to load this screen</strong>
          <p>{state.message}. Check authentication and the API connection.</p>
        </div>
      ) : list && records(state.data).length === 0 ? (
        <div className="state-card empty" role="status">
          <strong>No records yet</strong>
          <p>When the API has data, it will appear here.</p>
        </div>
      ) : state.data && typeof state.data === "object" && "stale" in state.data && state.data.stale === true ? (
        <div className="state-card stale" role="status">
          <strong>Data needs review</strong>
          <p>This record is stale. Confirm it before relying on it.</p>
        </div>
      ) : (
        <DataView data={state.data} />
      )}
    </section>
  );
}

function DataView({ data }: { data: unknown }) {
  const rows = records(data);
  if (rows.length === 0) {
    return (
      <div className="data-card">
        <div className="card-header"><strong>Live data</strong><span className="chip">Updated now</span></div>
        <dl className="detail-list">
          {data && typeof data === "object"
            ? Object.entries(data as Record<string, unknown>).map(([key, value]) => (
                <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{displayValue(value)}</dd></div>
              ))
            : <dd>{displayValue(data)}</dd>}
        </dl>
      </div>
    );
  }
  const columns = Object.keys(rows[0]).filter((key) => key !== "items" && key !== "aliases");
  return (
    <div className="data-card table-wrap">
      <div className="card-header"><strong>Live data</strong><span className="chip">{rows.length} records</span></div>
      <table>
        <thead><tr>{columns.map((column) => <th key={column} scope="col">{column.replaceAll("_", " ")}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={String(row.id ?? row.reply_id ?? index)}>{columns.map((column) => <td key={column}>{displayValue(row[column])}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}
