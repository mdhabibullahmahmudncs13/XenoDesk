# Entity Relationship Diagram (ERD)

**Project:** Xenovarients — Customer Genome · Creator Commerce · Agent Workspace
**Version:** 1.0 (derived from Master Project Documentation v3.0, 16 November 2026)
**Target:** PostgreSQL (see `TRD.md` §2)

---

## 1. Conventions

| Convention | Rule |
|---|---|
| **PK** | Primary key — `id` (UUIDv7 / ULID, time-sortable). |
| **FK** | Foreign key. |
| **U** | Unique constraint. |
| **NN** | NOT NULL. |
| **Nullable** | `*` suffix in the field list. |
| **Timestamps** | `timestamptz`, stored UTC. Displayed in the business time zone. |
| **Tenant scope** | Every tenant-scoped entity carries `business_id`. It is always part of the primary lookup index. |
| **Money** | `numeric(12,2)` plus `currency` (ISO-4217). Never a float. |
| **Immutable rows** | Marked ⟂ — insert-only, updates blocked at the database level. |
| **Soft state** | Status columns use constrained enums, not free text. |
| **Audit columns** | Every mutable table carries `created_at`, `updated_at`; actor columns where relevant. |

---

## 2. Entity Index

| # | Entity | Purpose | Module |
|---|---|---|---|
| 2.1 | `businesses` | Tenant root | Shared |
| 2.2 | `users` | Staff/owner accounts | Shared |
| 2.3 | `business_memberships` | User↔business↔role | Shared |
| 2.4 | `customers` | Customer mirror from the source | M1 |
| 2.5 | `customer_orders` | Order mirror from the source | M1 |
| 2.6 | `order_items` | Lines of an order | M1 |
| 2.7 | `products` / `product_variants` | Catalogue mirror | M1 / M2 |
| 2.8 | `messaging_identity_links` | Channel identity ↔ customer | M1 |
| 2.9 | `identity_conflicts` | Unresolved match queue | M1 |
| 2.10 | `inbound_message_events` | Inbound webhook store | M1 / M2 |
| 2.11 | `customer_bubbles` | Bubble state | M1 |
| 2.12 | `contact_permissions` | Per-channel permission & opt-out | M1 |
| 2.13 | `product_interests` | Waiting-list entries | M1 |
| 2.14 | `restock_events` | Out-of-stock → available | M1 |
| 2.15 | `restock_batches` | Owner-confirmed batch | M1 |
| 2.16 | `outbound_messages` | Unified delivery log | M1 / M2 |
| 2.17 | `delivery_attempts` | Per-attempt send record | M1 / M2 |
| 2.18 | `review_settings` | Review configuration | M2 |
| 2.19 | `review_requests` | One per order | M2 |
| 2.20 | `review_replies` | Verbatim customer reply ⟂ | M2 |
| 2.21 | `review_reply_products` | Reply ↔ product tagging | M2 |
| 2.22 | `review_permissions` | Consent state | M2 |
| 2.23 | `review_cards` | Generated marketing card | M2 |
| 2.24 | `ad_insight_snapshots` | Competitor & own ad metrics | M2 |
| 2.25 | `ad_account_connections` | Meta OAuth link | M2 |
| 2.26 | `collaboration_suggestions` | Collaborator/influencer list | M2 |
| 2.27 | `faq_entries` | FAQ registry | M3 |
| 2.28 | `faq_aliases` | Alias matching | M3 |
| 2.29 | `chat_sessions` / `chat_messages` | Conversation store | M3 |
| 2.30 | `ai_usage_events` | Per-request usage & cost | M3 |
| 2.31 | `tour_steps` / `tour_progress` | Tour definition & state | M3 |
| 2.32 | `audit_log` | Immutable activity log | Shared |
| 2.33 | `scheduled_jobs` | Delayed job store | Shared |
| 2.34 | `notifications` | In-app dashboard notifications | Shared |

---

## 3. Entity Definitions

### 2.1 `businesses`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `name` | text | NN | Used in message templates |
| `timezone` | text | NN, default `Asia/Dhaka` | Business time zone (OD-13) |
| `currency` | char(3) | NN | ISO-4217 |
| `settings` | jsonb | default `{}` | Qualifying-order rule version, ad tier, locale |
| `created_at` / `updated_at` | timestamptz | NN | |

### 2.2 `users`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `email` | text | **U**, NN | Lowercase |
| `name` | text | NN | |
| `password_hash` | text | NN | Argon2id |
| `is_active` | boolean | NN, default true | |
| `last_login_at` | timestamptz | * | |
| `created_at` / `updated_at` | timestamptz | NN | |

### 2.3 `business_memberships`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK → `businesses.id`, NN | |
| `user_id` | uuid | FK → `users.id`, NN | |
| `role` | enum | NN | `owner` \| `admin` \| `staff` |
| `created_at` | timestamptz | NN | |
| — | | **U** (`business_id`,`user_id`) | One role per user per business |

### 2.4 `customers`

Mirror of the authoritative customer source.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | Internal ID |
| `business_id` | uuid | FK → `businesses.id`, NN | |
| `source_customer_id` | text | NN | Stable identifier from the source |
| `name` | text | * | |
| `phone_e164` | text | * | Normalised on ingest (+880…) |
| `email_normalised` | text | * | Lowercase, trimmed |
| `first_seen_at` / `last_seen_at` | timestamptz | * | |
| `total_orders` | integer | NN, default 0 | Derived, refreshed from history |
| `total_spend` | numeric(12,2) | NN, default 0 | Derived, net of refunds |
| `last_purchase_at` | timestamptz | * | Derived |
| `is_repeat_buyer` | boolean | NN, default false | Derived: ≥ 2 qualifying orders (CG-01) |
| `source_updated_at` | timestamptz | * | For incremental sync |
| `created_at` / `updated_at` | timestamptz | NN | |
| — | | **U** (`business_id`,`source_customer_id`) | |
| — | | index (`business_id`,`phone_e164`), (`business_id`,`email_normalised`) | Identity lookup (CG-03) |

### 2.5 `customer_orders`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `customer_id` | uuid | FK → `customers.id`, NN | |
| `source_order_id` | text | NN | |
| `ordered_at` | timestamptz | NN | Business time zone preserved on ingest |
| `status` | enum | NN | Source status mapped to internal enum |
| `qualifying` | boolean | NN | Derived from OD-02 rule set; rule version stored |
| `qualifying_rule_version` | text | NN | So a rule change can be re-applied without re-ingest |
| `total_amount` | numeric(12,2) | NN | Net of refunds where applicable |
| `currency` | char(3) | NN | |
| `refund_amount` | numeric(12,2) | NN, default 0 | Partial refunds counted net |
| `is_cancelled` / `is_returned` / `is_refunded` | boolean | NN, default false | Used by RV-04 send-time re-check |
| `delivered_at` | timestamptz | * | Verified delivery confirmation (RV-02) |
| `source_payload` | jsonb | * | Raw payload for audit / re-derivation |
| `source_updated_at` | timestamptz | * | Incremental sync cursor |
| `created_at` / `updated_at` | timestamptz | NN | |
| — | | **U** (`business_id`,`source_order_id`) | |
| — | | index (`business_id`,`customer_id`,`ordered_at` DESC) | CG-02 history timeline |

### 2.6 `order_items`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `order_id` | uuid | FK → `customer_orders.id`, NN | ON DELETE CASCADE |
| `product_id` | uuid | FK → `products.id`, NN | |
| `variant_id` | uuid | FK → `product_variants.id`, * | |
| `product_name_snapshot` | text | NN | Name as shown on the order |
| `quantity` | integer | NN | > 0 |
| `line_total` | numeric(12,2) | NN | |
| `created_at` | timestamptz | NN | |
| — | | index (`business_id`,`order_id`) | |
| — | | index (`business_id`,`product_id`) | CG-02 product filter |

### 2.7 `products` and `product_variants`

**`products`**

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `source_product_id` | text | * | From inventory/order source |
| `name` | text | NN | |
| `category` | text | * | Used by MI-01 and CF-01 |
| `created_at` / `updated_at` | timestamptz | NN | |

**`product_variants`**

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `product_id` | uuid | FK → `products.id`, NN | |
| `source_variant_id` | text | * | |
| `name` | text | NN | |
| `is_available` | boolean | NN, default false | Restock detection input (RP-04) |
| `stock_on_hand` | integer | NN, default 0 | For RP-09 stock warning |
| `last_inventory_sync_at` | timestamptz | * | Staleness guard (OD-12) |
| `created_at` / `updated_at` | timestamptz | NN | |
| — | | **U** (`business_id`,`source_variant_id`) | |
| — | | index (`business_id`,`product_id`) | RP-03 grouping by product and variant |

### 2.8 `messaging_identity_links`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `channel` | enum | NN | `messenger` \| `whatsapp` \| `sms` \| `email` |
| `channel_user_id` | text | NN | Platform-scoped identity |
| `customer_id` | uuid | FK → `customers.id`, NN | |
| `method` | enum | NN | `verified_link` \| `phone` \| `email` \| `staff_link` \| `customer_shared_phone` |
| `verified_at` | timestamptz | * | Set for `verified_link` / confirmed links |
| `verified_by_user_id` | uuid | FK → `users.id`, * | Staff-created links |
| `created_at` / `updated_at` | timestamptz | NN | |
| — | | **U** (`business_id`,`channel`,`channel_user_id`) | One identity ↔ one customer |
| — | | index (`business_id`,`customer_id`) | Reverse lookup |

### 2.9 `identity_conflicts`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `channel` | enum | NN | |
| `channel_user_id` | text | NN | |
| `candidate_customer_ids` | uuid[] | NN | Two or more conflicting candidates |
| `reason` | enum | NN | `multiple_match` \| `changed_customer` \| `manual_flag` |
| `state` | enum | NN | `open` \| `resolved` |
| `resolved_customer_id` | uuid | FK → `customers.id`, * | Staff resolution |
| `resolved_by_user_id` | uuid | FK → `users.id`, * | |
| `created_at` / `updated_at` | timestamptz | NN | |

### 2.10 `inbound_message_events` ⟂

Insert-only. Duplicate prevention is the point of this table.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `provider_event_id` | text | NN | **U** together with `business_id` — idempotency |
| `channel` | enum | NN | |
| `conversation_id` | text | * | |
| `channel_user_id` | text | * | Resolves to `messaging_identity_links` |
| `direction` | enum | NN | `inbound` (outbound lives in `outbound_messages`) |
| `message_id` | text | * | Provider message ID |
| `content` | text | * | Verbatim, untrusted input |
| `received_at` | timestamptz | NN | Provider timestamp — drives qualification (CG-06) |
| `processed_at` | timestamptz | * | |
| `resolved_customer_id` | uuid | FK → `customers.id`, * | Null ⇒ no confident match (CG-10) |
| `review_request_id` | uuid | FK → `review_requests.id`, * | Set when the reply attached to a request |
| `created_at` | timestamptz | NN | |
| — | | **U** (`business_id`,`provider_event_id`) | |
| — | | index (`business_id`,`channel_user_id`,`received_at` DESC) | Identity lookup |
| — | | index (`business_id`,`conversation_id`) | Thread matching for replies (RV-07) |

### 2.11 `customer_bubbles`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `customer_id` | uuid | FK → `customers.id`, NN | |
| `conversation_id` | text | NN | |
| `channel` | enum | NN | |
| `is_returning_customer` | boolean | NN | False ⇒ no label, no figures (CG-10) |
| `order_count` | integer | NN, default 0 | Live figures (CG-09) |
| `total_spend` | numeric(12,2) | NN, default 0 | Live figures |
| `currency` | char(3) | NN | |
| `last_purchase_at` | timestamptz | * | |
| `data_as_of` | timestamptz | NN | "as of" time shown on the card |
| `last_message_at` | timestamptz | NN | |
| `last_message_preview` | text | * | |
| `state` | enum | NN | `new` \| `seen` \| `dismissed` |
| `seen_at` | timestamptz | * | |
| `dismissed_at` | timestamptz | * | |
| `created_at` / `updated_at` | timestamptz | NN | |
| — | | **U** (`business_id`,`customer_id`,`conversation_id`) | One bubble per customer and conversation (CG-08) |
| — | | index (`business_id`,`state`,`last_message_at` DESC) | Bubble list ordering |

### 2.12 `contact_permissions`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `customer_id` | uuid | FK → `customers.id`, NN | |
| `channel` | enum | NN | |
| `contact_value` | text | NN | E.164 phone or email |
| `eligible` | boolean | NN | Master send eligibility |
| `source` | enum | NN | `opt_in` \| `purchase` \| `opt_out` \| `manual` \| `import` |
| `opted_out_at` | timestamptz | * | Honoured immediately (RP-08) |
| `updated_at` | timestamptz | NN | |
| `created_at` | timestamptz | NN | |
| — | | **U** (`business_id`,`customer_id`,`channel`) | |

### 2.13 `product_interests`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `customer_id` | uuid | FK → `customers.id`, NN | |
| `product_id` | uuid | FK → `products.id`, NN | |
| `variant_id` | uuid | FK → `product_variants.id`, NN | Variants never mixed (RP-03) |
| `requested_at` | timestamptz | NN | Request date (RP-02) |
| `quantity` | integer | * | Optional |
| `contact_channel` | enum | NN | Preferred channel |
| `contact_value` | text | NN | |
| `source` | enum | NN | `profile` \| `bubble` \| `product_page` \| `csv_import` |
| `created_by_user_id` | uuid | FK → `users.id`, * | |
| `created_at` / `updated_at` | timestamptz | NN | |
| — | | index (`business_id`,`variant_id`,`requested_at`) | Waiting-list grouping |
| — | | index (`business_id`,`customer_id`) | Duplicate interest check |

### 2.14 `restock_events`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `product_id` | uuid | FK → `products.id`, NN | |
| `variant_id` | uuid | FK → `product_variants.id`, NN | |
| `detected_at` | timestamptz | NN | |
| `stock_after` | integer | NN | For the RP-09 warning |
| `source` | enum | NN | `poll` \| `webhook` |
| `source_ref` | text | * | Source transition reference |
| `notified_owner_at` | timestamptz | * | Owner notification sent |
| `created_at` | timestamptz | NN | |
| — | | **U** (`business_id`,`variant_id`,`source_ref`) | One event per transition (RP-04) |
| — | | index (`business_id`,`detected_at` DESC) | |

### 2.15 `restock_batches`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `restock_event_id` | uuid | FK → `restock_events.id`, NN | |
| `approved_by_user_id` | uuid | FK → `users.id`, NN | Owner (RP-07) |
| `approved_at` | timestamptz | NN | |
| `template_id` | uuid | FK → `message_templates.id`, NN | |
| `template_version` | text | NN | Snapshot of the rendered template |
| `state` | enum | NN | `queued` \| `sending` \| `completed` \| `cancelled` |
| `idempotency_key` | text | NN | **U** (`business_id`,`idempotency_key`) |
| `recipient_count` | integer | NN, default 0 | |
| `skipped_count` | integer | NN, default 0 | |
| `created_at` / `updated_at` | timestamptz | NN | |
| — | | index (`business_id`,`restock_event_id`) | |

### 2.16 `outbound_messages`

The single delivery log for every purpose (Restore Product and Review).

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `purpose` | enum | NN | `restock` \| `review_request` \| `review_consent` |
| `ref_id` | uuid | NN | `restock_batch_id` or `review_request_id` (polymorphic, enforced in app layer) |
| `customer_id` | uuid | FK → `customers.id`, NN | |
| `channel` | enum | NN | |
| `to_address` | text | NN | |
| `body` | text | NN | Rendered message |
| `idempotency_key` | text | NN | **U** globally — sha256(business\|ref\|recipient\|channel) |
| `status` | enum | NN | `pending` \| `sent` \| `delivered` \| `failed` \| `skipped` |
| `skip_reason` | text | * | e.g. `opted_out`, `channel_ineligible`, `no_permission` |
| `provider_message_id` | text | * | |
| `error_code` | text | * | |
| `attempt_count` | integer | NN, default 0 | Bounded retries (RP-10) |
| `next_attempt_at` | timestamptz | * | Backoff schedule |
| `sent_at` | timestamptz | * | |
| `delivered_at` | timestamptz | * | Only if observable |
| `created_at` / `updated_at` | timestamptz | NN | |
| — | | index (`business_id`,`purpose`,`status`) | Delivery reporting |
| — | | index (`status`,`next_attempt_at`) WHERE `status='pending'` | Dispatcher claim query |

### 2.17 `delivery_attempts`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `outbound_message_id` | uuid | FK → `outbound_messages.id`, NN | ON DELETE CASCADE |
| `attempt_number` | integer | NN | |
| `started_at` | timestamptz | NN | |
| `finished_at` | timestamptz | * | |
| `outcome` | enum | NN | `success` \| `failure` \| `retryable_failure` |
| `provider_response` | jsonb | * | Sanitised |
| `error_code` | text | * | |
| — | | **U** (`outbound_message_id`,`attempt_number`) | |

### 2.18 `review_settings`

One row per business.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | **U** |
| `delay_days` | integer | NN, default 3 | 3 or 4 (RV-03) |
| `send_window_start` | time | NN, default 09:00 | Business time zone |
| `send_window_end` | time | NN, default 20:00 | |
| `reply_window_days` | integer | NN, default 14 | RV-07 |
| `channel_order` | enum[] | NN | e.g. `['email','sms']` — Messenger/WhatsApp appended only when eligible |
| `template_id` | uuid | FK → `message_templates.id`, * | |
| `updated_at` | timestamptz | NN | |

### 2.19 `review_requests`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `order_id` | uuid | FK → `customer_orders.id`, NN | |
| `customer_id` | uuid | FK → `customers.id`, NN | |
| `delivery_confirmed_at` | timestamptz | NN | RV-02 trigger |
| `due_at` | timestamptz | NN | = confirmed_at + delay_days, resolved in business tz |
| `sent_at` | timestamptz | * | |
| `state` | enum | NN | `scheduled` \| `sent` \| `replied` \| `cancelled` \| `skipped` \| `needs_assignment` \| `unresolved` |
| `state_reason` | text | * | e.g. `order_refunded`, `opted_out`, `channel_ineligible`, `missing_delivery` |
| `reference_token` | text | NN | **U** — reply matching (RV-06/RV-07) |
| `sent_channel` | enum | * | |
| `created_at` / `updated_at` | timestamptz | NN | |
| — | | **U** (`business_id`,`order_id`) | One request per order (RV-05) |
| — | | index (`business_id`,`state`,`due_at`) | Scheduler sweep |

### 2.20 `review_replies` ⟂

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `review_request_id` | uuid | FK → `review_requests.id`, * | Null ⇒ needs assignment (RV-07) |
| `inbound_message_id` | uuid | FK → `inbound_message_events.id`, NN | |
| `customer_id` | uuid | FK → `customers.id`, NN | |
| `order_id` | uuid | FK → `customer_orders.id`, * | |
| `content` | text | NN | **Verbatim, immutable** (RV-08) |
| `message_id` | text | NN | Provider message ID |
| `channel` | enum | NN | |
| `received_at` | timestamptz | NN | |
| `sentiment` | enum | * | `positive` \| `neutral` \| `negative` — all retained |
| `created_at` | timestamptz | NN | |
| — | | index (`business_id`,`customer_id`,`received_at` DESC) | RV-11 filters |
| — | | index (`review_request_id`) | |

### 2.21 `review_reply_products`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `review_reply_id` | uuid | FK → `review_replies.id`, NN | ON DELETE CASCADE |
| `product_id` | uuid | FK → `products.id`, NN | |
| `variant_id` | uuid | FK → `product_variants.id`, * | |
| — | | **U** (`review_reply_id`,`product_id`) | |

### 2.22 `review_permissions`

Consent state per review (RV-09).

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `review_request_id` | uuid | FK → `review_requests.id`, NN | **U** |
| `review_reply_id` | uuid | FK → `review_replies.id`, * | |
| `customer_id` | uuid | FK → `customers.id`, NN | |
| `state` | enum | NN | `pending` \| `approved` \| `anonymous` \| `declined` \| `revoked` |
| `consent_method` | enum | NN | `reply_yes` \| `reply_anonymous` \| `reply_no` \| `manual` |
| `answered_at` | timestamptz | * | |
| `revoked_at` | timestamptz | * | Blocks future exports (RV-12) |
| `consent_text_version` | text | NN | Exact wording shown |
| `created_at` / `updated_at` | timestamptz | NN | |

### 2.23 `review_cards`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `review_request_id` | uuid | FK → `review_requests.id`, NN | |
| `review_reply_id` | uuid | FK → `review_replies.id`, NN | Words copied exactly (RV-10) |
| `version` | integer | NN, default 1 | |
| `display_text` | text | NN | Must equal `review_replies.content` |
| `display_name` | text | * | Null when consent state is `anonymous` |
| `display_label` | text | NN, default 'Customer review' | Mandatory label (RV-10) |
| `is_anonymous` | boolean | NN, default false | |
| `template_version` | text | NN | Must not imitate platform UI |
| `state` | enum | NN | `draft` \| `published` \| `withdrawn` |
| `exported_at` | timestamptz | * | Audit |
| `created_at` / `updated_at` | timestamptz | NN | |
| — | | **U** (`review_request_id`,`version`) | |

### 2.24 `ad_insight_snapshots`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `scope` | enum | NN | `competitor` \| `own` |
| `account_id` | text | * | Own ad account (MP) |
| `ad_id` | text | * | Competitor ad ID (MI) |
| `advertiser_name` | text | * | |
| `ad_url` | text | * | |
| `objective` | enum | * | `sales` \| `traffic` \| `leads` — never mixed (MP-04) |
| `source_tier` | enum | NN | `meta_api` \| `licensed_provider` \| `manual_intake` (MI tiers) |
| `metrics` | jsonb | NN | Spend, impressions, reach, CTR, CPC, CPA, ROAS… or explicit nulls with reasons |
| `creative` | jsonb | * | Type, copy, hook, CTA, overlay, visible price |
| `score` | numeric(5,2) | * | MI total score |
| `score_breakdown` | jsonb | * | Component scores + evidence |
| `fetched_at` | timestamptz | NN | Freshness (MP-03) |
| `synced_at` | timestamptz | NN | |
| `created_at` | timestamptz | NN | |
| — | | index (`business_id`,`scope`,`objective`,`synced_at` DESC) | Ranking queries |

### 2.25 `ad_account_connections`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | Owner-only (MP-01) |
| `provider` | enum | NN | `meta` |
| `external_account_id` | text | NN | |
| `account_name` | text | * | |
| `scopes` | text[] | NN | `ads_read` only — read-only |
| `access_token_encrypted` | text | NN | KMS envelope-encrypted |
| `token_expires_at` | timestamptz | * | |
| `connected_by_user_id` | uuid | FK → `users.id`, NN | |
| `created_at` / `updated_at` | timestamptz | NN | |
| — | | **U** (`business_id`,`provider`,`external_account_id`) | |

### 2.26 `collaboration_suggestions`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `kind` | enum | NN | `collaborator` \| `influencer` |
| `name` | text | NN | |
| `platform` | text | * | |
| `niche` | text | * | |
| `location` | text | * | |
| `audience_metric` | jsonb | * | Only if available (CF-02) |
| `contact_route` | text | * | Only if public — no outreach (CF-03) |
| `match_reasons` | jsonb | NN | Category, product type, audience, geography |
| `is_verified` | boolean | NN, default false | IF-01 "Unverified" until confirmed |
| `source_ref` | text | * | Provider record reference |
| `created_at` / `updated_at` | timestamptz | NN | |
| — | | index (`business_id`,`kind`) | |

### 2.27 `faq_entries`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | Null ⇒ global entry |
| `faq_key` | text | NN | Stable slug/ID used for exact match |
| `answer` | text | NN | Fixed answer (AW-03) |
| `answer_type` | enum | NN | `faq` |
| `references` | jsonb | * | Screen links |
| `locale` | text | NN, default 'en' | Bangla + English (NFR) |
| `owner_user_id` | uuid | FK → `users.id`, NN | Ownership (OD-09) |
| `review_due_at` | timestamptz | NN | Staleness flagging |
| `is_active` | boolean | NN, default true | |
| `created_at` / `updated_at` | timestamptz | NN | |
| — | | **U** (`business_id`,`faq_key`,`locale`) | |

### 2.28 `faq_aliases`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `faq_entry_id` | uuid | FK → `faq_entries.id`, NN | ON DELETE CASCADE |
| `alias` | text | NN | Normalised |
| `locale` | text | NN | |
| — | | **U** (`faq_entry_id`,`alias`) | |
| — | | index (`alias`) | Exact alias lookup |

### 2.29 `chat_sessions` and `chat_messages`

**`chat_sessions`**

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `user_id` | uuid | FK → `users.id`, NN | |
| `started_at` | timestamptz | NN | |
| `last_message_at` | timestamptz | NN | |
| `created_at` | timestamptz | NN | |

**`chat_messages`**

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `chat_session_id` | uuid | FK → `chat_sessions.id`, NN | ON DELETE CASCADE |
| `role` | enum | NN | `user` \| `assistant` \| `system` |
| `content` | text | NN | |
| `answer_type` | enum | * | `faq` \| `data` \| `ai` \| `blocked` |
| `references` | jsonb | * | |
| `data_as_of` | timestamptz | * | |
| `created_at` | timestamptz | NN | |

### 2.30 `ai_usage_events`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | Request ID (AW-08) |
| `business_id` | uuid | FK, NN | |
| `user_id` | uuid | FK → `users.id`, NN | |
| `chat_session_id` | uuid | FK → `chat_sessions.id`, * | |
| `route` | enum | NN | `faq` \| `data` \| `ai` \| `blocked` |
| `input_tokens` | integer | NN, default 0 | Zero for FAQ (AW-04) |
| `output_tokens` | integer | NN, default 0 | |
| `estimated_cost` | numeric(10,6) | NN, default 0 | |
| `latency_ms` | integer | NN | |
| `model` | text | * | OD-10 |
| `tools_invoked` | text[] | * | Read-only tool names |
| `prompt_hash` | text | * | Audit without storing PII |
| `created_at` | timestamptz | NN | |
| — | | index (`business_id`,`created_at` DESC) | Cost dashboard |
| — | | index (`route`,`created_at` DESC) | Route mix |

### 2.31 `tour_steps` and `tour_progress`

**`tour_steps`**

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | Null ⇒ global |
| `step_order` | integer | NN | 1..5 |
| `target_id` | text | NN | Stable ID, not a fragile selector |
| `selector` | text | * | CSS selector fallback |
| `message` | text | NN | |
| `locale` | text | NN | |
| `is_active` | boolean | NN, default true | |
| — | | **U** (`business_id`,`step_order`,`locale`) | |

**`tour_progress`**

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `user_id` | uuid | FK → `users.id`, NN | |
| `tour_key` | text | NN | |
| `state` | enum | NN | `offered` \| `in_progress` \| `skipped` \| `completed` |
| `current_step` | integer | NN, default 1 | |
| `completed_at` | timestamptz | * | |
| `created_at` / `updated_at` | timestamptz | NN | |
| — | | **U** (`business_id`,`user_id`,`tour_key`) | |

### 2.32 `audit_log` ⟂

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `actor_user_id` | uuid | FK → `users.id`, * | Null ⇒ system |
| `action` | enum | NN | `batch_approved` \| `export_created` \| `consent_changed` \| `identity_linked` \| `role_changed` \| `faq_updated` \| `ad_account_connected` |
| `target_type` | text | NN | |
| `target_id` | text | NN | |
| `before_hash` | text | * | |
| `after_hash` | text | * | |
| `metadata` | jsonb | * | No PII |
| `ip_address` | inet | * | |
| `created_at` | timestamptz | NN | |
| — | | index (`business_id`,`created_at` DESC) | |
| — | | index (`target_type`,`target_id`) | |

### 2.33 `scheduled_jobs`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `job_type` | enum | NN | `review_request` \| `restock_batch_dispatch` \| `inventory_poll` \| `retry_delivery` |
| `run_at` | timestamptz | NN | Due time, UTC |
| `state` | enum | NN | `pending` \| `claimed` \| `done` \| `failed` \| `cancelled` |
| `payload` | jsonb | NN | |
| `idempotency_key` | text | NN | **U** — e.g. `review_request:{order_id}` |
| `attempts` | integer | NN, default 0 | |
| `last_error` | text | * | |
| `created_at` / `updated_at` | timestamptz | NN | |
| — | | **U** (`business_id`,`idempotency_key`) | One request per order, one batch dispatch |
| — | | index (`state`,`run_at`) | Scheduler sweep |

### 2.34 `notifications`

In-app dashboard notifications only — no browser push (CG-11).

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `user_id` | uuid | FK → `users.id`, * | Null ⇒ broadcast to role |
| `kind` | enum | NN | `restock` \| `bubble` \| `review_reply` \| `ad_sync` \| `chat_cost` |
| `title` | text | NN | |
| `body` | text | * | |
| `payload` | jsonb | * | Deep-link target |
| `is_read` | boolean | NN, default false | |
| `created_at` | timestamptz | NN | |

### 2.35 `message_templates` (supporting)

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | uuid | **PK** | |
| `business_id` | uuid | FK, NN | |
| `key` | text | NN | e.g. `restock_notification`, `review_request`, `review_consent` |
| `locale` | text | NN | |
| `body` | text | NN | Merge fields |
| `version` | integer | NN | Snapshotted onto batches |
| `is_active` | boolean | NN, default true | |
| `created_at` / `updated_at` | timestamptz | NN | |
| — | | **U** (`business_id`,`key`,`locale`,`version`) | |

---

## 4. Relationship Diagram

```mermaid
erDiagram
    BUSINESSES ||--o{ BUSINESS_MEMBERSHIPS : "has"
    USERS ||--o{ BUSINESS_MEMBERSHIPS : "joins"

    BUSINESSES ||--o{ CUSTOMERS : "owns"
    BUSINESSES ||--o{ CUSTOMER_ORDERS : "owns"
    BUSINESSES ||--o{ PRODUCTS : "owns"
    BUSINESSES ||--o{ MESSAGING_IDENTITY_LINKS : "owns"
    BUSINESSES ||--o{ INBOUND_MESSAGE_EVENTS : "owns"
    BUSINESSES ||--o{ CUSTOMER_BUBBLES : "owns"
    BUSINESSES ||--o{ CONTACT_PERMISSIONS : "owns"
    BUSINESSES ||--o{ PRODUCT_INTERESTS : "owns"
    BUSINESSES ||--o{ RESTOCK_EVENTS : "owns"
    BUSINESSES ||--o{ RESTOCK_BATCHES : "owns"
    BUSINESSES ||--o{ OUTBOUND_MESSAGES : "owns"
    BUSINESSES ||--o{ REVIEW_REQUESTS : "owns"
    BUSINESSES ||--o{ REVIEW_REPLIES : "owns"
    BUSINESSES ||--o{ REVIEW_PERMISSIONS : "owns"
    BUSINESSES ||--o{ REVIEW_CARDS : "owns"
    BUSINESSES ||--o{ AD_INSIGHT_SNAPSHOTS : "owns"
    BUSINESSES ||--o{ FAQ_ENTRIES : "owns"
    BUSINESSES ||--o{ CHAT_SESSIONS : "owns"
    BUSINESSES ||--o{ AI_USAGE_EVENTS : "owns"
    BUSINESSES ||--o{ TOUR_PROGRESS : "owns"
    BUSINESSES ||--o{ AUDIT_LOG : "owns"
    BUSINESSES ||--o{ SCHEDULED_JOBS : "owns"
    BUSINESSES ||--o{ NOTIFICATIONS : "owns"

    CUSTOMERS ||--o{ CUSTOMER_ORDERS : "places"
    CUSTOMER_ORDERS ||--o{ ORDER_ITEMS : "contains"
    PRODUCTS ||--o{ ORDER_ITEMS : "referenced by"
    PRODUCTS ||--o{ PRODUCT_VARIANTS : "has"
    CUSTOMERS ||--o{ MESSAGING_IDENTITY_LINKS : "identified by"
    MESSAGING_IDENTITY_LINKS }o--|| CUSTOMERS : "links to"
    MESSAGING_IDENTITY_LINKS ||--o{ IDENTITY_CONFLICTS : "may conflict"

    CUSTOMERS ||--o{ CUSTOMER_BUBBLES : "has bubble"
    INBOUND_MESSAGE_EVENTS ||--o{ CUSTOMER_BUBBLES : "triggers"
    CUSTOMERS ||--o{ CONTACT_PERMISSIONS : "has permission"

    CUSTOMERS ||--o{ PRODUCT_INTERESTS : "expresses"
    PRODUCTS ||--o{ PRODUCT_INTERESTS : "requested"
    PRODUCT_VARIANTS ||--o{ PRODUCT_INTERESTS : "requested variant"
    PRODUCT_VARIANTS ||--o{ RESTOCK_EVENTS : "restocks"
    RESTOCK_EVENTS ||--o{ RESTOCK_BATCHES : "batches"
    RESTOCK_BATCHES ||--o{ OUTBOUND_MESSAGES : "produces"

    OUTBOUND_MESSAGES ||--o{ DELIVERY_ATTEMPTS : "attempts"
    CUSTOMER_ORDERS ||--o{ REVIEW_REQUESTS : "triggers"
    CUSTOMER_ORDERS ||--o{ INBOUND_MESSAGE_EVENTS : "received on"
    REVIEW_REQUESTS ||--o{ REVIEW_REPLIES : "receives"
    REVIEW_REPLIES ||--o{ REVIEW_REPLY_PRODUCTS : "tagged"
    PRODUCTS ||--o{ REVIEW_REPLY_PRODUCTS : "tagged"
    REVIEW_REQUESTS ||--o| REVIEW_PERMISSIONS : "consent"
    REVIEW_REPLIES ||--o| REVIEW_CARDS : "rendered as"

    FAQ_ENTRIES ||--o{ FAQ_ALIASES : "has"
    CHAT_SESSIONS ||--o{ CHAT_MESSAGES : "contains"
    CHAT_SESSIONS ||--o{ AI_USAGE_EVENTS : "measures"

    USERS ||--o{ FAQ_ENTRIES : "owns"
    USERS ||--o{ TOUR_PROGRESS : "tracks"
    USERS ||--o{ AD_ACCOUNT_CONNECTIONS : "connects"

    CUSTOMERS {
        uuid id PK
        uuid business_id FK
        text source_customer_id U
        text phone_e164
        text email_normalised
        int total_orders
        numeric total_spend
        bool is_repeat_buyer
        timestamptz last_purchase_at
    }

    CUSTOMER_ORDERS {
        uuid id PK
        uuid business_id FK
        uuid customer_id FK
        text source_order_id U
        timestamptz ordered_at
        enum status
        bool qualifying
        text qualifying_rule_version
        numeric total_amount
        numeric refund_amount
        bool is_cancelled
        bool is_returned
        bool is_refunded
        timestamptz delivered_at
    }

    MESSAGING_IDENTITY_LINKS {
        uuid id PK
        uuid business_id FK
        uuid customer_id FK
        enum channel
        text channel_user_id U
        enum method
        timestamptz verified_at
    }

    INBOUND_MESSAGE_EVENTS {
        uuid id PK
        uuid business_id FK
        text provider_event_id U
        enum channel
        text conversation_id
        text channel_user_id
        text content
        timestamptz received_at
        uuid resolved_customer_id FK
    }

    CUSTOMER_BUBBLES {
        uuid id PK
        uuid business_id FK
        uuid customer_id FK
        text conversation_id U
        bool is_returning_customer
        int order_count
        numeric total_spend
        enum state
        timestamptz last_message_at
        timestamptz seen_at
        timestamptz dismissed_at
    }

    PRODUCT_INTERESTS {
        uuid id PK
        uuid business_id FK
        uuid customer_id FK
        uuid product_id FK
        uuid variant_id FK
        timestamptz requested_at
        int quantity
        enum contact_channel
        enum source
    }

    RESTOCK_EVENTS {
        uuid id PK
        uuid business_id FK
        uuid product_id FK
        uuid variant_id FK
        timestamptz detected_at
        int stock_after
    }

    RESTOCK_BATCHES {
        uuid id PK
        uuid business_id FK
        uuid restock_event_id FK
        uuid approved_by_user_id FK
        text template_version
        enum state
        text idempotency_key U
    }

    OUTBOUND_MESSAGES {
        uuid id PK
        uuid business_id FK
        enum purpose
        uuid ref_id
        uuid customer_id FK
        enum channel
        text idempotency_key U
        enum status
        text skip_reason
        text error_code
        int attempt_count
        timestamptz sent_at
    }

    REVIEW_REQUESTS {
        uuid id PK
        uuid business_id FK
        uuid order_id FK U
        uuid customer_id FK
        timestamptz delivery_confirmed_at
        timestamptz due_at
        enum state
        text state_reason
        text reference_token U
    }

    REVIEW_REPLIES {
        uuid id PK
        uuid business_id FK
        uuid review_request_id FK
        uuid inbound_message_id FK
        text content
        text message_id
        enum channel
        timestamptz received_at
        enum sentiment
    }

    REVIEW_PERMISSIONS {
        uuid id PK
        uuid business_id FK
        uuid review_request_id FK U
        enum state
        enum consent_method
        timestamptz answered_at
        timestamptz revoked_at
    }

    REVIEW_CARDS {
        uuid id PK
        uuid business_id FK
        uuid review_request_id FK
        uuid review_reply_id FK
        text display_text
        bool is_anonymous
        text display_label
        enum state
    }

    AD_INSIGHT_SNAPSHOTS {
        uuid id PK
        uuid business_id FK
        enum scope
        text account_id
        text ad_id
        enum objective
        enum source_tier
        jsonb metrics
        numeric score
        timestamptz synced_at
    }

    FAQ_ENTRIES {
        uuid id PK
        uuid business_id FK
        text faq_key U
        text answer
        uuid owner_user_id FK
        timestamptz review_due_at
        bool is_active
    }

    AI_USAGE_EVENTS {
        uuid id PK
        uuid business_id FK
        uuid user_id FK
        enum route
        int input_tokens
        int output_tokens
        numeric estimated_cost
        int latency_ms
    }
```

---

## 5. Key Constraint Summary

| Rule | Enforcement | Requirement |
|---|---|---|
| Inbound events processed once | **U** (`business_id`,`provider_event_id`) | CG-08, RP-T05, RV-T04 |
| One bubble per customer + conversation | **U** (`business_id`,`customer_id`,`conversation_id`) | CG-08 |
| One outbound message per recipient per channel | **U** (`idempotency_key`) | RP-08, RP-T05 |
| One review request per order | **U** (`business_id`,`order_id`) | RV-05 |
| One consent record per review request | **U** (`review_request_id`) | RV-09 |
| One scheduled job per logical action | **U** (`business_id`,`idempotency_key`) | RV-05, RP-07 |
| One channel identity → one customer | **U** (`business_id`,`channel`,`channel_user_id`) | CG-03 |
| One membership role per user per business | **U** (`business_id`,`user_id`) | Roles matrix |
| Reply text is immutable | `BEFORE UPDATE` trigger raising an exception ⟂ | RV-08 |
| Audit log is immutable | `BEFORE UPDATE`/`DELETE` triggers raising ⟂ | Audit requirement |
| Tenant scope always present | NOT NULL `business_id` on every tenant table + repository guard | Tenant isolation |

---

## 6. Indexing Strategy

| Table | Index | Purpose |
|---|---|---|
| `customers` | (`business_id`,`phone_e164`), (`business_id`,`email_normalised`), (`business_id`,`source_customer_id`) U | Identity resolution (CG-03) |
| `customers` | (`business_id`,`total_orders` DESC) WHERE `is_repeat_buyer` | Repeat Buyers list (CG-01) |
| `customer_orders` | (`business_id`,`customer_id`,`ordered_at` DESC) | History timeline (CG-02) |
| `customer_orders` | (`business_id`,`qualifying`,`ordered_at` DESC) | Qualifying-order counting (CG-06) |
| `order_items` | (`business_id`,`product_id`) | Product filter (CG-02) |
| `inbound_message_events` | (`business_id`,`channel_user_id`,`received_at` DESC) | Identity lookup |
| `inbound_message_events` | (`business_id`,`conversation_id`,`received_at` DESC) | Reply thread matching (RV-07) |
| `customer_bubbles` | (`business_id`,`state`,`last_message_at` DESC) | Bubble list |
| `product_interests` | (`business_id`,`variant_id`,`requested_at`) | Waiting list (RP-03) |
| `outbound_messages` | (`status`,`next_attempt_at`) WHERE `status='pending'` | Dispatcher claim (partial index) |
| `outbound_messages` | (`business_id`,`purpose`,`status`) | Delivery reporting |
| `review_requests` | (`business_id`,`state`,`due_at`) | Scheduler sweep |
| `review_requests` | (`business_id`,`reference_token`) U | Reply token matching |
| `review_replies` | (`business_id`,`customer_id`,`received_at` DESC) | Review library (RV-11) |
| `ad_insight_snapshots` | (`business_id`,`scope`,`objective`,`synced_at` DESC) | Ranking (MP-04) |
| `faq_aliases` | (`alias`) | FAQ exact match (AW-03) |
| `ai_usage_events` | (`business_id`,`created_at` DESC), (`route`,`created_at` DESC) | Cost + route mix (AW-08) |
| `audit_log` | (`business_id`,`created_at` DESC) | Audit UI |

---

## 7. Data Lifecycle

| Data | Lifecycle | Notes |
|---|---|---|
| Customer & order mirrors | Refreshed by incremental sync; rows for deleted source records are tombstoned, not hard-deleted | History integrity |
| `inbound_message_events` | Retained per privacy policy (OD-07) | Required for reply matching |
| `review_replies` | Retained; immutable; subject to erasure requests | Legal (OD-07) |
| `review_permissions` | Retained as the consent audit trail | Consent revocation ≠ deletion |
| `outbound_messages` | Retained as the delivery record; used for reporting | |
| `ai_usage_events` | Retained per OD-10 chat retention policy | Cost and privacy |
| `chat_messages` | Retained per OD-10 | |
| `audit_log` | Long-term retention | Never modified |
| `delivery_attempts` | Cascade-deleted with the parent message after the retention window | |

---

## 8. Traceability

| PRD requirement | Entities |
|---|---|
| CG-01 Repeat Buyers list | `customers` (`is_repeat_buyer`, `total_orders`) |
| CG-02 Customer history | `customer_orders`, `order_items` |
| CG-03 Identity matching | `messaging_identity_links`, `identity_conflicts`, `customers` |
| CG-04 Data source | `customers`, `customer_orders.source_payload` |
| CG-05…CG-11 Bubbles | `inbound_message_events`, `customer_bubbles`, `messaging_identity_links` |
| RP-01…RP-10 Restore Product | `product_interests`, `restock_events`, `restock_batches`, `outbound_messages`, `delivery_attempts`, `contact_permissions`, `message_templates` |
| RV-01…RV-13 Review | `review_settings`, `review_requests`, `review_replies`, `review_reply_products`, `review_permissions`, `review_cards` |
| MI-01…MI-05 Ads intelligence | `ad_insight_snapshots` (`scope='competitor'`) |
| MP-01…MP-04 Own ads | `ad_account_connections`, `ad_insight_snapshots` (`scope='own'`) |
| CF-01…CF-03, IF-01…IF-02 | `collaboration_suggestions` |
| AW-01…AW-09 Chat | `faq_entries`, `faq_aliases`, `chat_sessions`, `chat_messages`, `ai_usage_events` |
| AW-10…AW-11 Tour | `tour_steps`, `tour_progress` |
| Platform services | `scheduled_jobs`, `audit_log`, `notifications` |
