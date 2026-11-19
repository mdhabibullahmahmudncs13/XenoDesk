# XenoDesk – Features, Structure and User Workflow

**Version 3.1** · 18 November 2026 · *Summary of the master project documentation*

---

## 1. Product Overview

XenoDesk is one project that combines the sourcing workspace and the customer and marketing platform. It helps a business find and source products, know its customers, market with evidence, and get unstuck quickly. Four modules share one dashboard, one customer identity layer, and one messaging layer, and they come in this order:

1. **Module 1 – Sourcing Workspace:** Takes a business from a product idea to a supplier shortlist: Dashboard, Onboarding, Market Intelligence, Product Search, Cart.
2. **Module 2 – Customer Genome:** Turns order history into customer understanding. Shows returning buyers the moment they message and wins back customers waiting for out-of-stock products.
3. **Module 3 – Creator Commerce:** Collects customer reviews, studies competitor ads, tracks the business's own ads, and finds collaborators.
4. **Module 4 – Agent Workspace:** Answers common questions instantly at zero AI cost, uses AI only for unique questions, and guides new users with a tour.

### In Scope
* Sourcing workspace: dashboard, onboarding chat, market intelligence, product search across supplier marketplaces, cart
* Customer history, Repeat Buyers list, Returning Customer Bubbles
* Restore Product with owner-confirmed batches
* Review requests, reply capture, consent, and marketing cards
* Competitor ad intelligence, own-ad performance, collaboration finder
* FAQ chat, AI chat for unique questions, website tour

### Out of Scope
* Publishing ads or editing budgets
* Sending partner or influencer outreach
* AI deleting or editing customer records
* Image analysis in chat (future)
* Browser push notifications
* Using an LLM to answer FAQ prompts

---

## 2. Roles and Permissions

| Capability | Owner | Admin | Staff |
| :--- | :---: | :---: | :---: |
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

## 3. Module 1: Sourcing Workspace

Helps a business go from a product idea to a shortlist of suppliers. The journey is Dashboard, Onboarding, Market Intelligence, Product Search, and Cart. This module comes first, and the other three modules live on the same dashboard.

### 3.1 Dashboard
* **Page:** `/en/dashboard`, titled *Workspace*.
* **Next action:** A highlighted action to pick up where the user left off. New users choose *Open onboarding*; users who want to go straight to analysis open *Research*.
* **Summary cards:** Products being tracked, saved landed cost, and recorded net financial result. They are built from saved workspace activity, so they can be empty at first.

### 3.2 Onboarding
* **Page:** `/en/onboarding`.
* **AI chat:** Asks one question at a time, with typed answers or quick replies.
* **Questions cover:** Business type, location, product idea, investment budget, team size, account type, experience, and main sales channels.
* **Product idea:** The user gives a specific idea, such as *wireless earbuds*.
* **On completion:** The onboarding details are saved and Market Intelligence opens with the idea prefilled.

### 3.3 Market Intelligence
* **Page:** `/en/research`, opened from the dashboard.
* **Entry:** Arriving from onboarding starts the analysis automatically; otherwise the user enters a product idea and runs it.
* **Demand and trends:** Where interest is concentrated and whether there is a seasonal peak.
* **Competition:** Estimated number and density of competitors and how established the market is.
* **Prices and risks:** Estimated local price range in BDT, sourcing options, and risk factors, with a data quality score.
* **Next step:** *Continue to Products* carries the same keyword into Product Search.

### 3.4 Product Search (Product Intelligence)
* **Page:** `/en/research/products`. It can be opened directly with a keyword, or reached from Market Intelligence for an automatic search.
* **Marketplaces:** Alibaba, AliExpress, DHgate, Pinduoduo, Xianyu, and SkyBuyBD.
* **Filters:** By price or shipping time.
* **Comparison:** Shortlisted listings side by side, with supplier ratings and shipping estimates where available.

### 3.5 Cart
* Listings the user wants to keep are added to the cart.
* *Go to Cart* shows the selected listings for review.
* **How it connects:** The saved onboarding profile, tracked products, and landed cost feed the dashboard summary cards, and the sidebar leads on to Customer Genome, Creator Commerce, and Agent Workspace.

---

## 4. Module 2: Customer Genome

Reads customer and order data from an independent source, builds a history per customer, and uses it in two moments: when a known customer messages, and when an out-of-stock product returns.

### 4.1 Repeat Buyers and Customer History
* **Repeat Buyers list:** Customers with two or more qualifying orders, showing name, contact, order count, last purchase date, new-order indicator, and a *View History* action.
* **Customer history:** A profile with a chronological order timeline (date, products, quantity, totals, status) and filters by date and product.
* **Identity matching:** Match by customer ID, normalised phone (`+880…`), normalised email, or a verified messaging link. Conflicts are never auto-merged; they are flagged for staff review.
* **Independent data source:** Customer and order data arrive through an adapter from an external source.

### 4.2 Returning Customer Bubbles
When a customer writes to the business, a small floating Messenger-style bubble appears in the dashboard. Expanding it shows staff that this person has bought before.

* **Trigger:** Only a new inbound customer message on a connected channel creates or updates a bubble. Orders, visits, and logins never do.
* **Qualification:** A bubble is created only if the customer has at least one qualifying order before the message.
* **Card contents:** *Returning Customer* label, name, total previous orders, total purchase amount (with "as of" time), last purchase date, and a link to history.
* **Deduplication:** Replayed webhooks or repeated messages update the existing bubble. One bubble per customer and conversation.
* **Live figures:** Counts and spend refresh after a new qualifying order.
* **Safe identity:** With no confident match, no label and no other customer's data is shown; staff are offered *Link customer*.
* **In-app only:** Works without browser push permission.
* **Bubble states:** `New`, `Seen`, `Dismissed`. A new message from a dismissed customer re-opens the bubble.

#### How a message is tied to a customer

| Method | Channels | Reliability |
| :--- | :--- | :--- |
| Verified link | All | High (primary lookup) |
| Normalised phone number | WhatsApp, SMS | High (automatic) |
| Email address | Email | High (automatic) |
| Staff *Link customer* action, or customer shares phone in chat | Messenger | High after confirmation |
| Display name | None | Never used |

### 4.3 Restore Product
When an out-of-stock product returns, the owner can invite the customers who asked for it. The system prepares everything; the owner decides when to send. There is no automatic sending.

* **Interest capture:** Staff use *Add to waiting list* from a customer profile, a bubble, or a product page. Optional CSV import.
* **Waiting lists:** Grouped by product and variant; variants are never mixed.
* **Restock detection:** Stock moving from zero to available creates a restock event and a dashboard notification.
* **Message template:** Merge fields for customer name, request date, product name, and business name, with a preview before sending.
* **Owner-confirmed batch:** The preview shows recipients, channel per recipient, and message. One confirmation queues the batch.
* **Consent and duplicates:** Eligibility is re-checked at send time; an idempotency key prevents duplicate sends.
* **Stock warning:** Warns when available stock is lower than waiting demand. The message never promises reservation.
* **Delivery history:** Per recipient status of `pending`, `sent`, `delivered`, `failed`, or `skipped` with reason. Retries are bounded.

#### Channel routing

| Channel | Role | Conditions |
| :--- | :--- | :--- |
| Email | Default | Authenticated sender domain, valid address, unsubscribe link |
| SMS | Default | Gateway configured, valid mobile number, opt-out honoured |
| Messenger | Conditional | Only inside the window or message type the platform allows |
| WhatsApp | Conditional | Approved template and recorded opt-in |

---

## 5. Module 3: Creator Commerce

Supports marketing with evidence: real customer feedback, competitor creative, own ad results, and potential collaborators.

### 5.1 Review
Turns delivered orders into authentic customer feedback and, with the customer's permission, into marketing cards. The customer's original words are never edited.

* **Trigger:** Only a verified delivery confirmation schedules a request.
* **Delay and send window:** 3 or 4 days after delivery (default 3), sent inside a configured window (default `09:00` to `20:00`, business time zone).
* **Eligibility at send time:** Order not cancelled, returned, or refunded; contact permission; channel eligibility; no opt-out.
* **One request per order:** A repeated delivery event never creates a second request.
* **Request message:** Template with customer, product(s), business name, and a reference token.
* **Reply capture:** Replies matched by token or thread within a reply window (default 14 days). Ambiguous replies go to *Needs assignment*.
* **Original preserved:** Verbatim text with message ID, timestamp, channel, customer, order, and product. Immutable. Positive, neutral, and negative replies are all kept.
* **Publication consent:** The customer is asked once: *Yes*, *Anonymous only*, or *No*. States: `pending`, `approved`, `anonymous`, `declined`, `revoked`.
* **Marketing card:** Generated from the original words, labelled *"Customer review"*, never imitating Messenger or WhatsApp interfaces.
* **Review library:** Browse and filter by product, date, customer, and consent state.
* **Consent-gated export:** Export only with current consent; revocation blocks future exports.

### 5.2 Meta Ads Intelligence
The owner enters a keyword, product category, or competitor theme. The system finds relevant ads, ranks the Top 5 by AI-assessed relevance and creative quality, shows what is observable, and suggests original creative directions.

* **Search input:** Keyword, country (default Bangladesh), category; optional language and price segment.
* **Top 5 result:** Advertiser, ad URL, creative type, visible copy and hook, CTA, overlay text, visible price or offer, and reasons for the rank.
* **Ranking transparency:** Labelled as AI relevance and creative quality; never implies sales, revenue, or ROAS.
* **No invented data:** Unavailable fields show *"Not visible"* or *"Not available"*.
* **Original suggestions:** Script, offer, and CTA ideas inspired by patterns, not copies.
* **Suggested scoring (editable):** Relevance 40, message clarity 25, offer readability 20, CTA strength 15.
* **Data access tiers:** (1) official Meta Ad Library API, (2) licensed third-party ad-data provider, (3) manual intake by pasting ad links or uploading screenshots. Scraping is never used.

### 5.3 My Ads Performance
After the owner connects a Meta ad account, the system shows read-only performance and ranks the business's own ads by campaign objective.

* **Secure connection:** OAuth, account selection, permission check. Read-only; no publishing or budget edits.
* **Metrics:** Spend, impressions, reach, CTR, CPC, cost per result, conversions, CPA, ROAS where available; otherwise *"N/A, tracking not available"*.
* **Freshness:** Always shows last-synced time and warns when data is stale.
* **Objective-aware ranking:** Objectives are never mixed in one ranking.

| Objective | Ranking order | Guard |
| :--- | :--- | :--- |
| Sales | ROAS, then CPA, then conversions | Minimum spend threshold |
| Traffic | CTR, then CPC | Minimum impressions |
| Leads | Cost per lead, then lead volume | Minimum lead count |

### 5.4 Collaboration Finder
Suggests potential collaborators by category, product type, audience, and geography from a legitimate data source.

* **Result fields:** Name, platform, niche, location, audience metric if available, public contact route if available.
* The system never contacts anyone on the owner's behalf.

### 5.5 Influencer Suggestions (optional)
* Bangladesh-relevant influencers by niche with available follower metrics, marked *Unverified* until confirmed.
* **Optional:** If disabled, every other Creator Commerce feature works unchanged.

---

## 6. Module 4: Agent Workspace

Quick help inside the product: a Smart Chat Assistant (full page and floating launcher) and a Website Tour.

### 6.1 Smart Chat Assistant
* **Chat routing:** Try a fixed FAQ, then an authorised data query, then AI for eligible unique questions. FAQ and data routes run without an LLM call.
* **Full chat page:** A dedicated sidebar entry.
* **Floating launcher:** On all authenticated pages; current page state is preserved.
* **Pre-built FAQ prompts:** Fixed answer plus a link to the relevant screen.
* **No tokens for FAQ:** A FAQ match never calls the LLM; usage records zero tokens.
* **Deterministic data answers:** Simple questions such as *"how many active ads do I have?"* use authorised queries.
* **AI for unique questions:** Read-only, allow-listed tools; explains missing data; never invents counts, rankings, or customer facts.
* **Authorisation:** Tenant and role checked on every tool call.
* **Usage monitoring:** Per request ID, route (`faq`, `data`, `ai`), tokens, latency, estimated cost.
* **Images unsupported in V1:** A clear *"future feature"* message is shown.
* **Matching rules:** Text is normalised (lower-case, punctuation removed, Bangla Unicode, and common Banglish spellings), then matched by exact FAQ ID first and alias lists next. Below the confidence threshold the message moves to the next route. Each FAQ has an owner and a review date; Owner and Admin can edit.

#### Routing examples

| User asks | Route | Result |
| :--- | :--- | :--- |
| "How do I use Review?" | FAQ | Fixed answer plus link; zero tokens |
| "How many active ads do I have?" | Data | Authorised query; count with "as of" time |
| "Which of my ads should I pause and why?" | AI | Read-only tools; recommendation with evidence; no changes made |
| "Delete this customer." | Blocked | Clear refusal; no write tools exist |

* **AI safety rules:** Ad copy, reviews, and customer text are untrusted input and cannot change instructions. The tool registry has no write actions. Personal data is minimised or redacted before reaching the LLM provider.

### 6.2 Website Tour
* **Predefined tour:** Fixed steps, no LLM. Start or skip on first visit; Previous, Next, Skip, and Finish; replay any time.
* **Resilient steps:** Stable IDs and selectors. A missing target is skipped or shown as a centred message; the tour never blocks the app.

| Step | Target | Message |
| :---: | :--- | :--- |
| 1 | Main dashboard | Your overview of customers, marketing and help |
| 2 | Customer Genome | Repeat buyers and history, returning customer alerts, back-in-stock notifications |
| 3 | Creator Commerce | Reviews, competitor ads, own ads and collaborators |
| 4 | Agent Workspace | Free common answers, AI assistant for unique questions |
| 5 | Finish | Replay the tour anytime from the Agent Workspace |

---

## 7. System Structure

One tenant-aware application with clear service boundaries. **Flow:** dashboard and inbound channels $\rightarrow$ API and webhooks $\rightarrow$ shared platform and module services $\rightarrow$ tenant-scoped storage, queues, and external adapters.

### 7.1 Shared platform services

| Service | Responsibility |
| :--- | :--- |
| Identity & Consent | Messaging identity links, contact permissions, opt-outs, consent records |
| Messaging Gateway | Inbound webhook signature check and idempotent event store; outbound channel adapters (Email, SMS, Messenger, WhatsApp), send-time eligibility, rate limits, bounded retries, one delivery log |
| Scheduler & Queue | Delayed jobs (review requests), batch sends (restock), retries, restock detection |
| Realtime | Server-sent events per business for bubble created, updated, and removed |
| Audit log | Batch approvals, exports, consent changes, identity links, role changes |

### 7.2 Cross-cutting rules
* **Tenant isolation:** Every query, webhook route, and cache key carries `business_id`.
* **Idempotency:** Unique constraints on inbound event IDs and outbound idempotency keys; outbox pattern for sends.
* **No fabricated data:** Unknown values display as unavailable.
* **Least data to AI:** Minimum fields, personal data redacted.
* **Time:** Store UTC, display in the business time zone.

### 7.3 Main data entities

| Entity | Used by |
| :--- | :--- |
| `messaging_identity_links`, `inbound_message_events`, `customer_bubbles` | Customer Genome |
| `contact_permissions` | Restore Product, Review |
| `product_interests`, `restock_events`, `restock_batches` | Restore Product |
| `outbound_messages` | Restore Product, Review |
| `review_settings`, `review_requests`, `review_replies`, `review_permissions`, `review_cards` | Review |
| `ad_insight_snapshots` | Meta Ads Intelligence, My Ads Performance |
| `faq_entries`, `chat_sessions`, `ai_usage_events`, `tour_steps`, `tour_progress` | Agent Workspace |

### 7.4 Non-functional targets
* **Performance:** Bubble visible within $5\text{ s}$ ($p_{95}$) of webhook receipt; read endpoints under $500\text{ ms}$ ($p_{95}$).
* **Reliability:** Webhooks acknowledged quickly and processed asynchronously; $99.5\%$ availability target.
* **Security:** HTTPS only, webhook signature verification, managed secrets, RBAC per endpoint, tenant isolation tests.
* **Privacy:** Consent audit trail, defined retention and erasure handling.
* **Language:** FAQ and message templates in Bangla and English.
* **Accessibility:** Bubbles, chat, and tour are keyboard operable with sufficient contrast.
* **Observability:** Structured logs with request IDs; dashboards for delivery outcomes and AI cost.
* **Reference stack (non-binding):** FastAPI, PostgreSQL, Redis-backed queue, server-sent events, and a Next.js front end.

---

## 8. User Workflows

### 8.1 Sourcing journey (idea to cart)
This is the first journey a user goes through: Dashboard $\rightarrow$ Onboarding $\rightarrow$ Market Intelligence $\rightarrow$ Product Search $\rightarrow$ Cart.

1. Open the Dashboard and pick the highlighted next action (new users choose *Open onboarding*).
2. In Onboarding, answer the AI chat one question at a time with a specific product idea, such as *wireless earbuds*. The profile is saved and Market Intelligence opens with the idea prefilled.
3. In Market Intelligence, review demand and trends, competition, and BDT prices and risks. Select *Continue to Products*.
4. In Product Search, the same keyword is searched automatically across the supplier marketplaces. Filter, compare, and shortlist listings.
5. Add listings to the Cart and select *Go to Cart* to review them.
6. From the same dashboard, move on to Customer Genome, Creator Commerce, and Agent Workspace.

### 8.2 Returning customer messages the business
1. A customer sends a message on a connected channel.
2. The system verifies and deduplicates the event.
3. The customer's identity is resolved (verified link, phone, or email).
4. The system checks for a qualifying prior order.
5. A bubble appears in the dashboard; staff expand it to see order count, total spend, and last purchase, and can open full history.
6. If no confident match exists, staff use *Link customer* to connect the identity.

### 8.3 Restock notification
1. Staff add customers to a product or variant waiting list.
2. Stock goes from zero to available; the owner gets a dashboard notification.
3. The owner previews the batch (recipients, channels, message) and sees any stock warning.
4. The owner confirms once.
5. The system re-checks eligibility and sends; per-recipient delivery status is recorded.

### 8.4 Customer review to marketing card
1. Delivery is confirmed.
2. A request is scheduled after the configured delay (default 3 days) within the send window.
3. Eligibility is re-checked and the request is sent.
4. The reply is matched to the order and preserved verbatim.
5. The customer is asked for publication consent.
6. With consent, a marketing card is generated and can be exported.

### 8.5 Ad research and performance
1. The owner searches competitor ads and gets the Top 5 with reasons and original creative ideas.
2. The owner connects the Meta ad account (read-only) and reviews metrics.
3. Own ads are ranked per campaign objective.
4. The owner browses collaborator suggestions and contacts them personally.

### 8.6 Getting help
1. A new user is offered the website tour on first visit.
2. The user opens the chat assistant from the sidebar or floating launcher.
3. FAQ and data questions are answered instantly; unique questions go to the AI with read-only tools.

---

## 9. Delivery Plan

| Phase | Scope | Exit criteria |
| :--- | :--- | :--- |
| **0 Feasibility** | Meta ad data access, messaging windows, SMS and email providers, Meta review lead time, data source | Go or no-go for each integration |
| **1 Foundation** | Auth, tenants, roles, sidebar shell, shared platform services | Tenant isolation and idempotency tests pass |
| **2 Customer Genome** | Data adapter, history, Repeat Buyers, bubbles, Restore Product | CG and RP tests pass |
| **3 Creator Commerce** | Review, Meta Ads Intelligence, My Ads Performance, Collaboration Finder | RV, MI, MP, CF tests pass |
| **4 Agent Workspace** | FAQ matching, chat routing, AI agent, usage metrics, tour | AW tests pass |
| **5 Hardening** | Security review, load tests, responsive UI, staged rollout | Definition of Done met |

* **Suggested first release:** Customer Genome, Review, and Agent Workspace. Meta Ads Intelligence joins once Phase 0 confirms a viable data tier.
* **Build order:** Sourcing Workspace first (Dashboard, Onboarding, Market Intelligence, Product Search, Cart), then Customer Genome, Creator Commerce, and Agent Workspace.
* **Definition of Done:** All acceptance tests pass; cross-tenant and duplicate-event tests pass; empty, error, and unavailable-data states are tested; documentation is updated.

---

## 10. Open Decisions

* **Open with interim approach:**
  * `OD-01` data source (adapter boundary)
  * `OD-05` channel eligibility (configurable)
  * `OD-06` Meta ad data tier (manual intake baseline)
  * `OD-10` AI provider and caps (caps and redaction applied)
* **Applied defaults, to confirm:**
  * `OD-07` consent and retention (confirm with legal)
  * `OD-13` UI language (confirm with owner)
* **Closed:**
  * `OD-03` tenant model
  * `OD-11` technology stack