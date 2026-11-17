# Product Requirements Document (PRD)

**Project:** Xenovarients — Customer Genome · Creator Commerce · Agent Workspace
**Version:** 1.0 (derived from Master Project Documentation v3.0, 16 November 2026)
**Status:** Module scope approved. Items tagged **RECOMMENDED** or **OPEN** need owner confirmation before build.
**Audience:** Product owner, developers, architects, QA, marketing stakeholders

---

## 1. Document Purpose

This PRD captures *what* the product must do and *why*. Technical design (service boundaries, schemas, endpoints, infrastructure) is specified in `TRD.md`, `ERD.md`, `USER_FLOW.md` and `ARCHITECTURE.md`.

Source of truth for requirement IDs remains the Master Project Documentation (`Project.md`). IDs are reproduced here unchanged so the two documents stay traceable.

### How to read this document

| Tag | Meaning |
|---|---|
| **APPROVED** | Owner-approved scope. Implement as written. |
| **RECOMMENDED** | Design proposal made in v3.0 to close a gap. Treat as the default unless the owner changes it. |
| **OPEN** | Undecided. Tracked in the Decision Register (Section 10). |

---

## 2. Product Vision

The platform helps a business **know its customers**, **market with evidence** and **get unstuck quickly**. It is organised as three modules that share one dashboard, one customer identity layer and one messaging layer.

### 2.1 Module map

| Module | Purpose | Features | Requirement IDs |
|---|---|---|---|
| **M1 Customer Genome** | Turns order history into customer understanding. Surfaces returning buyers the moment they message, and wins back customers waiting for out-of-stock products. | Repeat Buyers & Customer History; Returning Customer Bubbles; Restore Product | CG-01…CG-11, RP-01…RP-10 |
| **M2 Creator Commerce** | Collects customer reviews, studies competitor ads, tracks own ads and finds collaborators. | Review; Meta Ads Intelligence; My Ads Performance; Collaboration Finder; Influencer Suggestions (optional) | RV-01…RV-13, MI-01…MI-05, MP-01…MP-04, CF-01…CF-03, IF-01…IF-02 |
| **M3 Agent Workspace** | Answers common questions instantly at zero AI cost, uses AI only for unique questions, and guides new users with a tour. | Smart Chat Assistant; Website Tour | AW-01…AW-11 |

### 2.2 Product principles

| # | Principle | Consequence in requirements |
|---|---|---|
| P1 | **No fabricated data** | Unknown values display as unavailable, never as guesses (CG-07, MI-04, MP-02, AW-06). |
| P2 | **Human sends, system prepares** | No outbound message leaves the system without an explicit human confirmation (RP-07, RV-09). |
| P3 | **AI is a last resort** | FAQ and simple data questions never call an LLM (AW-04, AW-05). |
| P4 | **Consent is a gate, not a flag** | Marketing use of customer content requires live consent; revocation blocks future exports (RV-09, RV-12). |
| P5 | **Tenant isolation is absolute** | Every record carries `business_id`; data never crosses tenants (RV-13). |
| P6 | **Least data to AI** | The LLM receives the minimum fields needed, with personal data redacted (OD-10). |
| P7 | **Untrusted input stays untrusted** | Ad copy, reviews and customer text can never change instructions (MI-05, AW-06). |

---

## 3. Scope

### 3.1 In scope — APPROVED

- Customer history, Repeat Buyers list
- Returning Customer Bubbles
- Restore Product with owner-confirmed batches
- Review requests, reply capture, consent and marketing cards
- Competitor ad intelligence, own-ad performance, collaboration finder
- FAQ chat, AI chat for unique questions, website tour

### 3.2 Out of scope

- Publishing ads or editing budgets
- Sending partner or influencer outreach
- AI deleting or editing customer records
- Image analysis in chat (future)
- Browser push notifications
- Using an LLM to answer FAQ prompts

### 3.3 Optional

**Influencer Suggestions (IF)** is optional and never blocks a release. Items not yet decided are listed in the Decision Register (Section 10).

---

## 4. Roles and Permissions

Three roles replace the mixed use of "Admin", "Business Owner" and "authorized staff" in earlier versions.

| Capability | Owner | Admin | Staff |
|---|---|---|---|
| View bubbles, customer history, Repeat Buyers | Yes | Yes | Yes |
| Link a messaging identity to a customer | Yes | Yes | Yes |
| Add a customer to a product waiting list | Yes | Yes | Yes |
| Approve a restock notification batch | Yes | No | No |
| Configure review delay, channels and templates | Yes | Yes | No |
| Export review marketing cards | Yes | Yes | No |
| Connect ad accounts | Yes | No | No |
| Manage FAQ entries and tour steps | Yes | Yes | No |
| Use the chat assistant (data access follows role) | Yes | Yes | Yes |

---

## 5. Glossary

| Term | Meaning |
|---|---|
| **Tenant / Business** | One customer organisation. Every record carries a `business_id`; data never crosses tenants. |
| **Qualifying order** | An order that counts toward history and totals. Default: paid or completed; cancelled and fully refunded orders excluded; partial refunds counted net. See OD-02. |
| **Returning Customer** | A customer with at least one qualifying order **before** the current inbound message. Drives the bubble. |
| **Repeat Buyer** | A customer with two or more qualifying orders. Drives the Repeat Buyers list. |
| **Bubble** | A small floating, Messenger-style indicator showing a returning customer has just messaged. |
| **Restock event** | A product or variant changing from unavailable to available in the authoritative inventory source. |
| **Messaging Gateway** | Shared service that receives inbound messages and sends outbound messages with eligibility checks, idempotency and delivery logs. |
| **Idempotency key** | A unique key that guarantees a repeated event or send request produces one outcome. |

---

# MODULE 1 — Customer Genome

*Know your buyers. Recognise them instantly. Win them back.*

Customer Genome reads customer and order data from an independent source, builds a reliable history per customer and uses it in two moments that matter: **when a known customer messages** and **when an out-of-stock product returns**.

| Feature | IDs | Sidebar position |
|---|---|---|
| Repeat Buyers & Customer History | CG-01 to CG-04 | 1 |
| Returning Customer Bubbles | CG-05 to CG-11 | 2 (floating, all pages) |
| Restore Product | RP-01 to RP-10 | 4th item under Customer Genome |

## 6. Repeat Buyers & Customer History

| ID | Requirement | Expected behavior |
|---|---|---|
| **CG-01** | **Repeat Buyers list** | Lists customers with two or more qualifying orders: name, contact, order count, last purchase date, new-order indicator and a View History action. |
| **CG-02** | **Customer history** | A profile with a chronological order timeline (date, products, quantity, totals, status) and filters by date and product. |
| **CG-03** | **Identity matching** | Match by customer ID, normalised phone (E.164, +880…), normalised email or a verified messaging link. A conflict is never auto-merged; it is flagged for staff review. |
| **CG-04** | **Independent data source** | Customer and order data arrive through an adapter from a source independent of this app. Integration method: OD-01 **OPEN**. |

### 6.1 Minimum data contract

| Field | Type | Notes |
|---|---|---|
| `customer_id` | string | Stable identifier from the source |
| `name`, `phone`, `email` | string | Phone and email normalised on ingest |
| `order_id`, `ordered_at` | string, datetime | Business time zone preserved |
| `status` | enum | Mapped to the qualifying-order rule (OD-02) |
| `items[]` | list | Product ID, name, quantity, line total |
| `total_amount`, `currency` | decimal, string | Net of refunds where applicable |

> **DECISION — Two terms, two rules**
> **Returning Customer** (one or more prior orders) drives the bubble. **Repeat Buyer** (two or more orders) drives the list. A customer with exactly one prior order gets a bubble but is not in the Repeat Buyers list. Confirm this intent in OD-02.

---

## 7. Returning Customer Bubbles

When a customer writes to the business, the dashboard shows a small floating bubble. Expanding it tells staff, at a glance, that this person has bought before and how much.

| ID | Requirement | Expected behavior |
|---|---|---|
| **CG-05** | **Message trigger** | Only a new inbound customer message on a connected channel creates or updates a bubble. Orders, visits and logins never do. |
| **CG-06** | **Qualification** | A bubble is created only when the resolved customer has at least one qualifying order before the message. |
| **CG-07** | **Bubble and card** | Floating Messenger-style indicator with initials. Expanded card shows a **Returning Customer** label, name, total previous orders, total purchase amount (with "as of" time), last purchase date and a link to history. |
| **CG-08** | **Deduplication** | Replayed webhooks or repeated messages update the existing bubble. One bubble per customer and conversation. |
| **CG-09** | **Live figures** | After a qualifying order is recorded, counts and spend refresh from the authoritative history. |
| **CG-10** | **Safe identity** | No confident match: no "Returning Customer" label and no data from any other customer. Staff are offered **Link customer**. |
| **CG-11** | **In-app only** | Bubbles work without browser push permission. Notifications are in-app only. |

### 7.1 How a message is tied to a customer

| Method | Channels | Reliability | Notes |
|---|---|---|---|
| **Verified link (`messaging_identity_links`)** | All | High | Primary lookup once a link exists. |
| **Normalised phone number** | WhatsApp, SMS | High | The platform supplies the number, so matching is automatic. |
| **Email address** | Email | High | Automatic match. |
| **Staff Link customer action, or customer shares their phone in chat** | Messenger | High after confirm | Messenger exposes only a page-scoped ID, so the first link must be created by staff or by the customer. |
| **Display name** | None | Never used | Names are not unique and must never drive a match. |

> **WATCH OUT — Why this section exists**
> Without a linking path, Messenger messages could never be tied to an order history and the bubble would almost never appear. Build WhatsApp, SMS and Email matching first; add Messenger once **Link customer** is in place.

> **DECISION — Where bubbles appear**
> Bubbles render in the dashboard shell on every page. Replies stay in each platform's own inbox. A native inbox is out of scope for V1.
> Bubble states: **New**, **Seen**, **Dismissed**. A new inbound message from a dismissed customer re-opens the bubble. Final persistence rules: OD-04.

### 7.2 Acceptance tests — Customer Genome

| Test | Scenario and expected result |
|---|---|
| **CG-T01** | A linked returning customer messages. Exactly one bubble appears; the card shows the correct order count and total. |
| **CG-T02** | A first-time buyer messages. No bubble and no "Returning Customer" label. |
| **CG-T03** | Identity is unlinked or conflicting. No label, no other customer's data, **Link customer** offered. |
| **CG-T04** | The same webhook arrives twice, or three messages arrive. Still one bubble; last activity updates. |
| **CG-T05** | Two returning customers message. Two bubbles, each with correct figures. |
| **CG-T06** | A new qualifying order is recorded. The card refreshes. |
| **CG-T07** | Browser notifications blocked. Bubbles still work. |
| **CG-T08** | A customer with one order gets a bubble but is absent from Repeat Buyers. At two orders they appear in the list. |

---

## 8. Restore Product

When an out-of-stock product returns, the owner can invite the customers who asked for it. The system prepares everything; **the owner decides when to send**.

> **RULE — No automatic sending**
> A restock event only notifies the owner. Messages leave the system only after an explicit owner confirmation of one batch.

| ID | Requirement | Expected behavior |
|---|---|---|
| **RP-01** | **Menu placement** | Restore Product is the fourth item under Customer Genome. |
| **RP-02** | **Interest capture** | Staff record interest with **Add to waiting list** (from a customer profile, a bubble or a product page). Optional CSV import. Stored: customer, contact, product and variant, request date, optional quantity. |
| **RP-03** | **Waiting lists** | Grouped by product and variant. Variants are never mixed. |
| **RP-04** | **Restock detection** | Stock moving from zero to available in the authoritative inventory source creates a `restock_event` and a dashboard notification. |
| **RP-05** | **Message template** | Merge fields: customer name, request date, product name, business name. The owner previews before sending. |
| **RP-06** | **Channels** | Email, SMS, Messenger and WhatsApp through the Messaging Gateway, only when connected, authorised and eligible. |
| **RP-07** | **Owner-confirmed batch** | Preview shows recipients, channel per recipient and message. One confirmation queues the batch. |
| **RP-08** | **Consent and duplicates** | Eligibility is re-checked at send time. Idempotency key: business + restock event + interest + channel. |
| **RP-09** | **Stock warning** | Warn when available stock is lower than waiting demand. The message must not promise reservation. |
| **RP-10** | **Delivery history** | Per recipient: pending, sent, delivered (if observable), failed or skipped with reason. Retries are bounded. |

### 8.1 Channel routing

| Channel | Default role | Conditions |
|---|---|---|
| **Email** | Default | Authenticated sender domain, valid address, unsubscribe link. |
| **SMS** | Default | Gateway configured, valid mobile number, opt-out honoured. |
| **Messenger** | Conditional | Only inside the window or message type the platform allows at send time. |
| **WhatsApp** | Conditional | Approved template and recorded opt-in. |

> **WATCH OUT — Why channels are conditional**
> Restock and review messages usually go out days after the last chat, which is typically outside Messenger and WhatsApp's short free-reply windows. The Gateway therefore routes by **eligibility at send time**. Verify the current Meta and SMS rules before build (OD-05).

### 8.2 Sample message

```
Hi {customer_name},

You asked us about {product_name} on {request_date}. Good news: it is back in stock at {business_name}. Reply or visit us soon, as stock may be limited.
```

### 8.3 Acceptance tests — Restore Product

| Test | Scenario and expected result |
|---|---|
| **RP-T01** | Staff add a customer to a waiting list. The interest saves against the correct product and variant. |
| **RP-T02** | Stock goes from 0 to available. A restock event and owner notification appear. No message is sent. |
| **RP-T03** | The owner previews a batch. Recipients, channels and text are correct and match the waiting list. |
| **RP-T04** | The owner confirms once. Only eligible recipients are queued. |
| **RP-T05** | Confirm is submitted twice. Each recipient still gets one message per channel. |
| **RP-T06** | A recipient has opted out or is ineligible on a channel. They are skipped with a visible reason. |
| **RP-T07** | Stock is below waiting demand. A warning shows and the message makes no reservation promise. |
| **RP-T08** | A send fails. Status shows failed; retries stay within the limit; other recipients are unaffected. |

---

# MODULE 2 — Creator Commerce

*Collect proof. Study the market. Spend ad money wisely.*

Creator Commerce supports marketing with evidence: real customer feedback, competitor creative, the business's own ad results and potential collaborators.

| Feature | IDs | Sidebar position |
|---|---|---|
| Review | RV-01 to RV-13 | 1 |
| Meta Ads Intelligence | MI-01 to MI-05 | 2 |
| My Ads Performance | MP-01 to MP-04 | 3 |
| Collaboration Finder | CF-01 to CF-03 | 4 |
| Influencer Suggestions (optional) | IF-01 to IF-02 | 5 |

## 9. Review

Review turns delivered orders into authentic customer feedback and, with the customer's permission, into marketing cards. The system sends the request, captures the reply, asks for permission and keeps the customer's original words untouched.

| ID | Requirement | Expected behavior |
|---|---|---|
| **RV-01** | **Menu placement** | Review is the first item in Creator Commerce. |
| **RV-02** | **Trigger** | Only a verified delivery confirmation schedules a request. No confirmation, no request. |
| **RV-03** | **Delay and send window** | Business picks 3 or 4 days (default 3) after confirmed delivery, in the business time zone. Requests are sent inside a configured window (default 09:00 to 20:00). |
| **RV-04** | **Eligibility at send time** | Re-check: order not cancelled, returned or refunded; contact permission; channel eligibility; no opt-out. |
| **RV-05** | **One request per order** | One request lists the delivered products. A repeated delivery event never creates a second request. The owner can tag a reply to a specific product. |
| **RV-06** | **Request message** | Template with customer, product(s) and business name, plus a reference token for matching the reply. |
| **RV-07** | **Reply capture** | Replies are matched by token or thread within a reply window (default 14 days). An ambiguous reply goes to **Needs assignment** instead of attaching automatically. |
| **RV-08** | **Original preserved** | Verbatim text with message ID, timestamp, channel, customer, order and product. Immutable. Positive, neutral and negative replies are all kept. |
| **RV-09** | **Publication consent** | After a reply, the customer is asked once: **Yes**, **Anonymous only** or **No**. State per review: pending, approved, anonymous, declined, revoked. |
| **RV-10** | **Marketing card** | Generated from the original words, labelled "Customer review". It must not imitate Messenger or WhatsApp interfaces or claim to be a genuine screenshot. |
| **RV-11** | **Review library** | Browse and filter by product, date, customer and consent state. |
| **RV-12** | **Consent-gated export** | Export only with current consent. Identity fields hidden unless permitted. Revocation blocks future exports. |
| **RV-13** | **Isolation** | Tenant-scoped data. Missing delivery, customer or product data shows as unresolved and is never invented. |

> **NOTE — Delivery channel**
> Review requests use the same Messaging Gateway rules as Restore Product (Section 8.1). Email and SMS are the default; Messenger and WhatsApp are used only when eligible.

### 9.1 Acceptance tests — Review

| Test | Scenario and expected result |
|---|---|
| **RV-T01** | Delivery confirmed with a 3-day delay. One request is due at +3 days, inside the send window. |
| **RV-T02** | No confirmed delivery. No request is scheduled. |
| **RV-T03** | Delay set to 4 days. The request is due at +4 days. |
| **RV-T04** | The same delivery event arrives twice. Only one request exists. |
| **RV-T05** | The order is returned or refunded before the due time. The request is cancelled with a visible reason. |
| **RV-T06** | The customer has opted out or the channel is ineligible. Nothing is sent; the reason is visible. |
| **RV-T07** | The customer replies. The verbatim text attaches to the right order. An ambiguous reply lands in Needs assignment. |
| **RV-T08** | Consent answered Yes, Anonymous and No. States and export behaviour match each answer. |
| **RV-T09** | A card is generated. Its words equal the original, it carries the label, and it does not imitate platform UI. |
| **RV-T10** | Consent is revoked. Further export is blocked. |
| **RV-T11** | A user from another business requests the review. Access is denied without revealing that it exists. |

---

## 10. Meta Ads Intelligence

The owner enters a keyword, product category or competitor theme. The system finds relevant ads, ranks the **Top 5** by AI-assessed relevance and creative quality, shows what is observable and suggests original creative directions.

> **RISK — Highest delivery risk: data access**
> Meta's Ad Library API is largely limited to political and issue ads and to ads shown in certain regions. Commercial ads in Bangladesh may not be available through the official API. Confirm access in Phase 0 before any build commitment. Never bypass platform restrictions by scraping.

### 10.1 Data access tiers

| Tier | Source | Condition |
|---|---|---|
| 1 | Official Meta Ad Library API | Use if the target country and ad type are covered. |
| 2 | Licensed third-party ad-data provider | Use if Tier 1 is not available and terms permit. |
| 3 | Manual intake | User pastes ad links or uploads screenshots; analysis covers only supplied items. |

| ID | Requirement | Expected behavior |
|---|---|---|
| **MI-01** | **Search input** | Keyword, country (default Bangladesh), product category; optional language and price segment. |
| **MI-02** | **Top 5 result** | Per ad: advertiser, ad URL, creative type, visible copy and hook, CTA, overlay text, visible price or offer, and the reasons for its rank. |
| **MI-03** | **Ranking transparency** | Ranking is labelled as AI relevance and creative quality. It never implies sales, revenue or ROAS. |
| **MI-04** | **No invented data** | Unavailable fields show "Not visible" or "Not available". |
| **MI-05** | **Original suggestions** | Script, offer and CTA ideas that are inspired by patterns, not copies of competitor creative. |

> **NOTE — Suggested scoring (editable)**
> Relevance 40, message clarity 25, offer readability 20, CTA strength 15. Each score shows its evidence and the freshness of the data. Ad copy is untrusted input and is never executed as instructions.

| Test | Scenario and expected result |
|---|---|
| **MI-T01** | A keyword search returns five ads ordered by score, each with visible fields and reasons. |
| **MI-T02** | An ad without a visible price shows "Not visible"; no value is invented. |

---

## 11. My Ads Performance

After the owner connects a Meta ad account, the system shows read-only performance and ranks the business's own ads using rules that match each campaign objective.

| ID | Requirement | Expected behavior |
|---|---|---|
| **MP-01** | **Secure connection** | OAuth connection, account selection, permission check. Read-only. No publishing or budget edits. |
| **MP-02** | **Metrics** | Spend, impressions, reach, CTR, CPC, cost per result, conversions, CPA, ROAS where available; otherwise "N/A, tracking not available". |
| **MP-03** | **Freshness** | Always show last-synced time and warn when data is stale. |
| **MP-04** | **Objective-aware ranking** | Deterministic rules from the stored snapshot. Objectives are never mixed in one ranking. |

| Objective | Ranking order | Guard |
|---|---|---|
| Sales | ROAS, then CPA, then conversions | Minimum spend threshold |
| Traffic | CTR, then CPC | Minimum impressions |
| Leads | Cost per lead, then lead volume | Minimum lead count |

> **WATCH OUT — Lead time**
> Reading ad-account data needs Meta app review and business verification. Start these early; they can take longer than the build.

| Test | Scenario and expected result |
|---|---|
| **MP-T01** | A 7-day filter updates every metric and the last-synced time. |
| **MP-T02** | Conversion tracking is missing. ROAS and CPA show N/A; objective ranking stays valid. |

---

## 12. Collaboration Finder

| ID | Requirement | Expected behavior |
|---|---|---|
| **CF-01** | **Suggestions** | Suggest potential collaborators by category, product type, audience and geography from a legitimate data source. |
| **CF-02** | **Result fields** | Name, platform, niche, location, audience or follower metric if available, contact route if public. |
| **CF-03** | **No outreach** | The system never contacts anyone on the owner's behalf. |

## 13. Influencer Suggestions (optional)

| ID | Requirement | Expected behavior |
|---|---|---|
| **IF-01** | **Niche view** | Bangladesh-relevant influencers by niche with available follower metrics, marked **Unverified** until confirmed. |
| **IF-02** | **Not a blocker** | If disabled or unavailable, every other Creator Commerce feature works unchanged. |

| Test | Scenario and expected result |
|---|---|
| **CF-T01** | A suggestion shows category match, available fields and no outreach action. |
| **IF-T01** | With Influencer Suggestions disabled, all other features remain fully usable. |

---

# MODULE 3 — Agent Workspace

*Instant answers. AI only when needed. A guided first day.*

Agent Workspace gives users quick help inside the product. It has two parts: a **Smart Chat Assistant** (full page and floating launcher) and a **Website Tour**. Common questions are answered without any AI call; the model is used only for genuinely unique questions.

| Feature | IDs | Where it lives |
|---|---|---|
| Smart Chat Assistant | AW-01 to AW-09 | Sidebar page and floating launcher |
| Website Tour | AW-10 to AW-11 | Overlay on every main page |

## 14. Smart Chat Assistant

| ID | Requirement | Expected behavior |
|---|---|---|
| **AW-01** | **Full chat page** | A dedicated Agent Workspace entry in the sidebar. |
| **AW-02** | **Floating launcher** | Available on all authenticated pages; the current page state is preserved. |
| **AW-03** | **Pre-built FAQ prompts** | Selecting a prompt returns a fixed answer and, where useful, a link to the relevant screen. |
| **AW-04** | **No tokens for FAQ** | A FAQ match never calls the LLM; usage records zero tokens. |
| **AW-05** | **Deterministic data answers** | Simple questions such as "how many active ads do I have?" use authorised queries, not the LLM. |
| **AW-06** | **AI for unique questions** | Read-only, allow-listed tools. Explains missing data. Never invents counts, rankings or customer facts. |
| **AW-07** | **Authorisation** | Tenant and role checked on every tool call. |
| **AW-08** | **Usage monitoring** | Per request: ID, route (faq, data or ai), tokens, latency, estimated cost. |
| **AW-09** | **Images unsupported in V1** | A clear message states that image analysis is a future feature. |

### 14.1 Matching rules

| Rule | Definition |
|---|---|
| **Normalisation** | Lower-case, strip punctuation and extra spaces, normalise Bangla Unicode forms and common Banglish spellings before matching. |
| **Matching** | Exact FAQ ID first, then alias lists. Below the confidence threshold the message moves on to the next route. |
| **Ownership** | Each FAQ has an owner and a review date. Editors are Owner and Admin (OD-09). |
| **Response shape** | `answer`, `answer_type` (faq, data, ai), `references`, `data_as_of`, `usage`. |

### 14.2 Routing examples

| User asks | Route | Result |
|---|---|---|
| "How do I use Review?" (FAQ prompt) | FAQ | Fixed answer plus link; zero tokens. |
| "How many active ads do I have?" | Data | Authorised query; count with "as of" time. |
| "Which of my ads should I pause and why?" | AI | Read-only tools; recommendation with evidence; no changes made. |
| "Delete this customer." | Blocked | Clear refusal; no write tools exist. |

> **RISK — AI safety rules**
> Ad copy, reviews and customer text are **untrusted input** and cannot change instructions.
> The tool registry has no write actions: no order edits, publishing, budget changes, outreach or deletions.
> Customer personal data is minimised or redacted before it reaches the LLM provider (OD-10).

### 14.3 Acceptance tests — Agent Workspace

| Test | Scenario and expected result |
|---|---|
| **AW-T01** | A pre-built FAQ is selected. Fixed answer returns; the usage log shows zero tokens. |
| **AW-T02** | An alias, Bangla or Banglish variant of a FAQ matches the same answer without an LLM call. |
| **AW-T03** | A simple metric question uses the data handler and states its data time. |
| **AW-T04** | A unique question reaches the AI route with read-only tools only. |
| **AW-T05** | A prompt injected inside ad copy is ignored; no tool outside the allow-list runs. |
| **AW-T06** | A Staff user cannot retrieve data outside their role or another tenant's data. |
| **AW-T07** | An image is attached. The user sees the "future feature" message. |
| **AW-T08** | The floating chat opens on any page and returns the user to the same page state. |

---

## 15. Website Tour

| ID | Requirement | Expected behavior |
|---|---|---|
| **AW-10** | **Predefined tour** | Fixed steps, no LLM. Start or skip on first visit; Previous, Next, Skip and Finish; replay at any time. |
| **AW-11** | **Resilient steps** | Steps use stable IDs and selectors. A missing target is skipped or shown as a centred message; the tour never blocks the app. |

| Step | Target | Message |
|---|---|---|
| 1 | Main dashboard | Your overview of customers, marketing and help. |
| 2 | Customer Genome | See repeat buyers and history, get alerted when a returning customer messages, and notify customers when a product is back. |
| 3 | Creator Commerce | Collect customer reviews, study competitor ads, track your own ads and find collaborators. |
| 4 | Agent Workspace | Ask common questions for free, or use the AI assistant for unique ones. |
| 5 | Finish | You are ready. Replay this tour anytime from the Agent Workspace. |

| Test | Scenario and expected result |
|---|---|
| **AW-T09** | A first-time user sees the tour offer; Skip closes it; Replay restarts it from step 1. |
| **AW-T10** | A tour target is missing. The step is skipped or centred; the app stays usable. |

---

# 16. Delivery Plan

Phases are sequenced by dependency, not by calendar. Phase 0 removes the biggest unknowns before the team commits to them.

| Phase | Scope | Exit criteria |
|---|---|---|
| **0 Feasibility**<br>Small | Meta ad data access for Bangladesh commercial ads (OD-06); Messenger and WhatsApp identity and message windows (OD-05); SMS gateway and email provider selection; Meta app review and business verification lead time; Customer, order and inventory source (OD-01) | Go or no-go recorded for each integration. Decisions OD-01, 05, 06 closed. |
| **1 Foundation**<br>Medium | Authentication, tenant model, roles, sidebar shell; Identity & Consent, Messaging Gateway, Scheduler & Queue, Realtime, Audit log; API conventions, logging, CI | Tenant isolation and idempotency tests pass on the shared services. |
| **2 Customer Genome**<br>Large | Data adapter, history, Repeat Buyers; Identity linking and Returning Customer Bubbles; Restore Product: interests, waiting lists, restock detection, owner-confirmed batches | CG-T01 to T08 and RP-T01 to T08 pass. |
| **3 Creator Commerce**<br>Large | Review first; Meta Ads Intelligence on the tier chosen in Phase 0; My Ads Performance, Collaboration Finder, optional Influencer view | RV, MI, MP, CF tests pass. |
| **4 Agent Workspace**<br>Medium | FAQ registry and matching; Chat routing, AI agent with read-only tools, usage metrics; Website tour | AW-T01 to T10 pass. Can start after Phase 1. |
| **5 Hardening**<br>Medium | Security review, data correctness, failure and load tests; Responsive UI, owner acceptance, staged rollout | Definition of Done met for all modules. |

> **DECISION — Suggested first release**
> Customer Genome (history, bubbles, Restore Product), Review and Agent Workspace. Meta Ads Intelligence joins once Phase 0 confirms a viable data tier.

## 16.1 Definition of Done

- All acceptance tests for the feature pass.
- Cross-tenant access test and duplicate-event test pass.
- Empty, error and unavailable-data states are designed and tested.
- Requirements, API and data-model sections updated in the master document.

---

## 17. Success Metrics

Not specified in the source document. Proposed **RECOMMENDED** measures, to be confirmed by the owner:

| Metric | Definition | Target |
|---|---|---|
| Bubble qualification rate | Bubbles created ÷ inbound messages received | Baseline in Phase 2; rising trend as identity links accumulate |
| Bubble latency p95 | Time from webhook receipt to bubble visible | ≤ 5 s (see TRD NFR) |
| Restock recovery | Waiting-list recipients sent a message ÷ waiting-list recipients eligible | Tracked per business; no fixed target set |
| Review response rate | Replies received ÷ review requests delivered | Baseline in Phase 3 |
| Consent rate | Approved + anonymous ÷ consent answers received | Baseline in Phase 3 |
| FAQ containment | FAQ + data routes ÷ total chat requests | Majority target; AI route is the exception by design |
| AI cost per business | Sum of `ai_usage_events.estimated_cost` per tenant per month | Bounded by OD-10 cost cap |
| Cross-tenant violations | Count of failed isolation tests | 0 |

---

## 18. Decision Register

Decisions are listed in the order they are needed. Items proposed in v3.0 are the default until the owner changes them.

| ID | Decision | Why it matters | Owner | Needed by |
|---|---|---|---|---|
| **OD-01** | Customer, order and inventory data source and integration method | Blocks all of M1 and Restock detection | Product + Eng | Phase 0 |
| **OD-02** | Qualifying-order rules (cancelled, refunded, partial) and the Returning vs Repeat definitions | Accuracy of totals, lists and bubbles | Product | Phase 1 |
| **OD-03** | Tenant model: multi-tenant SaaS or single business | Shapes data model and security | Product | Phase 1 |
| **OD-04** | Bubble persistence and dismissal rules; confirm in-dashboard bubbles only | Daily staff experience | Product + Design | Phase 2 |
| **OD-05** | Channel eligibility per provider (Meta windows, WhatsApp templates, SMS and email rules) | Decides which channel actually delivers | Eng | Phase 0 |
| **OD-06** | Meta ad data access tier (official API, provider or manual) | Feasibility of Meta Ads Intelligence | Eng | Phase 0 |
| **OD-07** | Consent capture, retention periods and erasure handling for reviews and chats | Legal and trust | Product + Legal | Phase 1 |
| **OD-08** | Review defaults: delay, send window, reply window, one request per order | Review behaviour and cost | Product | Phase 3 |
| **OD-09** | FAQ ownership, editing and review workflow | Answer quality | Product | Phase 4 |
| **OD-10** | AI provider and model, cost caps, chat retention, redaction policy | Cost and privacy | Product + Eng | Phase 4 |
| **OD-11** | Technology stack and hosting | Build speed and operations | Eng | Phase 0 |
| **OD-12** | Stock-warning thresholds and inventory authority | Restock accuracy | Product | Phase 2 |
| **OD-13** | UI language or languages | Content and layout | Product | Phase 1 |

---

## 19. Traceability

| Source section | This document |
|---|---|
| Project.md §2 Product Overview | §2–§5 |
| Project.md §3 Customer Genome | §6–§8 |
| Project.md §4 Creator Commerce | §9–§13 |
| Project.md §5 Agent Workspace | §14–§15 |
| Project.md §6 System Architecture | TRD.md, ERD.md, ARCHITECTURE.md |
| Project.md §7 Delivery Plan | §16 |
| Project.md §8 Decision Register | §18 |

**Companion documents:** `TRD.md` · `ERD.md` · `USER_FLOW.md` · `ARCHITECTURE.md`
