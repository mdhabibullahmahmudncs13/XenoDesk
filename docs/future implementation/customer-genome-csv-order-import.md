# Customer Genome CSV order import

**Status:** Planned. [OD-01](../decisions/OD-01.md) already discusses CSV/SFTP as a source adapter. This guide describes the merchant-facing upload, preview, and confirmation workflow for historical orders.

## Upload and preview

Add **Import Orders** to [Genome Overview](../../frontend/src/components/GenomeOverview.tsx) and use the existing [API client](../../frontend/src/lib/api.ts). Provide a UTF-8 CSV template with one row per order. Require source order ID, source customer ID, order timestamp with timezone, status, total amount, and currency. Support optional customer email and phone if supplied. Preview qualifying-order status using the same rules as sync.

Add authenticated preview and confirm routes under the [Genome API](../../backend/xenovarients/api/genome.py), using existing principal, role, and tenant checks. Parse with Python's `csv` module and enforce file-size and row limits. Validate dates, supported statuses, currencies, amounts, duplicate IDs within the file, and customer references. Return counts and row-numbered errors. Keep the preview free of writes to customer or order records. Use a short-lived staging record scoped to the business and uploader. Expire it and avoid logging raw CSV values.

## Confirm and import

- Map rows to [`SourceCustomer` and `SourceOrder`](../../backend/xenovarients/platform/source.py). Match stable source customer IDs within the tenant and reuse existing normalization. Surface ambiguous identity matches and skip unresolved rows unless the upload contains a valid customer record.
- Reuse the order upsert, qualifying rules, and rollup logic in [`platform/sync.py`](../../backend/xenovarients/platform/sync.py). Extract the shared ingestion step if needed. The current scheduled `sync_orders` flow also schedules review requests. Historical imports should ingest and recompute figures without enqueuing review requests or outbound messages.
- Verify the existing source-ID uniqueness constraints before mixing exports from multiple systems. Use stable source-aware keys or add a source namespace consistently across customer and order lookups. Skip identical existing rows and report conflicting rows for review. Recheck duplicates and conflicts inside the confirm transaction. Make repeated confirmation return the saved result without importing twice.
- Return imported, skipped, and conflicted counts. Record confirmation in the existing audit flow with actor, business and counts. Expire the staged file and show the refreshed customer history and repeat-buyer figures.

## Acceptance checks

- An authorized merchant can upload, preview, and confirm historical orders through Customer Genome.
- Invalid rows and conflicting identities receive actionable errors. Currency and timezone handling match the CSV contract.
- Re-uploading the same file or retrying confirmation preserves order and rollup counts. A failed confirmation leaves no partial import.
- A second business cannot preview or confirm the first business's upload. Historical imports enqueue no customer messages or review requests.

Select **User Uploads / Bulk Import** on the submission form once the workflow passes these checks.
