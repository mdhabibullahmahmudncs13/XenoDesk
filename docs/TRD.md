# Technical Requirements Document (TRD)

**Project:** XenoDesk — Customer Genome · Creator Commerce · Agent Workspace
**Version:** 1.0 (derived from Master Project Documentation v3.0, 16 November 2026)
**Audience:** Developers, architects, DevOps, QA, security reviewers

---

## 1. Purpose and Scope

This TRD specifies *how* the product is built: technology stack, service boundaries, API contract, data model summary, non-functional requirements, security and privacy controls, and the build/release plan.

**Companion documents**

| Document | Covers |
|---|---|
| `PRD.md` | Product scope, requirements, acceptance criteria |
| `TRD.md` *(this file)* | Technical design, API, NFRs, security, plan |
| `ERD.md` | Entity definitions, keys, constraints, relationships |
| `USER_FLOW.md` | User journeys, state machines, error paths |
| `ARCHITECTURE.md` | Layered architecture, components, deployment, integrations |

---

## 2. Technology Stack

> **Reference stack (non-binding)** — final choice is OD-11.

| Layer | Choice | Rationale |
|---|---|---|
| API service | Python, FastAPI (typed) | Typed request/response models, async I/O for webhooks and SSE, Pydantic validation at the boundary. |
| Database | PostgreSQL | Row-level tenant scoping, strong constraints for idempotency keys, JSONB for flexible snapshot payloads, mature advisory locking for restock detection. |
| Queue / cache | Redis + Celery (or Dramatiq) | Delayed jobs (review requests), batch sends, bounded retries, cache for hot read endpoints. |
| Realtime | Server-Sent Events (SSE) | One-way server→client push is all the bubble feature needs; simpler than WebSockets and survives proxies. |
| Front end | React with Next.js | App shell with a persistent sidebar, per-page routes for the SSE stream to survive navigation, server components for initial reads. |
| Background scheduler | APScheduler-style worker loop *or* queue-native delayed jobs | Restock detection polling and due-job dispatch. |
| Object storage | S3-compatible | CSV imports, uploaded screenshots (MI Tier 3), export artifacts. |
| LLM provider | Selected per OD-10 | Provider-agnostic client behind a `LLMPort` interface so the model can change without touching feature code. |
| Migrations | Alembic | Versioned, reversible schema migrations. |

**Alternatives considered**

| Option | Verdict |
|---|---|
| Node/Express API | Rejected — typed concurrency model and Pydantic validation fit the webhook-heavy, data-contract-driven domain better. |
| Firebase / DynamoDB | Rejected — the domain needs relational joins (customer ↔ order ↔ variant ↔ interest ↔ batch) and cross-table uniqueness for idempotency. |
| WebSockets for realtime | Rejected — one-way push only; SSE gives auto-reconnect and works through corporate proxies. |
| MongoDB | Rejected — qualifying-order rules and per-recipient delivery state are strongly relational. |

---

## 3. System Architecture Summary

One tenant-aware application with clear service boundaries. Features share five platform services instead of each building its own messaging, identity and scheduling.

### 3.1 Shared platform services

| Service | Responsibility | Owned tables |
|---|---|---|
| **Identity & Consent** | Messaging identity links, contact permissions, opt-outs and consent records. Used by bubbles, Restore Product and Review. | `messaging_identity_links`, `contact_permissions`, `review_permissions` |
| **Messaging Gateway** | Inbound: webhook signature check, idempotent event store. Outbound: channel adapters (Email, SMS, Messenger, WhatsApp), send-time eligibility, rate limits, bounded retries, one delivery log for all purposes. | `inbound_message_events`, `outbound_messages`, `delivery_attempts` |
| **Scheduler & Queue** | Delayed jobs (review requests), batch sends (retries), restock detection. | `scheduled_jobs`, `job_runs` |
| **Realtime** | Server-sent events per business for `bubble.created`, `bubble.updated`, `bubble.removed`. Clients reconnect and refetch. | — (fan-out from Redis pub/sub) |
| **Audit log** | Batch approvals, exports, consent changes, identity links, role changes. | `audit_log` |

Full component and deployment detail: `ARCHITECTURE.md`.

### 3.2 Cross-cutting technical rules

| Rule | Implementation |
|---|---|
| **Tenant isolation** | `business_id` is a required column on every tenant-scoped table, included in every index, and injected by the ORM session/middleware from the authenticated principal — never from request bodies. A repository-layer guard rejects queries without it. Cross-tenant tests are part of Definition of Done. |
| **Idempotency** | Unique constraints on inbound event IDs and outbound idempotency keys. Sends use an **outbox pattern**: the business transaction writes `outbound_messages` rows in `pending`, and a separate dispatcher claims and sends them. |
| **No fabricated data** | The API returns explicit `null` + a `reason` enum (`not_visible`, `not_available`, `not_tracked`, `unresolved`) rather than defaults. The UI renders a dedicated unavailable component. |
| **Least data to AI** | A redaction layer strips/masks personal fields before the prompt is assembled; the LLM port receives only an allow-listed payload. |
| **Time** | Store UTC (`timestamptz`). Display in the business time zone, resolved per `business.timezone`. Scheduled jobs compute due times in business time and persist the resolved UTC instant. |
| **Untrusted input** | Ad copy, review text and customer messages are stored and displayed as data, never interpolated into system prompts or tool schemas. |

---

## 4. Module Technical Design

### 4.1 M1 Customer Genome

#### 4.1.1 Data adapter (CG-04)

A pluggable adapter interface isolates the platform from the authoritative source:

```python
class CustomerOrderSource(Protocol):
    async def fetch_customers(self, cursor: str | None, updated_since: datetime) -> CustomerPage: ...
    async def fetch_orders(self, cursor: str | None, updated_since: datetime) -> OrderPage: ...
    async def fetch_inventory(self, cursor: str | None) -> InventoryPage: ...
```

- **Normalisation on ingest:** phone → E.164 (`+880…`), email → lowercase trimmed, whitespace collapsed.
- **Qualifying-order mapping:** the source `status` enum maps to `qualifying` / `non_qualifying` / `partial_refund` using the OD-02 rule set, versioned in `business_settings.qualifying_order_rules` so a rule change does not require a re-ingest.
- **Raw payload retention:** the source payload is stored in `order_source_payloads` (JSONB) for audit and re-derivation when the rule set changes.
- **Sync modes:** full backfill + incremental `updated_since` poll; webhook push where the source supports it. Sync runs as a queued job with per-run cursors.

#### 4.1.2 Identity resolution (CG-03)

Resolution order, highest confidence first:

| Priority | Method | Channel | Auto-link? |
|---|---|---|---|
| 1 | Verified `messaging_identity_links` row | All | Yes — primary lookup |
| 2 | Normalised phone (E.164) | WhatsApp, SMS | Yes |
| 3 | Normalised email | Email | Yes |
| 4 | Staff **Link customer** / customer shares phone in chat | Messenger | Yes, after explicit confirm |
| 5 | Display name | — | **Never** |

**Conflict handling (CG-10):** when two candidate customers match at the same priority, or when a channel identity resolves to different customers over time, the system:
1. creates no auto-merge,
2. records an `identity_conflicts` row,
3. returns a `no_confident_match` resolution to the caller — the bubble is created **without** the "Returning Customer" label and without any customer's figures,
4. surfaces a **Link customer** action to staff.

#### 4.1.3 Bubble pipeline (CG-05…CG-11)

```
provider webhook
  → POST /webhooks/messaging/{channel}
  → signature verification (constant-time)
  → fast ACK (< 500 ms), 202 Accepted
  → insert inbound_message_events (unique provider_event_id) — duplicate ⇒ no-op
  → enqueue identity_resolution job
      → resolve customer (order above)
      → qualifying-order count BEFORE message timestamp
      → if count ≥ 1: upsert customer_bubbles (unique: business + customer + conversation)
      → publish bubble.created / bubble.updated on Redis pub/sub
      → SSE fan-out to the business channel
```

- **Qualification timestamp (CG-06):** the comparison uses `inbound_message_events.received_at`, not processing time, so a delayed webhook cannot mis-qualify a customer.
- **Deduplication (CG-08):** unique constraint `UNIQUE(business_id, customer_id, conversation_id)` on `customer_bubbles`; repeated messages update `last_message_at` and `last_message_text`. A message from a **dismissed** customer re-opens the bubble (`dismissed_at = NULL`, state back to `new`).
- **Live figures (CG-09):** figures are recomputed from the authoritative history at read time (or refreshed by a cache invalidation on order sync) — never incrementally accumulated, so corrections in the source propagate.
- **In-app only (CG-11):** no browser push permission is requested; the SSE stream only needs an authenticated session.

**Bubble states**

| State | Entered when | Meaning |
|---|---|---|
| `new` | Bubble created or re-opened by a new message | Unread |
| `seen` | Staff opened the bubble | Read, not acted on |
| `dismissed` | Staff dismissed it | Hidden until a new inbound message arrives |

#### 4.1.4 Restore Product (RP-01…RP-10)

```
restock detection worker (poll inventory source)
  → product/variant transitions unavailable → available
  → insert restock_events (unique: business + product + variant + source transition)
  → create dashboard notification for the owner   [NO message sent]

owner opens Restore Product → selects restock event
  → GET /api/customer-genome/restocks/{eventId}/preview
      → resolves waiting list (product_interests for that product+variant)
      → for each interest: determine channel (Email default → SMS → Messenger/WhatsApp if eligible)
      → evaluate send-time eligibility per recipient
      → compute stock vs waiting demand → warning flag
      → returns per-recipient: customer, contact, channel, message, eligibility, skip_reason
  → owner edits template → re-previews
  → POST /api/customer-genome/restocks/{eventId}/notifications  (idempotency key required)
      → create restock_batches (state=queued, approved_by, approved_at, template_version)
      → insert outbound_messages rows (state=pending) for eligible recipients ONLY
      → skip ineligible recipients with a recorded reason (no send attempted)
      → audit_log entry
  → dispatcher claims pending rows, applies rate limits, sends, records delivery attempts
```

- **Idempotency (RP-08):** `outbound_messages.idempotency_key = sha256(business_id | restock_event_id | product_interest_id | channel)`, enforced by a unique index. A repeated confirm hits the constraint and is a no-op — one message per recipient per channel.
- **Eligibility re-check (RP-08):** re-evaluated at dispatch time (not preview time) against `contact_permissions`, opt-out state and channel provider rules. A recipient who opted out between preview and dispatch is skipped with `opted_out`.
- **Stock warning (RP-09):** if `stock_after < count(eligible waiting list)`, the preview returns a `stock_warning` with the numbers, and the template is rendered without reservation language. Enforced by template validation — a template containing reservation phrasing is rejected at save time.
- **No automatic sending:** the restock detection worker has no path to `outbound_messages`. It writes only `restock_events` and a dashboard notification. This is enforced in code by keeping outbound inserts behind the Gateway service interface, which requires a `restock_batch` in `queued` state.
- **Bounded retries (RP-10):** per-recipient max 3 attempts with exponential backoff; after exhaustion the row moves to `failed` with `error_code`. Other recipients are unaffected — each recipient is an independent row.

#### 4.1.5 Channel adapters

| Channel | Transport | Notes |
|---|---|---|
| Email | SMTP / transactional email API | Authenticated sending domain, mandatory unsubscribe link (List-Unsubscribe header), attachment-free |
| SMS | Regional SMS gateway | E.164 required, opt-out keyword honoured, per-submit rate limit |
| Messenger | Meta Graph API | Conditional on the free-reply window / message tag still being valid at send time |
| WhatsApp | WhatsApp Business API | Conditional on approved template + recorded opt-in |

Every adapter implements the same interface:

```python
class ChannelAdapter(Protocol):
    channel: Channel
    async def send(self, msg: OutboundMessage) -> SendReceipt: ...   # provider_message_id
    def eligibility(self, recipient: Recipient, at: datetime) -> EligibilityResult: ...
```

`eligibility()` returns `(eligible: bool, reason: str | None)` and is the single place channel rules live (OD-05).

---

### 4.2 M2 Creator Commerce

#### 4.2.1 Review pipeline (RV-01…RV-13)

```
delivery confirmed (from source adapter)
  → review_requests created (unique: business + order_id)  → due_at = confirmed_at + delay_days (business tz)
  → scheduled job dispatched for due_at
      → re-check eligibility at send time
          order cancelled/returned/refunded? → state=cancelled, reason recorded
          contact permission / opt-out?     → state=skipped, reason recorded
          channel ineligible?               → try next channel or skip with reason
      → send request with reference token
      → state=sent

customer replies (inbound message)
  → match by token, else by thread within reply window (default 14 days)
  → ambiguous match → state=needs_assignment  (no automatic attachment)
  → review_replies row: verbatim text, message_id, received_at, channel, customer, order, product
  → IMMUTABLE: insert-only, no UPDATE on the text columns

consent request sent (once per reply)
  → customer answers: yes | anonymous | no
  → review_permissions state: pending → approved | anonymous | declined | revoked
  → every change audited

marketing card
  → generated from review_replies.verbatim_text (exact string, no rewriting)
  → labelled "Customer review"
  → must not imitate Messenger/WhatsApp UI chrome (enforced by a template whitelist + visual regression test)
  → export allowed only when consent state ∈ {approved, anonymous}
```

- **One request per order (RV-05):** `UNIQUE(business_id, order_id)` on `review_requests`. A repeated delivery event is a no-op. Product tagging is `review_reply_products` (many-to-many).
- **Verbatim preservation (RV-08):** `review_replies.content` is written once with the provider `message_id` and never updated. Corrections are recorded as separate replies, not edits. Database-level protection: the column has a `BEFORE UPDATE` trigger that raises, or the write path uses a restricted role.
- **Consent gating (RV-09, RV-12):** the export query filters `review_permissions.state IN ('approved','anonymous')` at query time. Revocation immediately removes the row from export scope without deleting it. `anonymous` hides identity fields (name, contact, order ID) in both card and export.
- **Negative reviews (RV-08):** kept. There is no sentiment filter that hides negative replies — consent state governs use, not sentiment.
- **Unresolved data (RV-13):** if delivery, customer or product data is missing, the request row is `unresolved` with a reason; the system never synthesises a product name or a delivery date.

#### 4.2.2 Meta Ads Intelligence (MI-01…MI-05)

Three-tier source strategy selected in Phase 0 (OD-06):

| Tier | Provider interface | Availability |
|---|---|---|
| 1 | `MetaAdLibrarySource` — official API | Only if country + ad type are covered |
| 2 | `LicensedProviderSource` — third-party ad-data vendor | If Tier 1 unavailable and licence permits |
| 3 | `ManualIntakeSource` — pasted links / uploaded screenshots | Always available as fallback |

**Scoring (editable weights, MI-03)**

| Component | Weight | Evidence shown |
|---|---|---|
| Relevance to query | 40 | Matching terms, category match |
| Message clarity | 25 | Hook length/structure signals |
| Offer readability | 20 | Visible price/offer, overlay text |
| CTA strength | 15 | CTA presence and specificity |

Each score displays its evidence and the snapshot's freshness (`fetched_at`). The score is labelled "AI relevance and creative quality" and the UI never implies sales, revenue or ROAS (MI-03).

**Prompt-injection defence (MI-05, AW-06):** ad copy is placed inside a delimited, clearly-marked data block in the prompt; the system prompt states that the block is data to analyse and never instructions. The LLM port only receives structured fields and returns a validated JSON object (schema-constrained). The response cannot trigger a tool call — the insight path has no tools at all.

**Never scrape.** If Tier 1 and Tier 2 are unavailable, the feature runs in Tier 3 (manual intake) and the UI states that coverage is limited to submitted items.

#### 4.2.3 My Ads Performance (MP-01…MP-04)

- **OAuth connection (MP-01):** Facebook Login → Marketing API access token → `ads_read` scope only. Account selection list stored per business. Token encrypted at rest; refresh handled by the OAuth library; long-lived tokens never written to logs.
- **Metrics (MP-02):** computed from a stored snapshot in `ad_insight_snapshots` (raw metrics + `synced_at`). Missing fields return `{"value": null, "reason": "not_tracked"}` → UI shows "N/A, tracking not available".
- **Objective-aware ranking (MP-04):** deterministic SQL/Postgres computation over the snapshot — no LLM, no randomness. Objectives never mix in one ranking; a separate ranked list per objective.

| Objective | Sort | Guard (min) |
|---|---|---|
| Sales | ROAS desc → CPA asc → conversions desc | spend threshold |
| Traffic | CTR desc → CPC asc | impressions threshold |
| Leads | cost per lead asc → lead volume desc | lead count threshold |

- **Freshness (MP-03):** every response includes `synced_at`; the UI warns when the snapshot is older than the staleness threshold.

#### 4.2.4 Collaboration Finder (CF-01…CF-03) and Influencer Suggestions (IF-01…IF-02)

- Sourced from a legitimate, licensed data provider (CF-01). No scraping.
- Fields rendered only when present; missing fields show "Not available" (CF-02).
- **No outreach (CF-03):** the module has no outbound capability at all — no channel adapter is registered for it, and the outbound service rejects `purpose = collaboration`.
- IF-01 metrics are marked **Unverified** until confirmed by the owner. IF-02: the module is feature-flagged; disabling it removes the nav entry and nothing else.

---

### 4.3 M3 Agent Workspace

#### 4.3.1 Chat routing (AW-01…AW-09)

```
user message
  → normalise (lowercase, strip punctuation/extra spaces, Bangla Unicode NFC + common Banglish fold)
  → route 1: FAQ
      exact FAQ id match
      → alias list match
      → similarity score; below threshold ⇒ fall through
      → HIT: return fixed answer + references, answer_type='faq', tokens=0, cost=0
  → route 2: DATA
      intent classifier (deterministic, allow-listed question types)
      e.g. "how many active ads" → count_query(ads, active=true)
      → authorised read-only SQL via a pre-defined query registry
      → returns value + data_as_of
  → route 3: AI
      → LLM with a tool registry of READ-ONLY tools only
      → tool calls re-check tenant + role on every invocation (AW-07)
      → answer_type='ai'
  → route 4: BLOCKED
      write/delete intent detected ("delete this customer")
      → refusal, no tool executed
```

- **Zero tokens for FAQ (AW-04):** the FAQ route short-circuits before the LLM port is touched. `ai_usage_events` records a row with `route='faq'`, `input_tokens=0`, `output_tokens=0`, `estimated_cost=0`.
- **No write tools (AW-06):** the tool registry is a static allow-list of read-only functions; there is no dynamic tool registration path. A refusal template handles blocked intents.
- **Data minimisation (P6 / OD-10):** a redaction layer removes phone numbers, emails and full names from tool results before they reach the provider, unless the answer strictly requires them.
- **Usage monitoring (AW-08):** every request writes an `ai_usage_events` row: request ID, route, tokens, latency ms, estimated cost, tool names invoked, tenant, user.
- **Images (AW-09):** the upload control is disabled with an explanatory message; the API rejects image parts with a `415` and a clear message.
- **Floating launcher (AW-02):** a client-side launcher mounts on authenticated pages; opening it must not unmount the underlying route (kept outside the route tree, e.g. in the shell layout).

#### 4.3.2 FAQ matching rules (AW-03, AW-04)

| Rule | Detail |
|---|---|
| **Normalisation** | Lowercase; strip punctuation and extra spaces; normalise Bangla Unicode forms (NFC) and map common Banglish spellings (e.g. `review` ↔ `rb` variants per a maintained alias table). |
| **Matching order** | 1) exact FAQ ID → 2) alias list exact match → 3) similarity score against alias set |
| **Threshold** | Below the confidence threshold ⇒ fall through to DATA, then AI. Configurable, default 0.85 for alias exact, 0.80 for similarity. |
| **Ownership (AW-03 / OD-09)** | Each FAQ has `owner_user_id` and `review_due_at`. Editors are Owner and Admin. Stale FAQs (past `review_due_at`) are flagged in the admin list and to the owner. |
| **Response shape** | `{answer, answer_type: faq\|data\|ai, references[], data_as_of, usage{tokens, latency_ms, estimated_cost}}` |

#### 4.3.3 Website tour (AW-10, AW-11)

- Steps are static data in `tour_steps` with a stable `target_id` and a CSS selector.
- A driver walks the steps: Start / Skip / Previous / Next / Finish. First-visit offer is shown when no `tour_progress` row exists for the user.
- **Resilience (AW-11):** if the selector does not resolve, the step is skipped (auto-advance) or rendered as a centred message. The overlay never blocks input outside itself, and `Escape` always dismisses.
- Progress persisted per user (`tour_progress`), enabling Replay to restart from step 1.

---

## 5. API Surface

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/webhooks/messaging/{channel}` | Verified, idempotent inbound events (bubbles and review replies) |
| GET | `/api/realtime/stream` | Server-sent events for bubbles |
| GET | `/api/customer-genome/repeat-buyers` | Repeat Buyers list |
| GET | `/api/customers/{id}/history` | Customer history |
| POST | `/api/customers/{id}/link-identity` | Link customer action |
| GET, PATCH | `/api/customer-genome/returning-bubbles[/{id}]` | List, detail, seen and dismiss |
| GET, POST | `/api/customer-genome/product-interests` | Waiting-list entries |
| GET | `/api/customer-genome/restocks/{eventId}/preview` | Batch preview |
| POST | `/api/customer-genome/restocks/{eventId}/notifications` | Owner-confirmed batch (idempotency key required) |
| GET, PATCH | `/api/creator-commerce/reviews/settings` | Review configuration |
| GET | `/api/creator-commerce/reviews[/{id}]` | Review library and detail |
| POST | `/api/creator-commerce/reviews/{id}/card, /permission, /export` | Card, consent state, export |
| GET | `/api/creator-commerce/ads/insights` | Competitor and own-ad insights |
| GET, POST, PUT | `/api/workspace/faqs, /chat, /tour, /tour/progress` | FAQ list, chat, tour |

### 5.1 API conventions

| Convention | Rule |
|---|---|
| **Base path** | `/api` for product APIs; `/webhooks` for provider callbacks (no auth header — signature verification instead). |
| **Versioning** | Path prefix `/api/v1` (the table above omits it for readability). |
| **Auth** | OAuth2/OIDC bearer token for `/api`. Every request resolves to `business_id` + `role`. |
| **Tenant injection** | `business_id` comes from the token, never the request body or query string. A body-supplied `business_id` is rejected. |
| **Errors** | RFC 7807 problem+json: `{type, title, status, detail, code, request_id}`. Stable `code` values (`not_found`, `forbidden`, `eligibility_failed`, `idempotency_conflict`, `unavailable`). |
| **Pagination** | Cursor-based (`?cursor=&limit=`, max 100). Offset pagination is not used on large tables. |
| **Time** | All timestamps ISO-8601 UTC in responses; the client renders the business time zone. |
| **Idempotency** | Mutating sends accept `Idempotency-Key`; replays return the original result with `Idempotent-Replay: true`. |
| **Concurrency** | Optimistic locking via `version` column on mutable aggregates (settings, FAQ, review permission). |
| **Rate limiting** | Per tenant per endpoint; send endpoints additionally limited per channel. |
| **Request IDs** | `X-Request-Id` echoed; included in all logs. |
| **OpenAPI** | Generated from the typed models; served at `/api/docs`. |

### 5.2 Key endpoint contracts

**`POST /webhooks/messaging/{channel}`**

| Aspect | Behaviour |
|---|---|
| Auth | Provider signature (HMAC-SHA256 per provider), constant-time compare, timestamp tolerance window |
| Body | Provider-native payload |
| Response | `202 Accepted` with `{received: true, duplicate: bool}` — processing is asynchronous |
| Duplicate | `provider_event_id` unique constraint ⇒ duplicate inserts are swallowed; `duplicate: true` returned |
| Failure | `401` bad signature, `400` malformed payload, `5xx` transient (provider retries) |

**`GET /api/customer-genome/returning-bubbles`**

```json
{
  "items": [{
    "id": "bbl_...",
    "customer": {"id": "cus_...", "name": "Ayesha", "initials": "A"},
    "is_returning_customer": true,
    "conversation_id": "conv_...",
    "channel": "messenger",
    "last_message_at": "2026-11-16T09:12:00Z",
    "state": "new",
    "previous_order_count": 3,
    "total_purchase_amount": 24500.00,
    "currency": "BDT",
    "as_of": "2026-11-16T09:12:00Z",
    "last_purchase_date": "2026-11-02",
    "history_url": "/customers/cus_..."
  }],
  "data_as_of": "2026-11-16T09:12:05Z"
}
```

- `is_returning_customer: false` ⇒ no "Returning Customer" label, no figures, no other customer's data (CG-10).
- `link_customer_offered: true` is returned when identity resolution found no confident match.

**`POST /api/customer-genome/restocks/{eventId}/notifications`**

| Aspect | Behaviour |
|---|---|
| Auth | Owner only (approve a restock notification batch) |
| Required header | `Idempotency-Key` |
| Body | `{template_id, template_version, channel_overrides?: {customer_id: channel}}` |
| Behaviour | Creates `restock_batches` (queued) + `outbound_messages` rows for eligible recipients only; ineligible recipients recorded as `skipped` with a reason |
| Response | `{batch_id, queued: n, skipped: [{customer_id, reason}], stock_warning?: {...}}` |
| Replay | Same key ⇒ original batch returned, no additional messages |

**`POST /api/workspace/chat`**

```json
{
  "answer": "...",
  "answer_type": "faq",
  "references": [{"type": "screen", "label": "Review settings", "href": "/creator-commerce/reviews/settings"}],
  "data_as_of": null,
  "usage": {"input_tokens": 0, "output_tokens": 0, "latency_ms": 12, "estimated_cost": 0.0}
}
```

`answer_type` ∈ `faq` | `data` | `ai` | `blocked`.

---

## 6. Non-Functional Requirements

| Area | Target |
|---|---|
| **Performance** | Bubble visible within 5 s (p95) of webhook receipt. Read endpoints under 500 ms (p95). |
| **Reliability** | Webhooks acknowledged quickly and processed asynchronously with at-least-once handling. Availability target 99.5%. |
| **Security** | HTTPS only, webhook signature verification, secrets in a managed store, RBAC per endpoint, tenant isolation tests. |
| **Privacy** | Consent audit trail, defined retention and erasure handling (OD-07), personal data minimised for AI. |
| **Language** | FAQ and message templates in Bangla and English. UI language: OD-13. |
| **Accessibility** | Bubbles, chat and tour are keyboard operable with sufficient contrast. |
| **Observability** | Structured logs with request IDs, dashboards for delivery outcomes and AI cost. |

### 6.1 Measurable interpretations

| NFR | Interpretation |
|---|---|
| Bubble ≤ 5 s p95 | Measured from `inbound_message_events.received_at` to the SSE `bubble.created` frame reaching the client. |
| Reads < 500 ms p95 | Measured server-side for list/detail endpoints at typical tenant data volumes, excluding cold starts. |
| 99.5% availability | Measured monthly on the API and the realtime stream, excluding scheduled maintenance windows announced in advance. |
| At-least-once | Inbound processing may be executed more than once; idempotency constraints make it effectively-once. The contract is never at-most-once. |
| Tenant isolation | Automated test suite attempts cross-tenant reads on every tenant-scoped endpoint; all must return 403/404 with no data leakage. |

---

## 7. Security Design

| Concern | Control |
|---|---|
| **Transport** | HTTPS/TLS 1.2+ everywhere; HSTS; internal traffic over TLS as well. |
| **Webhook verification** | HMAC-SHA256 signature per provider, constant-time comparison, replay window check on the timestamp, and a per-provider secret stored in a managed secret store. |
| **Authentication** | OIDC/OAuth2 with short-lived access tokens; refresh tokens stored hashed server-side. |
| **Authorisation** | Role-based access control enforced per endpoint from the roles matrix in `PRD.md` §4. Owner-only: restock batch approval, ad account connection, review export, FAQ/tour management. |
| **Tenant isolation** | `business_id` injected from the token at the middleware layer; repository guard; row-level security recommended as defence in depth; mandatory cross-tenant test suite. |
| **Secrets** | Managed secret store (e.g. cloud secret manager). No secrets in code, images, logs or client bundles. |
| **Secrets in transit to third parties** | Meta access tokens encrypted at rest (KMS-envelope); rotated; never logged. |
| **Injection (SQL)** | Parameterised queries / ORM only; no string-built SQL from user input. |
| **Injection (LLM / prompt)** | Untrusted content isolated in delimited data blocks; JSON-schema-constrained responses; read-only tool allow-list; no tool can perform writes. |
| **XSS** | No raw HTML rendering of customer text or ad copy; React escaping by default; any rich text is sanitised server-side. |
| **PII exposure** | Redaction before LLM calls; export endpoints gated by consent; audit trail on all export and consent actions. |
| **Rate limiting** | Per tenant and per IP on inbound webhooks; per channel on outbound; per user on chat. |
| **Auditability** | Immutable audit log for batch approvals, exports, consent changes, identity links and role changes, with actor, timestamp, business, target and before/after hash. |
| **Dependency risk** | Locked dependency versions, automated dependency scanning, signed build artifacts. |

---

## 8. Reliability & Failure Handling

| Failure | Behaviour |
|---|---|
| Duplicate webhook | Unique `provider_event_id` ⇒ swallowed, `duplicate: true` returned, no side effects. |
| Out-of-order webhook | Qualification compares against `received_at`, so late-arriving events still qualify correctly. |
| Gateway timeout on ACK | Provider retries; idempotency absorbs the retry. |
| Channel provider down | Adapter throws ⇒ delivery attempt recorded `failed`, bounded retry with backoff, row ends `failed` with `error_code`. Other recipients unaffected. |
| Rate limit from provider | Retry after the provider-specified delay, within the bounded retry budget. |
| Queue backlog | Dispatcher scales horizontally; the dashboard shows last-synced/last-sent times so staleness is visible. |
| Database failover | Connection retry with jitter; requests fail fast rather than hanging (request timeout 30 s). |
| LLM provider down | Chat degrades to FAQ + DATA routes and shows an explicit "AI temporarily unavailable" notice. FAQ and data routes never depend on the LLM. |
| Inventory source stale | Restock detection records the source's `fetched_at`; stale data suppresses new restock events and shows a warning (prevents false restock alerts). |
| Partial batch failure | Per-recipient rows are independent; a batch is `completed` with a per-recipient outcome summary. |

---

## 9. Testing Strategy

| Level | Scope | Key cases |
|---|---|---|
| **Unit** | Normalisation, qualifying-order rules, idempotency key derivation, eligibility checks, scoring, FAQ matching | Bangla/Banglish normalisation variants; refund edge cases; threshold boundaries |
| **Integration** | Adapter → DB, webhook → bubble, restock → preview → batch → dispatch, delivery → review request → reply → consent → export | Duplicate webhooks, missing delivery data, consent revocation |
| **Contract** | Each channel adapter against provider sandbox/recorded fixtures | Window expiry, opt-out keyword, template rejection |
| **E2E** | Browser journeys from `USER_FLOW.md` | All acceptance tests CG-T*, RP-T*, RV-T*, MI-T*, MP-T*, CF-T*, IF-T*, AW-T* |
| **Security** | Cross-tenant matrix, IDOR on every `{id}` route, signature bypass attempts, role escalation, prompt-injection corpus | Cross-tenant reads must 403/404 with no leakage |
| **Load** | Webhook burst, concurrent restock batches, chat concurrency | Bubble p95 ≤ 5 s under expected peak |
| **Resilience** | Kill worker mid-batch, provider outage, LLM outage, DB failover | No duplicate sends; no lost events; no fabricated data |
| **Visual regression** | Marketing cards | Card must not imitate Messenger/WhatsApp UI (RV-10) |

**Definition of Done (binding)**

1. All acceptance tests for the feature pass.
2. Cross-tenant access test and duplicate-event test pass.
3. Empty, error and unavailable-data states are designed and tested.
4. Requirements, API and data-model sections updated in the master document.

---

## 10. Build & Release Plan

| Phase | Technical scope | Exit criteria |
|---|---|---|
| **0 Feasibility** | Meta ad data access spike for Bangladesh commercial ads (OD-06); Messenger/WhatsApp identity + window validation (OD-05); SMS gateway & email provider selection; Meta app review / business verification lead time; customer, order and inventory source decision (OD-01); stack decision (OD-11) | Go/no-go recorded per integration. OD-01, 05, 06 closed. |
| **1 Foundation** | Auth, tenant model, roles, sidebar shell; Identity & Consent, Messaging Gateway, Scheduler & Queue, Realtime, Audit log; API conventions, logging, CI | Tenant isolation and idempotency tests pass on the shared services. |
| **2 Customer Genome** | Data adapter, history, Repeat Buyers; identity linking, bubbles; Restore Product | CG-T01…T08, RP-T01…T08 pass. |
| **3 Creator Commerce** | Review first; Meta Ads Intelligence on the chosen tier; My Ads Performance, Collaboration Finder, optional Influencer view | RV, MI, MP, CF tests pass. |
| **4 Agent Workspace** | FAQ registry + matching; chat routing, AI agent with read-only tools, usage metrics; website tour | AW-T01…T10 pass. Can start after Phase 1. |
| **5 Hardening** | Security review, data correctness, failure and load tests; responsive UI, owner acceptance, staged rollout | Definition of Done met for all modules. |

### 10.1 Environment strategy

| Environment | Purpose | Data |
|---|---|---|
| `local` | Development with docker-compose (Postgres, Redis, mailhog) | Seeded fixtures |
| `ci` | Automated test runs | Ephemeral per pipeline |
| `staging` | Pre-release verification, owner acceptance | Sanitised production-like data |
| `production` | Live | Real tenant data, encrypted, audited |

Secrets are injected per environment from the secret store; no `.env` files are committed.

### 10.2 CI/CD pipeline

```
lint (ruff/mypy/eslint/tsc)
  → unit tests
  → integration tests (docker-compose services)
  → migrations applied to a clean DB (up + down check)
  → contract tests
  → security tests (tenant isolation, IDOR, signature)
  → build images (pinned base, digest-pinned, scanned)
  → deploy to staging → smoke tests → owner acceptance → production
```

**Release strategy:** behind feature flags per tenant, staged rollout (internal → 5% → 25% → 100%), automatic rollback on error-rate breach. Migration policy: expand/contract — add nullable columns, backfill, switch reads, drop later — so deploy and schema change never conflict.

---

## 11. Observability

| Signal | Content |
|---|---|
| **Structured logs** | JSON with `request_id`, `business_id`, `user_id`, `route`, `latency_ms`, `outcome`. Secrets and customer PII are never logged. |
| **Traces** | Distributed tracing across API → queue worker → channel adapter → provider, with the correlation id propagated through the job payload. |
| **Metrics** | Webhook receipt rate, bubble latency (p95), qualification rate, outbound per channel, delivery success/failure by error code, retry counts, restock detection lag, review request due/sent rates, reply match rate, consent distribution, chat route mix (faq/data/ai), AI tokens and cost per tenant, SSE connections. |
| **Alerts** | Delivery failure rate > threshold; queue age > threshold; bubble p95 > 5 s; error rate > 2%; LLM cost anomaly; webhook signature failure spike. |
| **Dashboards** | Delivery outcomes per channel; AI cost per tenant per day; funnel: inbound → qualified → bubble → linked; review funnel: due → sent → replied → consented → exported. |
| **Audit** | Immutable audit log surfaced in the UI for Owner/Admin: batch approvals, exports, consent changes, identity links, role changes. |

---

## 12. Open Technical Decisions

| ID | Decision | Impact on this document | Owner | Needed by |
|---|---|---|---|---|
| OD-01 | Source & integration method | Adapter interface (§4.1.1), schema of ingested records | Product + Eng | Phase 0 |
| OD-02 | Qualifying-order rules | `qualifying` mapping and Repeat-vs-Returning thresholds | Product | Phase 1 |
| OD-03 | Multi-tenant SaaS vs single business | `business_id` propagation, RLS strategy, isolation tests | Product | Phase 1 |
| OD-05 | Channel eligibility per provider | `ChannelAdapter.eligibility()` implementation (§4.1.5) | Eng | Phase 0 |
| OD-06 | Meta ad data tier | Which `*Source` implementation ships (§4.2.2) | Eng | Phase 0 |
| OD-07 | Retention & erasure | Purge jobs, export scope, `ai_usage_events` retention | Product + Legal | Phase 1 |
| OD-08 | Review defaults | `review_settings` defaults and reply-window length | Product | Phase 3 |
| OD-09 | FAQ ownership workflow | FAQ editor permissions and staleness flagging | Product | Phase 4 |
| OD-10 | AI provider, model, cost caps, redaction | `LLMPort`, cost ceiling enforcement, redaction rules | Product + Eng | Phase 4 |
| OD-11 | Stack and hosting | §2 and deployment topology | Eng | Phase 0 |
| OD-12 | Stock warning thresholds | `stock_warning` computation | Product | Phase 2 |
| OD-13 | UI language | i18n strategy, FAQ/template locale fields | Product | Phase 1 |

---

## 13. Traceability

| PRD section | This TRD |
|---|---|
| §6 Customer Genome | §4.1 |
| §7 Bubbles | §4.1.2, §4.1.3 |
| §8 Restore Product | §4.1.4, §4.1.5 |
| §9 Review | §4.2.1 |
| §10 Meta Ads Intelligence | §4.2.2 |
| §11 My Ads Performance | §4.2.3 |
| §12–13 Collaboration & Influencer | §4.2.4 |
| §14 Chat | §4.3.1, §4.3.2 |
| §15 Tour | §4.3.3 |
| §4 Roles & permissions | §5.1, §7 |
| §16 Delivery plan | §10 |
| §18 Decision register | §12 |
