# System Architecture

**Project:** Xenovarients — Customer Genome · Creator Commerce · Agent Workspace
**Version:** 1.0 (derived from Master Project Documentation v3.0, 16 November 2026)
**Audience:** Architects, developers, DevOps, security reviewers, technical leads

---

## 1. Architectural Position

One tenant-aware application with clear service boundaries. Features share five platform services instead of each building its own messaging, identity and scheduling.

**Architecture principles**

| # | Principle | Implication |
|---|---|---|
| A1 | **Shared platform services over per-feature builds** | Messaging, identity, scheduling, realtime and audit are implemented once and consumed by every module. |
| A2 | **Modular monolith first** | One deployable API, internally separated by module and by service boundary. Extract a service only when a measured need (scale, isolation, ownership) justifies it. |
| A3 | **Tenant isolation is a platform concern** | `business_id` is injected at the middleware layer, not passed by callers. |
| A4 | **Async by default for anything slow** | Webhooks acknowledge in under 500 ms and hand work to the queue. |
| A5 | **Outbox for every send** | A business transaction and its outbound message row are committed together; a separate dispatcher sends. |
| A6 | **No fabricated data** | Unavailable is a first-class value with a reason, not a default. |
| A7 | **Boring, observable, reversible** | Structured logs, dashboards, feature flags, staged rollout, expand/contract migrations. |

---

## 2. Layered Architecture

```mermaid
flowchart TB
    subgraph Clients["Presentation Layer"]
        WEB["Next.js Web App<br/>React · App Shell · Sidebar"]
        SSE["SSE Client<br/>Bubble stream"]
        TRS["Tour Driver<br/>Overlay"]
    end

    subgraph Edge["Edge / Gateway Layer"]
        LB["HTTPS Load Balancer<br/>TLS termination · rate limit"]
        AUTH["Auth Middleware<br/>OIDC · RBAC · business_id injection"]
        WHS["Webhook Ingress<br/>Signature verify · fast ACK"]
    end

    subgraph API["API Layer — FastAPI (Modular Monolith)"]
        direction LR
        subgraph M1M["M1 Customer Genome"]
            CG["History & Repeat Buyers"]
            BB["Bubbles"]
            RSM["Restore Product"]
        end
        subgraph M2M["M2 Creator Commerce"]
            RV["Review"]
            AD["Ads Intelligence & Performance"]
            CFS["Collaboration Finder"]
        end
        subgraph M3M["M3 Agent Workspace"]
            CHT["Chat & FAQ"]
            TRS2["Tour"]
        end
    end

    subgraph Svc["Shared Platform Services"]
        IDC["Identity & Consent"]
        MSG["Messaging Gateway"]
        SCH["Scheduler & Queue"]
        RT["Realtime (SSE)"]
        AUD["Audit Log"]
    end

    subgraph AI["AI Services"]
        ROUT["Router<br/>FAQ → Data → AI → Blocked"]
        PORT["LLM Port<br/>Provider-agnostic · redacted"]
        TOOLS["Read-only Tool Registry"]
    end

    subgraph Ext["External Systems"]
        PROV["Channel Providers<br/>Messenger · WhatsApp · SMS · Email"]
        SRC["Customer · Order · Inventory Source"]
        META["Meta Ad Library /<br/>Marketing API"]
        PROVID["Licensed Ad-Data Provider"]
        LLM["LLM Provider"]
    end

    subgraph Data["Data Layer"]
        PG[("PostgreSQL<br/>Primary + Read Replica")]
        RD[("Redis<br/>Queue · Cache · Pub/Sub")]
        OBJ[("Object Storage<br/>CSV · Screenshots · Exports")]
    end

    WEB --> LB
    SSE --> LB
    LB --> AUTH --> API
    PROV --> WHS --> API

    API --> M1M
    API --> M2M
    API --> M3M

    M1M --> IDC
    M1M --> MSG
    M1M --> SCH
    M2M --> MSG
    M2M --> SCH
    M3M --> ROUT
    M3M --> IDC

    MSG --> PROV
    SRC --> SCH
    AD --> META
    AD --> PROVID
    ROUT --> PORT --> LLM
    PORT --> TOOLS --> PG

    API --> PG
    SCH --> RD
    SCH --> PG
    MSG --> RT
    RT --> RD
    API --> RD
    API --> OBJ
    AUD --> PG
```

---

## 3. Component Catalogue

### 3.1 Shared platform services

| Service | Responsibility | Interface | Owned data |
|---|---|---|---|
| **Identity & Consent** | Messaging identity links, contact permissions, opt-outs, consent records. Used by bubbles, Restore Product and Review. | `IdentityService.resolve(channel, channel_user_id) → Resolution`, `.link()`, `.check_permission()` | `messaging_identity_links`, `contact_permissions`, `review_permissions`, `identity_conflicts` |
| **Messaging Gateway** | Inbound: webhook signature check, idempotent event store. Outbound: channel adapters, send-time eligibility, rate limits, bounded retries, one delivery log for all purposes. | `Gateway.receive(channel, payload, signature)`, `.enqueue(outbound)`, `.dispatch()` | `inbound_message_events`, `outbound_messages`, `delivery_attempts` |
| **Scheduler & Queue** | Delayed jobs (review requests), batch sends (restock), retries, restock detection. | `Scheduler.schedule(type, run_at, payload, idempotency_key)`, `Worker.run()` | `scheduled_jobs`, `job_runs` |
| **Realtime** | Server-sent events per business for `bubble.created`, `bubble.updated`, `bubble.removed`. Clients reconnect and refetch. | `GET /api/realtime/stream`, `Realtime.publish(business_id, event)` | — (Redis pub/sub fan-out) |
| **Audit Log** | Batch approvals, exports, consent changes, identity links, role changes. | `Audit.record(action, target, before, after)` | `audit_log` |

### 3.2 Module components

| Component | Key responsibilities | Depends on |
|---|---|---|
| **Data Adapter** | Polls/pulls customers, orders, inventory; normalises phone/email; maps source status to the qualifying-order rule; stores raw payloads | Source system, Scheduler, PostgreSQL |
| **Identity Resolver** | Applies the resolution ladder; flags conflicts; never auto-merges | Identity & Consent, PostgreSQL |
| **Bubble Engine** | Qualification, upsert, state transitions, live figures, realtime emission | Identity Resolver, PostgreSQL, Realtime |
| **Restock Detector** | Detects unavailable→available transitions; creates restock events and owner notifications; **never sends messages** | Data Adapter, PostgreSQL, Notifications |
| **Batch Composer** | Resolves waiting lists, per-recipient channel selection, eligibility, stock warning, template preview | Identity & Consent, Messaging Gateway, PostgreSQL |
| **Dispatcher** | Claims pending outbound rows, applies rate limits, sends via adapters, records attempts, bounded retries | Messaging Gateway, Redis, PostgreSQL |
| **Review Scheduler** | Creates review requests on verified delivery; computes due times in business tz; cancels ineligible requests | Scheduler, Data Adapter, PostgreSQL |
| **Reply Matcher** | Token → thread → needs-assignment; preserves verbatim text | Messaging Gateway, PostgreSQL |
| **Consent Manager** | Issues consent asks, records the answer, enforces export gating, supports revocation | Identity & Consent, PostgreSQL, Audit Log |
| **Card Builder** | Generates cards from the verbatim reply; enforces the label and the no-platform-UI rule | PostgreSQL |
| **Ad Insight Service** | Tiered source selection (Meta API → licensed provider → manual intake); scoring; evidence; freshness | Meta API, licensed provider, Object Storage, LLM Port |
| **Ranking Engine** | Deterministic objective-aware ranking over stored snapshots | PostgreSQL |
| **Chat Router** | Normalisation, FAQ match, data intent, blocked-intent detection, AI fallback | FAQ registry, PostgreSQL, LLM Port |
| **FAQ Registry** | Entries, aliases, ownership, review dates, staleness flagging | PostgreSQL |
| **Tool Registry** | Static read-only tool allow-list with tenant/role re-check | PostgreSQL |
| **Usage Meter** | Records route, tokens, latency, cost per request | PostgreSQL |
| **Tour Driver** | Step navigation, target resolution, resilient skipping, progress persistence | PostgreSQL |

### 3.3 Channel adapters

| Channel | Transport | Eligibility conditions | Outbound purpose |
|---|---|---|---|
| Email | SMTP / transactional email API | Authenticated sending domain, valid address, unsubscribe link | restock, review_request, review_consent |
| SMS | Regional SMS gateway | Gateway configured, valid mobile number, opt-out honoured | restock, review_request, review_consent |
| Messenger | Meta Graph API | Platform-allowed window / message type valid at send time | restock, review_request, review_consent |
| WhatsApp | WhatsApp Business API | Approved template + recorded opt-in | restock, review_request, review_consent |

All adapters implement one interface: `send(msg) → SendReceipt` and `eligibility(recipient, at) → EligibilityResult`. Channel rules live in exactly one place (OD-05).

**Not a channel:** Collaboration Finder and Influencer Suggestions have no outbound capability. The outbound service rejects `purpose = collaboration` outright (CF-03).

---

## 4. Cross-Cutting Mechanisms

### 4.1 Tenant isolation

```mermaid
flowchart LR
    A[Request] --> B[Auth Middleware<br/>validate token]
    B --> C[Derive business_id + role<br/>from token claims]
    C --> D[Request Context<br/>business_id, role, user_id]
    D --> E[Repository Guard<br/>rejects any query without<br/>business_id predicate]
    E --> F[Data Access]
    C --> G[Cache key<br/>prefixed with business_id]
    C --> H[Realtime channel<br/>business:{id}]
    C --> I[Queue payload<br/>carries business_id]
```

- `business_id` is never read from a request body or query string; a body-supplied `business_id` is rejected.
- Every tenant-scoped table has `business_id NOT NULL` and includes it in its indexes.
- Row-Level Security in PostgreSQL is recommended as defence in depth.
- A cross-tenant test suite attempts reads on every tenant-scoped endpoint; all must return 403/404 with no leakage (RV-T11, Definition of Done).

### 4.2 Idempotency and the outbox pattern

```mermaid
sequenceDiagram
    participant API as API / Request handler
    participant DB as PostgreSQL
    participant W as Dispatcher worker
    participant CH as Channel provider

    API->>DB: BEGIN
    API->>DB: INSERT restock_batches (state=queued)
    API->>DB: INSERT outbound_messages (status=pending, idempotency_key)
    API->>DB: COMMIT
    Note over API,DB: single transaction — no lost sends
    W->>DB: SELECT ... WHERE status='pending' AND next_attempt_at<=now FOR UPDATE SKIP LOCKED
    W->>CH: send(msg)
    CH-->>W: provider_message_id
    W->>DB: UPDATE outbound_messages SET status='sent', provider_message_id, sent_at
    Note over W: duplicate dispatch is safe —<br/>idempotency_key unique index blocks a second row
```

| Level | Key | Table | Effect of a replay |
|---|---|---|---|
| Inbound event | `business_id + provider_event_id` | `inbound_message_events` | Second insert is swallowed → `duplicate: true` |
| Outbound message | sha256(business \| ref \| recipient \| channel) | `outbound_messages` | Unique index rejects → original message retained |
| Review request | `business_id + order_id` | `review_requests` | Second row rejected → one request per order |
| Consent record | `review_request_id` | `review_permissions` | One state per review |
| Scheduled job | `business_id + idempotency_key` | `scheduled_jobs` | One logical job per key |

### 4.3 Realtime (bubble stream)

```mermaid
sequenceDiagram
    participant P as Channel provider
    participant WH as Webhook ingress
    participant Q as Worker / queue
    participant DB as PostgreSQL
    participant RP as Redis pub/sub
    participant SSE as SSE server
    participant CL as Browser client

    P->>WH: webhook
    WH->>WH: verify signature
    WH->>DB: INSERT inbound_message_events
    WH-->>P: 202 Accepted (< 500 ms)
    WH->>Q: enqueue identity_resolution job
    Q->>DB: resolve customer, count qualifying orders
    alt qualified
        Q->>DB: UPSERT customer_bubbles
        Q->>RP: publish bubble.created / bubble.updated
        RP->>SSE: fan out to business:{business_id}
        SSE-->>CL: event: bubble.created
    else not qualified
        Q->>DB: no bubble (CG-T02)
    end
```

- One SSE stream per authenticated business, opened from the app shell so it survives route changes.
- Client behaviour on reconnect: refetch the bubble list (`GET /api/customer-genome/returning-bubbles`) — SSE frames are treated as invalidation signals, not the source of truth.
- No browser push permission is requested (CG-11).

### 4.4 Eligibility engine

Send-time eligibility is a single decision point shared by Restore Product, Review and the Consent flow.

```mermaid
flowchart TD
    A[Outbound candidate] --> B{Purpose allowed for<br/>this channel?}
    B -->|No| S[skipped: channel_ineligible]
    B -->|Yes| C{contact_permissions.eligible?}
    C -->|No| S2[skipped: no_permission]
    C -->|Yes| D{Opted out?}
    D -->|Yes| S3[skipped: opted_out]
    D -->|No| E{Order still valid?<br/>cancelled/returned/refunded}
    E -->|No| S4[skipped: order_invalid]
    E -->|Yes| F{Provider window open?<br/>Messenger / WhatsApp}
    F -->|No| S
    F -->|Yes| G{Valid destination?}
    G -->|No| S5[skipped: invalid_address]
    G -->|Yes| H[✅ eligible — queue send]
```

Evaluated twice: at preview time (so the owner sees the truth) and again at dispatch time (so a consent change between preview and send is respected — RP-08).

### 4.5 AI safety architecture

```mermaid
flowchart TD
    A[User message] --> B[Normalise]
    B --> C{FAQ match}
    C -->|Yes| F1[FAQ answer — zero tokens]
    C -->|No| D{Data intent}
    D -->|Yes| F2[Authorised read-only query]
    D -->|No| E{Write/delete intent}
    E -->|Yes| F3[Blocked — refusal]
    E -->|No| G[AI route]
    G --> H[Redaction layer<br/>strips PII]
    H --> I[Prompt assembly<br/>untrusted content in<br/>delimited DATA blocks]
    I --> J[LLM Port]
    J --> K[Tool registry<br/>read-only allow-list]
    K --> L[Per-call authz:<br/>tenant + role]
    L --> M[Schema-constrained<br/>JSON response]
    M --> N[Validate + redact output]
    N --> O[Usage + cost recorded]
```

**Guarantees**

| Guarantee | Mechanism |
|---|---|
| Ad copy, reviews and customer text cannot change instructions | Untrusted content only ever appears inside clearly delimited data blocks; the system prompt states they are data to analyse |
| No write tools | The tool registry is a static allow-list; no dynamic registration path exists |
| Least data to AI | Redaction layer strips phone, email and full name before the provider call (OD-10) |
| Tenant + role enforced per tool call | Authorisation re-checked inside each tool, not only at the entry point |
| No invented facts | The prompt forbids guessing; missing data is explained; output is schema-validated |
| Cost control | Usage metered per request; per-business caps configurable (OD-10) |

---

## 5. Data Architecture

```mermaid
flowchart LR
    subgraph Primary["PostgreSQL Primary"]
        TEN["Tenant-scoped tables<br/>business_id NOT NULL"]
        LOG["audit_log ⟂"]
        JOB["scheduled_jobs"]
    end

    subgraph Read["Read Replica"]
        RP1["Repeat Buyers list"]
        RP2["Customer history"]
        RP3["Review library"]
        RP4["Ad ranking"]
    end

    subgraph Cache["Redis"]
        QB["Queue: delayed jobs"]
        CB["Cache: hot reads<br/>key = business_id:…"]
        PB["Pub/Sub: bubble events"]
        RTB["Rate limit counters"]
    end

    subgraph Obj["Object Storage"]
        CSV["CSV imports"]
        SHOT["Ad screenshots (Tier 3)"]
        EXP["Export artifacts"]
    end

    API["API + Workers"] --> Primary
    API -->|"read"| Read
    API --> Cache
    Worker["Workers"] --> Cache
    Cache --> API
    Primary -.->|logical replication| Read
```

| Concern | Approach |
|---|---|
| Multi-tenancy | Shared schema, `business_id` discriminator, RLS as defence in depth |
| Read scaling | Read replica for list/report queries; Redis cache for hot endpoints (p95 < 500 ms target) |
| Concurrency | `FOR UPDATE SKIP LOCKED` for dispatcher claims; advisory locks for restock detection transitions |
| Migrations | Expand/contract with Alembic; no destructive change in the same release as the code that stops using the column |
| Backup | Point-in-time recovery on the primary; daily restore rehearsal |
| Retention | Per-entity retention per OD-07; purge jobs for chat, usage and delivery-attempt data |

**Data classification**

| Class | Examples | Handling |
|---|---|---|
| Public | Product names, public ad metadata, public collaborator info | Stored, displayable |
| Internal | Ad insights, snapshots, tour progress | Tenant-scoped |
| Personal | Names, phone numbers, emails, order history | Tenant-scoped, minimised, redacted before AI, access logged |
| Special | Review verbatim text, consent records | Tenant-scoped, immutable where required, consent-gated for export |
| Secret | OAuth tokens, webhook secrets | Encrypted at rest (KMS), never logged, never in exports |

---

## 6. Integration Architecture

| Integration | Direction | Protocol | Auth | Failure behaviour |
|---|---|---|---|---|
| **Customer/Order/Inventory source** | Inbound | Adapter (REST/DB/file) per OD-01 | Provider credentials from the secret store | Backfill + incremental sync with cursors; stale flag surfaced; no fabricated data |
| **Messenger (Meta)** | Bi | Webhook + Graph API | App secret / OAuth token | Signature mismatch → 401; API error → bounded retry |
| **WhatsApp Business** | Bi | Webhook + Cloud API | OAuth token + template approval | Template rejected → skipped with reason; window closed → ineligible |
| **SMS gateway** | Outbound | HTTP | API key | Provider 429 → retry after delay, bounded; failure → row `failed` |
| **Email provider** | Outbound | HTTPS API | API key | Transient error → retry; permanent (invalid address) → `failed` |
| **Meta Ad Library** | Outbound | Graph API | App token | Not covered → fall back to Tier 2, then Tier 3; never scrape |
| **Licensed ad provider** | Outbound | HTTPS | Licence key | Unavailable → Tier 3 |
| **LLM provider** | Outbound | HTTPS | API key | Down → chat degrades to FAQ + DATA with an explicit notice |
| **Identity provider** | Inbound | OIDC | — | Down → existing sessions continue until token expiry |

**Meta access lead time** — reading ad-account data requires Meta app review and business verification. This is started in Phase 0 because it routinely takes longer than the build itself.

---

## 7. Deployment Architecture

```mermaid
flowchart TB
    subgraph Edge["Edge"]
        CDN["CDN / Static assets"]
        LB["Load balancer<br/>TLS · WAF · rate limit"]
    end

    subgraph App["Application Tier"]
        API1["API pod 1"]
        API2["API pod 2"]
        WK1["Worker pod 1<br/>scheduler + dispatcher"]
        WK2["Worker pod 2"]
        SSE["SSE service<br/>(stateless, sticky not required)"]
    end

    subgraph Data["Data Tier"]
        PGPRIM[("PostgreSQL primary")]
        PGREP[("Read replica")]
        REDIS[("Redis cluster<br/>Sentinel")]
        S3[("Object storage")]
    end

    subgraph Obs["Observability"]
        LOGS["Log aggregation"]
        MET["Metrics + dashboards"]
        TRACE["Distributed tracing"]
        ALERT["Alerting"]
    end

    CDN --> LB --> API1 & API2
    LB --> SSE
    API1 & API2 --> PGPRIM
    API1 & API2 --> PGREP
    API1 & API2 --> REDIS
    API1 & API2 --> S3
    WK1 & WK2 --> PGPRIM
    WK1 & WK2 --> REDIS
    WK1 & WK2 --> S3
    API1 & API2 --> LOGS & MET & TRACE
    WK1 & WK2 --> LOGS & MET & TRACE
    MET --> ALERT
    TRACE --> ALERT
```

| Environment | Purpose | Data |
|---|---|---|
| `local` | Development via docker-compose (Postgres, Redis, mailhog) | Seeded fixtures |
| `ci` | Automated tests | Ephemeral per pipeline |
| `staging` | Pre-release verification and owner acceptance | Sanitised production-like data |
| `production` | Live | Real tenant data, encrypted, audited |

**Release strategy**

1. Code behind a per-tenant feature flag.
2. Migrations applied expand-only before the code ships.
3. Deploy → smoke tests → internal tenant → 5% → 25% → 100%.
4. Automatic rollback on error-rate breach.
5. Contract: backfill → switch reads → remove old path in a later release.

**CI/CD pipeline**

```
lint → unit → integration (docker-compose services)
      → migration up/down check → contract tests
      → security tests (tenant isolation, IDOR, signature)
      → build + scan images → deploy staging
      → smoke + E2E → owner acceptance → production
```

---

## 8. Availability, Performance and Capacity

| Target | Value | Mechanism |
|---|---|---|
| Bubble latency | ≤ 5 s p95 from webhook receipt | Fast ACK, queue hop, SSE push; the SSE frame is the invalidation signal |
| Read latency | < 500 ms p95 | Indexes, read replica, Redis cache |
| Availability | 99.5% | Multi-AZ API pods, DB failover, Redis Sentinel, worker autoscaling, graceful degradation of AI and ads features |
| Webhook processing | At-least-once with idempotent handling | Unique event IDs; duplicates absorbed |
| Throughput assumption | Peak burst of inbound messages and batch sends | Horizontal API scaling, batched dispatcher claims, per-channel rate limits |
| Chat concurrency | Bursty, low volume | Stateless API; the LLM path is the only cost-bearing route and is capped |

---

## 9. Observability Architecture

```mermaid
flowchart LR
    API["API + Workers"] -->|"JSON logs<br/>request_id · business_id<br/>user_id · route · latency"| LOGS["Log aggregation"]
    API -->|"spans"| TRACE["Tracing"]
    API -->|"counters & histograms"| MET["Metrics"]
    LOGS --> DASH["Dashboards"]
    MET --> DASH
    TRACE --> DASH
    DASH --> ALERT["Alerts & paging"]
    API --> AUDITDB[("audit_log")]
```

| Signal | Content |
|---|---|
| **Logs** | JSON with `request_id`, `business_id`, `user_id`, `route`, `latency_ms`, `outcome`. No secrets, no PII. |
| **Traces** | API → queue worker → channel adapter → provider, with the correlation id propagated through the job payload. |
| **Metrics** | Webhook receipt rate; bubble latency p95; qualification rate; outbound per channel; delivery success/failure by error code; retry counts; restock detection lag; review due/sent rate; reply match rate; consent distribution; chat route mix; AI tokens and cost per tenant; SSE connections. |
| **Alerts** | Delivery failure rate breach; queue age breach; bubble p95 > 5 s; error rate > 2%; AI cost anomaly; webhook signature failure spike. |
| **Dashboards** | Delivery outcomes per channel; AI cost per tenant per day; funnel inbound → qualified → bubble → linked; funnel due → sent → replied → consented → exported. |
| **Audit** | Immutable trail surfaced to Owner/Admin: batch approvals, exports, consent changes, identity links, role changes. |

---

## 10. Security Architecture

| Layer | Control |
|---|---|
| **Transport** | TLS 1.2+ everywhere, HSTS, internal traffic encrypted |
| **Edge** | WAF, IP and tenant rate limiting, request size caps |
| **Authentication** | OIDC/OAuth2, short-lived access tokens, hashed refresh tokens |
| **Authorisation** | RBAC per endpoint from the roles matrix; Owner-only on restock approval, ad connection, review export, FAQ/tour management |
| **Tenant isolation** | `business_id` injection at the middleware layer, repository guard, RLS, mandatory cross-tenant tests |
| **Webhook security** | HMAC-SHA256 constant-time comparison, timestamp replay window, secret rotation |
| **Secret management** | Managed secret store; no secrets in code, images, logs or client bundles |
| **Token protection** | OAuth access tokens encrypted at rest with KMS envelope encryption; rotated; never logged |
| **Application security** | Parameterised queries only; no raw HTML rendering of customer text or ad copy; sanitised rich text |
| **AI security** | Untrusted content isolated in delimited blocks; schema-constrained output; read-only tool allow-list; PII redaction |
| **Auditability** | Immutable audit log with actor, timestamp, target and before/after hash |
| **Supply chain** | Locked dependencies, automated scanning, signed and digest-pinned images |

---

## 11. Feature-to-Service Mapping

| Feature | Identity & Consent | Messaging Gateway | Scheduler & Queue | Realtime | Audit Log | LLM |
|---|---|---|---|---|---|---|
| Repeat Buyers & History | ○ | | ● | | | |
| Returning Customer Bubbles | ● | ● | ● | ● | ○ | |
| Restore Product | ● | ● | ● | ○ | ● | |
| Review | ● | ● | ● | | ● | |
| Meta Ads Intelligence | | | ● | | ○ | ● (scoring) |
| My Ads Performance | | | ● | | ○ | |
| Collaboration Finder | | | ● | | | |
| Smart Chat Assistant | ● | | | | ● | ● |
| Website Tour | | | | | | |

● primary owner  ○ secondary / read

---

## 12. Evolution Path

The system is a modular monolith by design. Extraction triggers, when met:

| Extract when | Candidate | Rationale |
|---|---|---|
| Sustained queue load justifies independent scaling, or a provider requires a separate deployment | Messaging Gateway | Outbound throughput and provider-specific concerns are self-contained |
| External partners need direct ad-data consumption, or ad analysis becomes compute-heavy | Ads Insight Service | Heavy scraping-free ingestion and scoring workloads |
| Tenant volume or isolation requirements grow | Tenant-scoped data plane | Sharding by `business_id` with the same repository contract |

Rules for extraction: the extracted service keeps the same interface and owns its tables exclusively; the API layer calls it over a network boundary with the same auth model; no module may reach into another module's tables.

---

## 13. Architecture Decisions

| # | Decision | Rationale | Status |
|---|---|---|---|
| AD-1 | Modular monolith over microservices | One deployable with internal boundaries delivers faster at this scale; extraction paths are defined (Section 12) | RECOMMENDED |
| AD-2 | Shared platform services over per-feature messaging/identity/scheduling | Avoids divergent behaviour for consent, idempotency and delivery | APPROVED |
| AD-3 | SSE over WebSockets for realtime | One-way push only; simpler reconnection and proxy behaviour | RECOMMENDED |
| AD-4 | Outbox pattern for every outbound send | Business state and send intent commit together; no lost or phantom sends | APPROVED |
| AD-5 | PostgreSQL as the primary store | Relational integrity and unique constraints are load-bearing for idempotency and consent | APPROVED |
| AD-6 | Ad intelligence limited to Tier 1/2/3 legal sources | Never bypass platform restrictions by scraping | APPROVED |
| AD-7 | FAQ and data routes never touch the LLM | Zero cost for common questions; the model is reserved for genuinely unique ones | APPROVED |
| AD-8 | Tool registry is a static read-only allow-list | Structural guarantee that the agent cannot mutate data | APPROVED |
| AD-9 | Shared schema with `business_id` discriminator | Simple to operate; RLS and repository guard provide isolation | RECOMMENDED (OD-03) |
| AD-10 | Provider-agnostic `LLMPort` | Keeps OD-10 (provider, model, cost caps, redaction) a configuration change | RECOMMENDED |

---

## 14. Traceability

| Requirement | Architecture section |
|---|---|
| CG-05…CG-11 Bubbles | §2 Realtime, §4.3 Realtime mechanism |
| CG-03 Identity matching | §4.1 Tenant isolation, §3.2 Identity Resolver |
| RP-06…RP-08 Channel routing and idempotency | §3.3 Channel adapters, §4.2 Outbox, §4.4 Eligibility |
| RP-04 Restock detection | §3.2 Restock Detector |
| RV-02…RV-07 Review pipeline | §3.2 Review Scheduler, Reply Matcher |
| RV-09…RV-12 Consent and cards | §3.2 Consent Manager, Card Builder |
| MI-01…MI-05 Ad intelligence | §3.2 Ad Insight Service, §6 Integration tiers |
| MP-01…MP-04 Own ads | §3.2 Ranking Engine, §3.2 Ad Insight Service |
| CF-03 No outreach | §3.3 Channel adapters |
| AW-04…AW-08 Chat routing and safety | §4.5 AI safety architecture |
| AW-10…AW-11 Tour | §3.2 Tour Driver |
| NFR performance/reliability | §8 Availability, Performance and Capacity |
| NFR observability | §9 Observability Architecture |
| NFR security | §10 Security Architecture |
| Tenant isolation | §4.1 |
