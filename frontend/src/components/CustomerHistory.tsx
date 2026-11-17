"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Screen } from "./Screen";

function HistoryView() {
  const customerId = useSearchParams().get("customer_id");
  if (!customerId) {
    return <Screen title="Customer history" description="Select a customer to view history." blocked />;
  }
  return (
    <Screen
      title="Customer history"
      description="Authoritative purchase history for this customer."
      endpoint={`/api/v1/customers/${encodeURIComponent(customerId)}/history`}
    />
  );
}

export function CustomerHistory() {
  return <Suspense fallback={<div className="state-card shell-loading" role="status">Loading history…</div>}><HistoryView /></Suspense>;
}
