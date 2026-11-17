# Development Plan

**Project:** Xenovarients — Customer Genome · Creator Commerce · Agent Workspace
**Version:** 1.0 · **Date:** 17 November 2026
**Strategy:** Backend first, frontend second. Every frontend screen is a thin view over an API that already exists and is tested.

**Source documents:** `PRD.md` · `TRD.md` · `ERD.md` · `USER_FLOW.md` · `ARCHITECTURE.md` · `UI_UX_DESIGN.md`

---

## 1. Why backend first

The product has three properties that make backend-first the only sane order:

1. **Nothing is sent without a human decision.** Restore Product and Review both end in a batch that must be previewed, confirmed and audited. The batch preview, eligibility evaluation, idempotency key and delivery log must be correct *before* there is a button to press. A frontend-first build would have mocked all of it.
2. **The correctness rules are subtle and concentrated in the server.** Qualifying-order logic, identity resolution, channel eligibility at send time, consent gating on export, and the zero-token FAQ route are all server concerns. If the frontend is built first, these get re-implemented (wrongly) in the browser.
3. **"No fabricated data" is a server contract.** Unavailable values, unresolved references and stale data must come back from the API as explicit states. A mock API cannot enforce this.

**Consequence:** the frontend is built against a **frozen API contract** (OpenAPI schema) rather than against a moving target. No screen is designed against a mock that later changes shape.

---

## 2. Phase overview

| Phase | Scope | Depends on | Exit criteria |
|---|---|---|---|
| **0 Feasibility** | Resolve the 5 blocking open decisions with go/no-go answers | — | OD-01, OD-05, OD-06, OD-11 closed |
| **1 Backend Foundation** | Repo, config, DB, models, migrations, tenant guard, auth, RBAC | Phase 0 | Tenant-isolation and idempotency tests pass |
| **2 Platform Services** | Identity & Consent, Messaging Gateway, Scheduler, Realtime, Audit Log | Phase 1 | Shared services pass isolation + idempotency tests |
| **3 M1 Customer Genome** | Adapter, history, Repeat Buyers, bubbles, Restore Product | Phase 2 | CG-T01…T08, RP-T01…T08 pass |
| **4 M2 Creator Commerce** | Review, consent, cards, export, ads intelligence, own ads, collaborations | Phase 2 | RV, MI, MP, CF tests pass |
| **5 M3 Agent Workspace** | FAQ registry, chat routing, read-only tools, usage metering, tour | Phase 2 | AW-T01…T10 pass |
| **6 Frontend** | App shell + all 28 screens | Phase 3 (M1 screens) · can start shell at Phase 2 | Every screen renders real API data; no mock in the shipped build |
| **7 Hardening & Release** | Security review, cross-tenant suite, load, failure, CI, staged rollout | Phase 6 | Definition of Done met |

**Parallelisation**

```
Phase 0 ──► Phase 1 ──► Phase 2 ──┬──► Phase 3 ──┐
                                   ├──► Phase 4 ──┼──► Phase 6 ──► Phase 7
                                   └──► Phase 5 ──┘
```

Phases 3, 4 and 5 are independent of each other and can run concurrently once Phase 2 lands. The frontend shell (Phase 6 step 1) can start as soon as auth and the tenant guard exist, but each module's screens wait for that module's API.

**Phase 0 is not optional.** OD-06 (Meta ad data tier) alone can invalidate an entire feature. Five days of feasibility work can save a month of building against an API that returns nothing.

---

## 3. Phase 0 — Feasibility (blocking, ~1 week)

The spec marks 13 decisions **OPEN**. Five of them gate the build and must be answered before Phase 1 writes code that cannot be changed cheaply.

### 3.1 The five blocking decisions

| ID | Decision | Why it blocks | Investigation | Fallback if it fails |
|---|---|---|---|---|
| **OD-01** | Customer, order and inventory data source + integration method | Every M1 feature reads from this. The adapter interface, the schema of ingested records and the restock detection loop all depend on the answer | Talk to the source system owner. Confirm: read API vs database access vs CSV/Excel exports; incremental sync support (cursor / `updated_since`); delivery confirmation field; inventory availability field and its granularity (product vs variant) | If there is no API: build the adapter against CSV/SFTP export and a scheduled import job. If inventory is not variant-level, RP-03 ("variants are never mixed") cannot be honoured — escalate |
| **OD-05** | Channel eligibility per provider | Decides whether Restore Product and Review can reach customers on Messenger/WhatsApp at all, and whether the free-reply window has closed by send time | Current Meta Messenger messaging-policy window rules; WhatsApp Business template requirements and session window; SMS gateway opt-out handling; email authenticated-domain requirements | If Messenger/WhatsApp windows turn out to be too restrictive, Email + SMS become the only default channels. The eligibility engine already supports this — it becomes a **configuration** decision, not a rewrite |
| **OD-06** | Meta ad data tier for Bangladesh commercial ads | Determines whether MI-01…MI-05 ship at all, and which implementation | Test the official Ad Library API for the target country and ad type. Check a licensed provider's coverage for BD. Confirm the manual-intake tier is acceptable as the shipped default | Tier 3 (manual intake) ships as the baseline. MI ships in a reduced form with an honest coverage banner. Tier 1/2 are additive later — the `*Source` interface is unchanged |
| **OD-11** | Technology stack and hosting | Decides the repo layout, the ORM, the queue and the deploy target | Confirm the host: any Postgres 15+ with managed Redis works. Confirm team familiarity | The reference stack in TRD §2 is the default: FastAPI + PostgreSQL + Redis + SSE + Next.js |
| **OD-13** | UI language | Affects DB schema (`locale` columns), template storage and the frontend i18n setup | Ask the owner: English only, Bangla only, or both with a switcher | Both, with English as the default. The schema already carries `locale` on templates, FAQs and tour steps |

### 3.2 The eight non-blocking decisions

These do not stop Phase 1. Each gets a documented default now and a config key, so a later decision is a data change, not a migration.

| ID | Default applied during the build | Where it lives |
|---|---|---|
| OD-02 | Qualifying order = paid or completed; cancelled and fully refunded excluded; partial refunds counted net. Returning = ≥1 order, Repeat = ≥2 orders | `business_settings.qualifying_order_rules`, versioned |
| OD-03 | Multi-tenant SaaS, shared schema with `business_id` discriminator + PostgreSQL RLS as defence in depth | Every table + `TenantFilter` |
| OD-04 | Bubbles are in-dashboard only, persisted indefinitely, dismissed bubbles re-open on a new inbound message | `customer_bubbles.state` |
| OD-07 | Reviews and chats retained 24 months; consent records retained indefinitely as the audit trail; erasure request deletes PII but keeps the consent record | Retention job + `legal_hold` flag |
| OD-08 | Delay 3 days, send window 09:00–20:00, reply window 14 days, one request per order | `review_settings` |
| OD-09 | FAQ owners are Owner and Admin; each entry has a `review_due_at`; overdue entries are flagged | `faq_entries.owner_user_id` |
| OD-10 | LLM provider chosen at Phase 5; cost cap per request and per business per day; PII redacted before the provider call | `LLMPort` + `ai_usage_events` |
| OD-12 | Stock warning when `stock_after < count(eligible waiting list)`; the inventory source is authoritative | `product_variants.stock_on_hand` |

### 3.3 Phase 0 deliverables

- `docs/decisions/OD-01.md` … `OD-13.md` — one file per decision: the question, the options considered, the answer, the date, who decided.
- A `configs/` directory of channel eligibility rules per provider, written as data not code.
- A spike branch for each risky integration (Ad Library tier, source adapter, channel windows).

---

## 4. Phase 1 — Backend Foundation

**Goal:** a running API where a tenant cannot see another tenant's data, and where the same request twice does the same thing once.

### 4.1 Repo layout

```
backend/
  app/
    main.py              FastAPI app factory
    config.py            Settings from env, no magic strings
    db/                  Session, base, TenantFilter, RLS session var
    models/              SQLAlchemy models, one file per bounded area
    schemas/             Pydantic request/response models
    api/                 Routers, one per module
    services/            Business logic, one file per feature
    platform/            The five shared services (Phase 2)
    jobs/                Queue consumers and scheduled tasks
    adapters/            External source adapters (Phase 3)
  alembic/               Migrations
  tests/
    unit/  integration/  contract/  security/
frontend/                Next.js app (Phase 6)
docs/
```

### 4.2 Tasks

| # | Task | Done when |
|---|---|---|
| 1.1 | Init repo, `backend/` + `frontend/` folders, `git init`, `.gitignore`, `README` | `git log` shows the first commit |
| 1.2 | `pyproject.toml` with pinned deps: `fastapi`, `uvicorn`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pydantic-settings`, `redis`, `httpx`, `pytest`, `pytest-asyncio`, `ruff`, `mypy` | `uvicorn app.main:app --reload` serves `/health` |
| 1.3 | `docker-compose.yml`: Postgres 16, Redis 7, MailHog | `docker compose up` gives a working DB |
| 1.4 | `config.py` — pydantic-settings, all env vars typed, no defaults for secrets | `Settings()` loads from env; missing secret fails fast |
| 1.5 | Alembic wired to `models/`; first migration creates `businesses`, `users`, `business_memberships` | `alembic upgrade head` succeeds on a clean DB; `downgrade` also succeeds |
| 1.6 | `db/session.py` — async engine, session factory, `TenantContext` | Every request handler can read `tenant.business_id` |
| 1.7 | **`db/tenant.py` — `TenantFilter`**: a `DeclarativeBase` event listener that appends `business_id = :bid` to every SELECT/UPDATE/DELETE on a tenant-scoped model, and raises `TenantScopeError` if `business_id` is not in the context | A test that queries without a tenant context raises |
| 1.8 | Postgres RLS: `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` + a policy using `current_setting('app.business_id')`; the session sets the variable per transaction | Cross-tenant query returns 0 rows even if the ORM guard is bypassed |
| 1.9 | Auth: password hash (argon2), OIDC-ready JWT issue/verify, `/api/auth/login`, `/api/auth/logout`, `/api/auth/me` | A login returns a token; the token resolves to user + business + role |
| 1.10 | RBAC dependency: `require_role("owner")` etc., wired per endpoint | Staff calling an Owner endpoint gets 403 |
| 1.11 | API conventions: RFC 7807 errors, request-ID middleware, cursor pagination helper, `Idempotency-Key` header handling | Consistent error shape across all routers |
| 1.12 | Structured logging with `request_id`; `/health` and `/ready` | Log lines carry `request_id` |
| 1.13 | Test harness: `pytest` + `httpx` async client + a per-test transaction rollback fixture; a `factories.py` with `business()`, `user()`, `customer()`, `order()` | Tests write no cleanup code |

### 4.3 Exit criteria

- [ ] `alembic upgrade head` and `alembic downgrade base` both succeed from clean.
- [ ] **Tenant isolation test**: for every tenant-scoped table, a query under tenant A cannot see tenant B's rows. This test is *the* gate for the whole phase.
- [ ] **Idempotency test**: the same `Idempotency-Key` twice yields one effect.
- [ ] `mypy` and `ruff` clean.
- [ ] Every endpoint returns a `request_id`.

---

## 5. Phase 2 — Shared Platform Services

**Goal:** the five services that every module depends on, so no feature builds its own messaging, identity or scheduling.

### 5.1 Tasks

| # | Service | Key deliverables | Done when |
|---|---|---|---|
| 2.1 | **Identity & Consent** | `messaging_identity_links`, `contact_permissions`, `review_permissions`, `identity_conflicts`; `resolve(channel, channel_user_id)` returning confident-match / no-match / conflict; `link()`, `unlink()`, `check_permission()` | ✅ A Messenger identity with no link resolves to *no confident match* and raises no exception; a conflict is recorded, never merged |
| 2.2 | **Messaging Gateway — inbound** | `POST /webhooks/messaging/{channel}`; per-provider HMAC-SHA256 signature verification (constant-time compare + timestamp window); `inbound_message_events` insert with the unique `provider_event_id`; fast ACK then async processing | ✅ A replayed webhook returns `duplicate: true` and produces no second row |
| 2.3 | **Messaging Gateway — outbound** | `outbound_messages` + `delivery_attempts`; the **outbox** pattern (business transaction writes `pending` rows; a separate dispatcher sends); `ChannelAdapter` protocol with `send()` and `eligibility()`; four adapters (Email, SMS, Messenger, WhatsApp) with the eligibility rules from OD-05; bounded retries (max 3, exponential backoff); per-channel rate limits | ✅ One failed recipient does not affect the others; a retried send does not duplicate |
| 2.4 | **Scheduler & Queue** | Redis-backed queue; `scheduled_jobs` with a unique `idempotency_key`; delayed-job dispatch at `run_at`; job retry with backoff; a worker entry point | ✅ The same logical job scheduled twice exists once |
| 2.5 | **Realtime** | Redis pub/sub → SSE endpoint per business; events `bubble.created`, `bubble.updated`, `bubble.removed`; client reconnect supported | ✅ A publish reaches a connected SSE client within the 5 s p95 budget |
| 2.6 | **Audit Log** | Immutable `audit_log` (DB trigger blocking UPDATE/DELETE); `Audit.record()`; used by batch approval, export, consent change, identity link, role change | ✅ An UPDATE on `audit_log` raises |
| 2.7 | **Notification service** | In-app `notifications` table + a bell badge count. No browser push (CG-11) | ✅ A restock event creates an owner notification and no outbound message |
| 2.8 | **Idempotency middleware** | `Idempotency-Key` → stored result, replayed on repeat | ✅ The REST API surface replays a stored response, not a fresh one |

### 5.2 Exit criteria

- [x] Every shared service has an isolation test (no cross-tenant read). — `tests/security/test_service_isolation.py` asserts each layer separately: the ORM layer on the compiled statement, the RLS layer on the visible result.
- [x] Every shared service has an idempotency test. — identity link, `provider_event_id`, `idempotency_key`, scheduler key, and the `Idempotency-Key` middleware.
- [x] A full inbound→outbound round trip works end to end with a stub adapter. — `tests/integration/test_round_trip.py`.
- [x] Retry budget is enforced and visible in `delivery_attempts`. — the attempt count equals the budget exactly, and a spent budget schedules no further attempt.
- [x] `audit_log` rejects mutation. — `tests/security/test_audit_log.py`.

---

## 6. Phase 3 — M1 Customer Genome

### 6.1 Task breakdown

| # | Task | Requirements |
|---|---|---|
| 3.1 | Source adapter interface + a stub adapter with seeded fixtures | CG-04 |
| 3.2 | Sync job: full backfill + incremental `updated_since`; phone → E.164, email → lowercase normalisation; source status → `qualifying` mapping with a rule version | CG-04, OD-02 |
| 3.3 | `customers`, `customer_orders`, `order_items`, `products`, `product_variants` models + derived `total_orders`, `total_spend`, `last_purchase_at`, `is_repeat_buyer` | CG-01, CG-02 |
| 3.4 | `GET /api/customer-genome/repeat-buyers` — cursor-paginated, filters | CG-01 |
| 3.5 | `GET /api/customers/{id}/history` — timeline, date + product filters | CG-02 |
| 3.6 | Identity resolution ladder: verified link → phone → email → staff link → never display name | CG-03 |
| 3.7 | `POST /api/customers/{id}/link-identity`, `GET/PATCH /api/customer-genome/returning-bubbles` | CG-03, CG-08, CG-10 |
| 3.8 | Bubble engine: qualify by `received_at`, upsert on (business, customer, conversation), state machine new/seen/dismissed, re-open on new message | CG-05…CG-08, CG-11 |
| 3.9 | Live figures recomputed from authoritative history, with `data_as_of` | CG-09 |
| 3.10 | `product_interests`, waiting-list grouping by product **and** variant | RP-02, RP-03 |
| 3.11 | Restock detection worker: unavailable → available transition → `restock_events` + owner notification, **no send path** | RP-04 |
| 3.12 | Batch preview: recipients, channel per recipient, eligibility, skip reasons, stock warning, template merge preview | RP-05…RP-07, RP-09 |
| 3.13 | Owner-confirmed batch: `POST .../notifications` with `Idempotency-Key`; creates `restock_batches` + `outbound_messages`; **skips ineligible recipients** | RP-07, RP-08 |
| 3.14 | Delivery history read endpoint | RP-10 |

### 6.2 Exit criteria

- [ ] CG-T01 … CG-T08 pass.
- [ ] RP-T01 … RP-T08 pass.
- [ ] A restock event **provably** cannot send a message — asserted by a test that greps the call graph from the detection worker to the Gateway's send path and expects no route.
- [ ] Confirming a batch twice produces one message per recipient per channel.
- [ ] A customer with one order gets a bubble but is absent from the Repeat Buyers list.

---

## 7. Phase 4 — M2 Creator Commerce

| # | Task | Requirements |
|---|---|---|
| 4.1 | `review_settings` + `GET/PATCH /api/creator-commerce/reviews/settings` — delay, send window, reply window, channel order, template | RV-03, RV-05, RV-06 |
| 4.2 | Delivery-confirmed listener → create `review_requests` (unique per order), compute `due_at` in business tz | RV-02, RV-05 |
| 4.3 | Send-time eligibility re-check; cancel on cancelled/returned/refunded with a visible reason | RV-04 |
| 4.4 | Reply matcher: token → thread → `needs_assignment` | RV-07 |
| 4.5 | `review_replies` with an immutable `content` (DB trigger blocking UPDATE) | RV-08 |
| 4.6 | Consent request flow + `review_permissions` state machine + revocation | RV-09 |
| 4.7 | `review_cards` — text copied exactly from the reply, mandatory "Customer review" label, template whitelist that cannot imitate platform UI | RV-10 |
| 4.8 | Review library + detail endpoints with filters | RV-11, RV-13 |
| 4.9 | Consent-gated export; `anonymous` hides identity; revoked excluded and counted | RV-12 |
| 4.10 | Ads intelligence: `AdSource` interface with three tiers; scoring (40/25/20/15) with evidence; untrusted-copy isolation in the prompt | MI-01…MI-05 |
| 4.11 | Own ads: Meta OAuth (`ads_read` only), token encryption, snapshot sync, metrics with explicit N/A reasons, freshness | MP-01…MP-03 |
| 4.12 | Deterministic objective-aware ranking with visible guard thresholds | MP-04 |
| 4.13 | Collaboration Finder from a licensed source; the outbound service rejects `purpose='collaboration'` | CF-01…CF-03 |
| 4.14 | Influencer Suggestions behind a feature flag; disabled = route hidden, nothing else changes | IF-01, IF-02 |

### 7.1 Exit criteria

- [ ] RV-T01 … RV-T11 pass.
- [ ] MI-T01, MI-T02 pass.
- [ ] MP-T01, MP-T02 pass.
- [ ] CF-T01, IF-T01 pass.
- [ ] A negative review is stored and displayed identically to a positive one.
- [ ] Revoked consent blocks export while the consent record survives.
- [ ] The outbound service refuses a `collaboration` purpose (tested).

---

## 8. Phase 5 — M3 Agent Workspace

| # | Task | Requirements |
|---|---|---|
| 5.1 | `faq_entries`, `faq_aliases`; editor permissions (Owner/Admin); `review_due_at` staleness | AW-03, OD-09 |
| 5.2 | Normaliser: lowercase, strip punctuation, Bangla Unicode NFC, Banglish folding | AW-03 |
| 5.3 | FAQ matcher: exact key → alias → similarity threshold; **falls through** when below threshold | AW-04 |
| 5.4 | Data-intent handlers against a **query registry** — a fixed set of parameterised read-only queries, not generated SQL | AW-05 |
| 5.5 | AI route: `LLMPort`, redacted payload, delimited untrusted blocks, schema-constrained output, read-only tool registry with per-call tenant+role check | AW-06, AW-07, OD-10 |
| 5.6 | Blocked-intent detection → refusal; no write tool exists | AW-06 |
| 5.7 | `ai_usage_events` — route, tokens, latency, cost; FAQ rows record **zero** tokens | AW-04, AW-08 |
| 5.8 | Chat session and message endpoints; response shape `answer / answer_type / references / data_as_of / usage` | AW-01, AW-08 |
| 5.9 | Image upload rejected with a clear message | AW-09 |
| 5.10 | `tour_steps`, `tour_progress`; step CRUD, reorder, activate; target-found check | AW-10, AW-11 |

### 8.1 Exit criteria

- [ ] AW-T01 … AW-T10 pass.
- [ ] A FAQ match records `input_tokens=0, output_tokens=0, estimated_cost=0`.
- [ ] A prompt injected into ad copy cannot cause a tool call outside the allow-list — tested with a corpus.
- [ ] The tool registry contains no write operation — asserted by a test that enumerates the registry.
- [ ] A Staff user cannot read another tenant's data through the chat.

---

## 9. Phase 6 — Frontend

**Rule:** the frontend consumes the frozen OpenAPI schema. It contains no mock server in the shipped build. Screens that need a backend capability that does not exist yet are **not built** — they are marked blocked in the tracker.

### 9.1 Structure

```
frontend/
  src/
    app/            Next.js routes, one per screen in UI_UX_DESIGN.md
    components/     Design-system components + feature components
    lib/            API client (generated types), SSE hook, formatters
    styles/         Tokens from UI_UX_DESIGN.md §4
```

### 9.2 Build order

| Step | Work | Depends on |
|---|---|---|
| 6.1 | Next.js + Tailwind scaffold; design tokens from `UI_UX_DESIGN.md` §4 | — |
| 6.2 | App shell: sidebar (exact group order and positions from the spec), top bar, content region, right drawer, overlay layer | Phase 1 auth |
| 6.3 | API client + typed hooks generated from the OpenAPI schema | Phase 2 |
| 6.4 | Component library: button, input, table, chip, stat-card, card, alert, modal, drawer, toast, skeleton, tooltip, **unavailable-chip** | 6.1 |
| 6.5 | State patterns: loading skeleton, empty, error, stale, unresolved — **all five** on every list screen | 6.4 |
| 6.6 | S-21, S-22 Auth | Phase 1 |
| 6.7 | S-01 Dashboard | Phase 3 |
| 6.8 | S-02, S-03 + M-01, M-02 | Phase 3 |
| 6.9 | S-04, S-05, S-06, S-07 | Phase 3 |
| 6.10 | S-08, S-09, S-10, S-11, S-12 | Phase 4 |
| 6.11 | S-13, S-14, S-15, S-15b | Phase 4 |
| 6.12 | S-16 Chat + floating launcher | Phase 5 |
| 6.13 | S-16b Bubble overlay, S-17b Tour overlay, S-18, S-19 | Phase 5 |
| 6.14 | S-17 Notifications, S-20 Settings | Phase 2 |
| 6.15 | Responsive variants (768 / 960 breakpoints) | all |
| 6.16 | Accessibility pass: keyboard, focus, contrast, screen-reader labels | all |

### 9.3 The Bubble component

The single most important frontend piece. It must:
- live in the shell **above** the route, so it survives navigation and appears on every page;
- connect to the SSE stream and render `bubble.created` / `bubble.updated` / `bubble.removed`;
- never show the "Returning Customer" label or any figures when `is_returning_customer` is false;
- offer **Link customer** when `link_customer_offered` is true;
- work with browser notifications blocked (no push permission requested);
- stack multiple bubbles with a `+N` counter opening the right drawer;
- re-open a dismissed bubble on a new inbound message.

### 9.4 Exit criteria

- [ ] All 28 screens from `UI_UX_DESIGN.md` render **real** API data.
- [ ] No mock in the production build (grep for fixtures in `src/`).
- [ ] Every list screen implements loading, empty, error, stale and unresolved states.
- [ ] Every "unknown" value renders the grey `unavailable-chip`, never a blank or a zero.
- [ ] Cross-tenant access returns 403/404 with no data in the UI.
- [ ] Lighthouse a11y score ≥ 95 on the main screens.
- [ ] Keyboard-only walkthrough of every interactive element.

---

## 10. Phase 7 — Hardening & Release

| Area | Work |
|---|---|
| **Security** | Cross-tenant matrix test over every endpoint; IDOR sweep on every `{id}` route; signature-bypass attempts; role-escalation attempts; dependency scan; secret-leak scan in logs and bundles |
| **Data correctness** | Reconciliation job comparing adapter totals with the source; proving no fabricated rows exist; proving missing data renders as unavailable |
| **Failure** | Kill the worker mid-batch → no duplicate sends; provider outage → bounded retries; LLM outage → chat degrades to FAQ + DATA; DB failover → no lost events; stale inventory → no false restock events |
| **Load** | Webhook burst → bubble p95 ≤ 5 s; concurrent restock batches; chat concurrency; cost per request |
| **CI/CD** | lint → unit → integration → migration up/down → contract → security → build → staging → smoke → owner acceptance → production |
| **Release** | Feature flags per tenant; expand/contract migrations; staged rollout internal → 5% → 25% → 100%; automatic rollback on error-rate breach |
| **Docs** | API reference generated from OpenAPI; runbook; on-call guide |

### Definition of Done (binding, from the spec)

1. All acceptance tests for the feature pass.
2. Cross-tenant access test and duplicate-event test pass.
3. Empty, error and unavailable-data states are designed and tested.
4. Requirements, API and data-model sections updated in the master document.

---

## 11. Cross-cutting rules for every phase

| Rule | Enforcement |
|---|---|
| Tenant isolation | `TenantFilter` + RLS + a test on every endpoint. Not optional, not deferred. |
| Idempotency | Unique constraints on inbound event IDs, outbound keys, review requests, scheduled jobs |
| No fabricated data | The API returns `null` + a reason enum. The frontend renders the unavailable chip. Never a default. |
| Least data to AI | Redaction before the provider call; the AI route receives a minimum payload |
| Untrusted input | Customer text, review text and ad copy are data, never instructions. Delimited blocks only. |
| Time | Store UTC; display and schedule in the business time zone |
| Audit | Batch approvals, exports, consent changes, identity links, role changes — all logged immutably |
| Read-only where required | No publish, no budget edit, no outreach, no delete. Enforced by the absence of the capability, not by a permission check |

---

## 12. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Meta Ad Library has no BD commercial coverage (OD-06) | High | MI ships reduced | Phase 0 spike; Tier 3 manual intake ships as the baseline; the interface makes Tier 1/2 additive |
| R2 | Messenger/WhatsApp windows closed at send time (OD-05) | High | Restock and Review reach fewer customers | Email + SMS as defaults; the eligibility engine reads provider rules from config, not code |
| R3 | Meta app review and business verification take longer than the build | High | My Ads Performance slips | Start at Phase 0 (the spec already flags this); the module is a separate phase so it can ship later |
| R4 | The source system has no API, only manual exports | Medium | The adapter becomes a file import | The adapter interface is chosen for this reason; CSV/SFTP import is one implementation of it |
| R5 | Inventory granularity is product-level, not variant-level | Medium | RP-03 ("variants never mixed") cannot be honoured | Escalate in Phase 0; a product-level fallback groups by product only and states it |
| R6 | Bangla/FastAPI and Unicode normalisation edge cases | Medium | FAQ matching misses | `unicodedata` NFC + a maintained Banglish alias table; AW-T02 covers it |
| R7 | Scope creep from the 26 screens | High | The release never ships | Phase 6 is gated per screen on a real API; IF is optional; the 5 phases have hard exit criteria |
| R8 | SSE does not survive the load balancer | Medium | Bubbles stop appearing | SSE reconnect + refetch-on-reconnect; the bubble list is always refetched, never treated as the source of truth |
| R9 | LLM cost surprises | Medium | Budget overrun | Per-request and per-business-per-day caps; FAQ route costs zero by construction; every call metered |

---

## 13. Working agreement

**Definition of ready** (a task may start when):
- its phase exit criteria for the previous phase are met;
- the requirement IDs it covers are listed in the task;
- the API shape is settled in the OpenAPI schema.

**Definition of done** (a task is finished when):
- its acceptance tests pass;
- its isolation and idempotency tests pass (where the task touches those paths);
- all five UI states exist (for frontend tasks);
- no `TODO` without a ticket reference;
- the doc it invalidates is updated in the same commit.

**Two rules that are never relaxed:**
1. A feature is not "done" if it sends something without a human confirmation step.
2. A feature is not "done" if it shows a value it does not actually know.

---

## 14. Document map

| Document | Purpose |
|---|---|
| `Project.md` | The source spec — requirement IDs live here |
| `PRD.md` | Product scope and acceptance criteria |
| `TRD.md` | Technical design, API surface, NFRs |
| `ERD.md` | 35 entities, keys, constraints, indexes |
| `USER_FLOW.md` | 11 flows, state machines, 36 edge cases |
| `ARCHITECTURE.md` | Services, cross-cutting mechanisms, deployment |
| `UI_UX_DESIGN.md` | 28 screens, design system, Stitch prompts |
| `DEVELOPMENT_PLAN.md` *(this file)* | Build order, exit criteria, risk register |
| `decisions/OD-*.md` | One file per open decision, written as they are resolved |
