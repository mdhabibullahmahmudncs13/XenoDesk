# Xenovarients product and workspace documentation

**Version 3.1 · 18 November 2026**

This document consolidates the [v3.0 project baseline](Project.md) and the [SWODAGAR quick guide](workspace-quick-guide.md).

## Contents

1. [Document control](#1-document-control)
2. [Product overview](#2-product-overview)
3. [Customer Genome](#3-customer-genome)
4. [Creator Commerce](#4-creator-commerce)
5. [Agent Workspace](#5-agent-workspace)
6. [System architecture](#6-system-architecture)
7. [Delivery plan](#7-delivery-plan)
8. [Decision register](#8-decision-register)
9. [SWODAGAR workspace workflow](#9-swodagar-workspace-workflow)

## 1. Document Control

| **Document** | Master Project Documentation: requirements, system design and delivery plan                           |
|--------------|-------------------------------------------------------------------------------------------------------|
| **Version** | 3.1, based on the v3.0 project baseline |
| **Date** | 18 November 2026 |
| **Modules**  | M1 Customer Genome · M2 Creator Commerce · M3 Agent Workspace                                         |
| **Audience** | Product owner, developers, architects, QA, marketing stakeholders                                     |
| **Status** | M1–M3 scope follows the approved v3.0 baseline. Section 9 records SWODAGAR workflows from the quick guide. See Section 8 for decision status. |

#### How to read this document

| **APPROVED**    | Owner-approved scope. Implement as written.                                                    |
|-----------------|------------------------------------------------------------------------------------------------|
| **RECOMMENDED** | Design proposal made in v3.0 to close a gap. Treat as the default unless the owner changes it. |
| **OPEN**        | Undecided. Tracked in the Decision Register (Section 8).                                       |

#### ID conventions

| **Item**         | **Pattern**                    | **Example**                                                                                                                                                                                |
|------------------|--------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Module           | M1 to M3                       | M2 = Creator Commerce                                                                                                                                                                      |
| Requirement      | \<FEATURE\>-\<nn\>             | CG-04, RP-07, RV-09, AW-03                                                                                                                                                                 |
| Acceptance test  | \<FEATURE\>-T\<nn\>            | RV-T05                                                                                                                                                                                     |
| Open decision    | OD-\<nn\>                      | OD-06                                                                                                                                                                                      |
| Feature prefixes | CG, RP, RV, MI, MP, CF, IF, AW | CG = Customer Genome, RP = Restore Product, RV = Review, MI = Meta Ads Intelligence, MP = My Ads Performance, CF = Collaboration Finder, IF = Influencer Suggestions, AW = Agent Workspace |

#### Revision history

| **Version** | 3.1, based on the v3.0 project baseline |
|-------------|-------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| 2.1         | n/a         | Added Restore Product as the fourth Customer Genome feature.                                                                                     |
| 2.2         | n/a         | Replaced the order-triggered popup with message-triggered Returning Customer Bubbles.                                                            |
| 2.3         | n/a         | Added Review as the first Creator Commerce feature.                                                                                              |
| **3.0**     | 16 Nov 2026 | Consolidated rewrite in English: IDs and numbering fixed, stale sections aligned, shared platform services defined, gaps closed, diagrams added. |
| **3.1** | 18 Nov 2026 | Consolidated the project baseline and workspace guide, checked route coverage, and linked decision records. |

#### What v3.0 corrected

| **Area**                    | **Correction**                                                                                                                                                                                                                                 |
|-----------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Identifiers**             | Module IDs (M1–M3) separated from requirement IDs, which previously collided (CG-001, CC-002, AW-003, CC-REV-001). Duplicate section numbers and two overlapping bubble test sets merged.                                                      |
| **Misplaced content**       | Data-model, API and Review-pipeline rows that had landed inside unrelated tables moved to Section 6. The broken feature table (header row swapped with a data row) rebuilt.                                                                    |
| **Alignment**               | Restore Product lives only in M1; Creator Commerce has five features. Summary, scope, tour copy and architecture now reflect Restore Product and Review.                                                                                       |
| **Definitions**             | **Returning Customer** (bubble, one or more prior orders) and **Repeat Buyer** (list, two or more orders) separated. Entity names unified (inbound_message_events, customer_bubbles).                                                          |
| **Gaps closed RECOMMENDED** | Identity-linking paths for Messenger, channel routing by eligibility, review consent step and reply window, waiting-list capture, Meta data-access tiers, shared Messaging Gateway, roles matrix, non-functional targets, Phase 0 feasibility. |
| **Removed**                 | History-style wording (“now begins with”, “NEW”, “supersedes”), duplicated tables and the legacy popup text.                                                                                                                                   |

## 2. Product Overview

The platform helps a business **know its customers**, **market with evidence** and **get unstuck quickly**. It is organised as three modules that share one dashboard, one customer identity layer and one messaging layer.

**Dashboard structure** — Customer Genome, Creator Commerce, and Agent Workspace share one dashboard.

| **M1 Customer Genome**<br>Turns order history into customer understanding.<br>Surfaces returning buyers the moment they message, and wins back customers waiting for out-of-stock products. |     | **M2 Creator Commerce**<br>Collects customer reviews, studies competitor ads, tracks own ads and finds collaborators. |     | **M3 Agent Workspace**<br>Answers common questions instantly at zero AI cost, uses AI only for unique questions, and guides new users with a tour. |
|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----|-----------------------------------------------------------------------------------------------------------------------|-----|----------------------------------------------------------------------------------------------------------------------------------------------------|

### 2.1 Scope

| **In scope APPROVED**                                                                                                                                                                                                                                                                           | **Out of scope**                                                                                                                                                                                          |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Customer history, Repeat Buyers list, Returning Customer Bubbles; Restore Product with owner-confirmed batches; Review requests, reply capture, consent and marketing cards; Competitor ad intelligence, own-ad performance, collaboration finder; FAQ chat, AI chat for unique questions, website tour | Publishing ads or editing budgets; Sending partner or influencer outreach; AI deleting or editing customer records; Image analysis in chat (future); Browser push notifications; Using an LLM to answer FAQ prompts |

| **NOTE Optional items**<br>Influencer Suggestions (IF) is optional and never blocks a release. Items not yet decided are listed in the Decision Register (Section 8). |
|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------|

### 2.2 Roles and permissions (recommended)

Three roles replace the mixed use of “Admin”, “Business Owner” and “authorized staff” in earlier versions.

| **Capability**                                    | **Owner** | **Admin** | **Staff** |
|---------------------------------------------------|-----------|-----------|-----------|
| View bubbles, customer history, Repeat Buyers     | Yes       | Yes       | Yes       |
| Link a messaging identity to a customer           | Yes       | Yes       | Yes       |
| Add a customer to a product waiting list          | Yes       | Yes       | Yes       |
| Approve a restock notification batch              | Yes       | No        | No        |
| Configure review delay, channels and templates    | Yes       | Yes       | No        |
| Export review marketing cards                     | Yes       | Yes       | No        |
| Connect ad accounts                               | Yes       | No        | No        |
| Manage FAQ entries and tour steps                 | Yes       | Yes       | No        |
| Use the chat assistant (data access follows role) | Yes       | Yes       | Yes       |

### 2.3 Glossary

| **Term**               | **Meaning**                                                                                                                                                       |
|------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Tenant / Business**  | One customer organisation. Every record carries a business_id; data never crosses tenants.                                                                        |
| **Qualifying order**   | An order that counts toward history and totals. Default: paid or completed; cancelled and fully refunded orders excluded; partial refunds counted net. See OD-02. |
| **Returning Customer** | A customer with at least one qualifying order **before** the current inbound message. Drives the bubble.                                                          |
| **Repeat Buyer**       | A customer with two or more qualifying orders. Drives the Repeat Buyers list.                                                                                     |
| **Bubble**             | A small floating, Messenger-style indicator showing a returning customer has just messaged.                                                                       |
| **Restock event**      | A product or variant changing from unavailable to available in the authoritative inventory source.                                                                |
| **Messaging Gateway**  | Shared service that receives inbound messages and sends outbound messages with eligibility checks, idempotency and delivery logs.                                 |
| **Idempotency key**    | A unique key that guarantees a repeated event or send request produces one outcome.                                                                               |

## 3. Customer Genome

Customer Genome reads customer and order data from an independent source, builds a reliable history per customer and uses it in two moments that matter: **when a known customer messages** and **when an out-of-stock product returns**.

| **Feature**                          | **IDs**        | **Sidebar position**           |
|--------------------------------------|----------------|--------------------------------|
| **Repeat Buyers & Customer History** | CG-01 to CG-04 | 1                              |
| **Returning Customer Bubbles**       | CG-05 to CG-11 | 2 (floating, all pages)        |
| **Restore Product**                  | RP-01 to RP-10 | 4th item under Customer Genome |

### 3.1 Repeat Buyers & Customer History

| **ID**    | **Requirement**             | **Expected behavior**                                                                                                                                                  |
|-----------|-----------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **CG-01** | **Repeat Buyers list**      | Lists customers with two or more qualifying orders: name, contact, order count, last purchase date, new-order indicator and a View History action.                     |
| **CG-02** | **Customer history**        | A profile with a chronological order timeline (date, products, quantity, totals, status) and filters by date and product.                                              |
| **CG-03** | **Identity matching**       | Match by customer ID, normalised phone (E.164, +880…), normalised email or a verified messaging link. A conflict is never auto-merged; it is flagged for staff review. |
| **CG-04** | **Independent data source** | Customer and order data arrive through an adapter from a source independent of this app. Integration method: OD-01 **OPEN** .                                          |

| **DECISION Two terms, two rules**<br>**Returning Customer** (one or more prior orders) drives the bubble. **Repeat Buyer** (two or more orders) drives the list. A customer with exactly one prior order gets a bubble but is not in the Repeat Buyers list. Confirm this intent in OD-02. |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

#### Minimum data contract

| **Field**              | **Type**         | **Notes**                                   |
|------------------------|------------------|---------------------------------------------|
| customer_id            | string           | Stable identifier from the source           |
| name, phone, email     | string           | Phone and email normalised on ingest        |
| order_id, ordered_at   | string, datetime | Business time zone preserved                |
| status                 | enum             | Mapped to the qualifying-order rule (OD-02) |
| items\[\]              | list             | Product ID, name, quantity, line total      |
| total_amount, currency | decimal, string  | Net of refunds where applicable             |

### 3.2 Returning Customer Bubbles

When a customer writes to the business, the dashboard shows a small floating bubble. Expanding it tells staff, at a glance, that this person has bought before and how much.

**Inbound message flow** — Receive and deduplicate the event → resolve customer identity → check for a qualifying prior order → create or refresh the bubble.

| **ID**    | **Requirement**     | **Expected behavior**                                                                                                                                                                                                   |
|-----------|---------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **CG-05** | **Message trigger** | Only a new inbound customer message on a connected channel creates or updates a bubble. Orders, visits and logins never do.                                                                                             |
| **CG-06** | **Qualification**   | A bubble is created only when the resolved customer has at least one qualifying order before the message.                                                                                                               |
| **CG-07** | **Bubble and card** | Floating Messenger-style indicator with initials. Expanded card shows a **Returning Customer** label, name, total previous orders, total purchase amount (with “as of” time), last purchase date and a link to history. |
| **CG-08** | **Deduplication**   | Replayed webhooks or repeated messages update the existing bubble. One bubble per customer and conversation.                                                                                                            |
| **CG-09** | **Live figures**    | After a qualifying order is recorded, counts and spend refresh from the authoritative history.                                                                                                                          |
| **CG-10** | **Safe identity**   | No confident match: no “Returning Customer” label and no data from any other customer. Staff are offered **Link customer**.                                                                                             |
| **CG-11** | **In-app only**     | Bubbles work without browser push permission. Notifications are in-app only.                                                                                                                                            |

#### How a message is tied to a customer (recommended)

| **Method**                                                             | **Channels**  | **Reliability**    | **Notes**                                                                                               |
|------------------------------------------------------------------------|---------------|--------------------|---------------------------------------------------------------------------------------------------------|
| **Verified link (**messaging_identity_links**)**                       | All           | High               | Primary lookup once a link exists.                                                                      |
| **Normalised phone number**                                            | WhatsApp, SMS | High               | The platform supplies the number, so matching is automatic.                                             |
| **Email address**                                                      | Email         | High               | Automatic match.                                                                                        |
| **Staff Link customer action, or customer shares their phone in chat** | Messenger     | High after confirm | Messenger exposes only a page-scoped ID, so the first link must be created by staff or by the customer. |
| **Display name**                                                       | None          | Never used         | Names are not unique and must never drive a match.                                                      |

| **WATCH OUT Why this section exists**<br>Without a linking path, Messenger messages could never be tied to an order history and the bubble would almost never appear. Build WhatsApp, SMS and Email matching first; add Messenger once **Link customer** is in place. |
|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

| **DECISION Where bubbles appear (recommended)**<br>Bubbles render in the dashboard shell on every page. Replies stay in each platform's own inbox. A native inbox is out of scope for V1.<br>Bubble states: **New**, **Seen**, **Dismissed**. A new inbound message from a dismissed customer re-opens the bubble. Final persistence rules: OD-04. |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

#### Acceptance tests

| **Test**   | **Scenario and expected result**                                                                                    |
|------------|---------------------------------------------------------------------------------------------------------------------|
| **CG-T01** | A linked returning customer messages. Exactly one bubble appears; the card shows the correct order count and total. |
| **CG-T02** | A first-time buyer messages. No bubble and no “Returning Customer” label.                                           |
| **CG-T03** | Identity is unlinked or conflicting. No label, no other customer's data, **Link customer** offered.                 |
| **CG-T04** | The same webhook arrives twice, or three messages arrive. Still one bubble; last activity updates.                  |
| **CG-T05** | Two returning customers message. Two bubbles, each with correct figures.                                            |
| **CG-T06** | A new qualifying order is recorded. The card refreshes.                                                             |
| **CG-T07** | Browser notifications blocked. Bubbles still work.                                                                  |
| **CG-T08** | A customer with one order gets a bubble but is absent from Repeat Buyers. At two orders they appear in the list.    |

### 3.3 Restore Product

When an out-of-stock product returns, the owner can invite the customers who asked for it. The system prepares everything; **the owner decides when to send**.

**Restock flow** — Capture interest by variant → detect a restock → notify the owner → preview the batch → obtain owner confirmation → recheck eligibility and send.

| **RULE No automatic sending**<br>A restock event only notifies the owner. Messages leave the system only after an explicit owner confirmation of one batch. |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------|

| **ID**    | **Requirement**            | **Expected behavior**                                                                                                                                                                                           |
|-----------|----------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **RP-01** | **Menu placement**         | Restore Product is the fourth item under Customer Genome.                                                                                                                                                       |
| **RP-02** | **Interest capture (recommended)** | Staff record interest with **Add to waiting list** (from a customer profile, a bubble or a product page). Optional CSV import. Stored: customer, contact, product and variant, request date, optional quantity. |
| **RP-03** | **Waiting lists**          | Grouped by product and variant. Variants are never mixed.                                                                                                                                                       |
| **RP-04** | **Restock detection**      | Stock moving from zero to available in the authoritative inventory source creates a restock_event and a dashboard notification.                                                                                 |
| **RP-05** | **Message template**       | Merge fields: customer name, request date, product name, business name. The owner previews before sending.                                                                                                      |
| **RP-06** | **Channels**               | Email, SMS, Messenger and WhatsApp through the Messaging Gateway, only when connected, authorised and eligible (table below).                                                                                   |
| **RP-07** | **Owner-confirmed batch**  | Preview shows recipients, channel per recipient and message. One confirmation queues the batch.                                                                                                                 |
| **RP-08** | **Consent and duplicates** | Eligibility is re-checked at send time. Idempotency key: business + restock event + interest + channel.                                                                                                         |
| **RP-09** | **Stock warning**          | Warn when available stock is lower than waiting demand. The message must not promise reservation.                                                                                                               |
| **RP-10** | **Delivery history**       | Per recipient: pending, sent, delivered (if observable), failed or skipped with reason. Retries are bounded.                                                                                                    |

#### Channel routing (recommended)

| **Channel**   | **Default role** | **Conditions**                                                           |
|---------------|------------------|--------------------------------------------------------------------------|
| **Email**     | Default          | Authenticated sender domain, valid address, unsubscribe link.            |
| **SMS**       | Default          | Gateway configured, valid mobile number, opt-out honoured.               |
| **Messenger** | Conditional      | Only inside the window or message type the platform allows at send time. |
| **WhatsApp**  | Conditional      | Approved template and recorded opt-in.                                   |

| **WATCH OUT Why channels are conditional**<br>Restock and review messages usually go out days after the last chat, which is typically outside Messenger and WhatsApp's short free-reply windows. The Gateway therefore routes by **eligibility at send time**. Verify the current Meta and SMS rules before build (OD-05). |
|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

#### Sample message

| **Hi {customer_name},**<br>You asked us about **{product_name}** on {request_date}. Good news: it is back in stock at {business_name}. Reply or visit us soon, as stock may be limited. |
|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

#### Acceptance tests

| **Test**   | **Scenario and expected result**                                                                    |
|------------|-----------------------------------------------------------------------------------------------------|
| **RP-T01** | Staff add a customer to a waiting list. The interest saves against the correct product and variant. |
| **RP-T02** | Stock goes from 0 to available. A restock event and owner notification appear. No message is sent.  |
| **RP-T03** | The owner previews a batch. Recipients, channels and text are correct and match the waiting list.   |
| **RP-T04** | The owner confirms once. Only eligible recipients are queued.                                       |
| **RP-T05** | Confirm is submitted twice. Each recipient still gets one message per channel.                      |
| **RP-T06** | A recipient has opted out or is ineligible on a channel. They are skipped with a visible reason.    |
| **RP-T07** | Stock is below waiting demand. A warning shows and the message makes no reservation promise.        |
| **RP-T08** | A send fails. Status shows failed; retries stay within the limit; other recipients are unaffected.  |

## 4. Creator Commerce

Creator Commerce supports marketing with evidence: real customer feedback, competitor creative, the business's own ad results and potential collaborators.

| **Feature**                           | **IDs**        | **Sidebar position** |
|---------------------------------------|----------------|----------------------|
| **Review**                            | RV-01 to RV-13 | 1                    |
| **Meta Ads Intelligence**             | MI-01 to MI-05 | 2                    |
| **My Ads Performance**                | MP-01 to MP-04 | 3                    |
| **Collaboration Finder**              | CF-01 to CF-03 | 4                    |
| **Influencer Suggestions (optional)** | IF-01 to IF-02 | 5                    |

### 4.1 Review

Review turns delivered orders into authentic customer feedback and, with the customer's permission, into marketing cards. The system sends the request, captures the reply, asks for permission and keeps the customer's original words untouched.

**Review flow** — Verify delivery → schedule the request → recheck eligibility and send → match the reply → preserve the original wording → capture consent → export a permitted marketing card.

| **ID**    | **Requirement**                 | **Expected behavior**                                                                                                                                               |
|-----------|---------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **RV-01** | **Menu placement**              | Review is the first item in Creator Commerce.                                                                                                                       |
| **RV-02** | **Trigger**                     | Only a verified delivery confirmation schedules a request. No confirmation, no request.                                                                             |
| **RV-03** | **Delay and send window (recommended)** | Business picks 3 or 4 days (default 3) after confirmed delivery, in the business time zone. Requests are sent inside a configured window (default 09:00 to 20:00).  |
| **RV-04** | **Eligibility at send time**    | Re-check: order not cancelled, returned or refunded; contact permission; channel eligibility; no opt-out.                                                           |
| **RV-05** | **One request per order (recommended)** | One request lists the delivered products. A repeated delivery event never creates a second request. The owner can tag a reply to a specific product.                |
| **RV-06** | **Request message**             | Template with customer, product(s) and business name, plus a reference token for matching the reply.                                                                |
| **RV-07** | **Reply capture (recommended)**         | Replies are matched by token or thread within a reply window (default 14 days). An ambiguous reply goes to **Needs assignment** instead of attaching automatically. |
| **RV-08** | **Original preserved**          | Verbatim text with message ID, timestamp, channel, customer, order and product. Immutable. Positive, neutral and negative replies are all kept.                     |
| **RV-09** | **Publication consent (recommended)**   | After a reply, the customer is asked once: **Yes**, **Anonymous only** or **No**. State per review: pending, approved, anonymous, declined, revoked.                |
| **RV-10** | **Marketing card**              | Generated from the original words, labelled “Customer review”. It must not imitate Messenger or WhatsApp interfaces or claim to be a genuine screenshot.            |
| **RV-11** | **Review library**              | Browse and filter by product, date, customer and consent state.                                                                                                     |
| **RV-12** | **Consent-gated export**        | Export only with current consent. Identity fields hidden unless permitted. Revocation blocks future exports.                                                        |
| **RV-13** | **Isolation**                   | Tenant-scoped data. Missing delivery, customer or product data shows as unresolved and is never invented.                                                           |

| **NOTE Delivery channel**<br>Review requests use the same Messaging Gateway rules as Restore Product (Section 3.3). Email and SMS are the default; Messenger and WhatsApp are used only when eligible. |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

#### Acceptance tests

| **Test**   | **Scenario and expected result**                                                                                   |
|------------|--------------------------------------------------------------------------------------------------------------------|
| **RV-T01** | Delivery confirmed with a 3-day delay. One request is due at +3 days, inside the send window.                      |
| **RV-T02** | No confirmed delivery. No request is scheduled.                                                                    |
| **RV-T03** | Delay set to 4 days. The request is due at +4 days.                                                                |
| **RV-T04** | The same delivery event arrives twice. Only one request exists.                                                    |
| **RV-T05** | The order is returned or refunded before the due time. The request is cancelled with a visible reason.             |
| **RV-T06** | The customer has opted out or the channel is ineligible. Nothing is sent; the reason is visible.                   |
| **RV-T07** | The customer replies. The verbatim text attaches to the right order. An ambiguous reply lands in Needs assignment. |
| **RV-T08** | Consent answered Yes, Anonymous and No. States and export behaviour match each answer.                             |
| **RV-T09** | A card is generated. Its words equal the original, it carries the label, and it does not imitate platform UI.      |
| **RV-T10** | Consent is revoked. Further export is blocked.                                                                     |
| **RV-T11** | A user from another business requests the review. Access is denied without revealing that it exists.               |

### 4.2 Meta Ads Intelligence

The owner enters a keyword, product category or competitor theme. The system finds relevant ads, ranks the **Top 5** by AI-assessed relevance and creative quality, shows what is observable and suggests original creative directions.

| **RISK Highest delivery risk: data access**<br>Meta's Ad Library API is largely limited to political and issue ads and to ads shown in certain regions. Commercial ads in Bangladesh may not be available through the official API. Confirm access in Phase 0 before any build commitment. Never bypass platform restrictions by scraping. |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

#### Data access tiers (recommended)

| **Tier** | **Source**                            | **Condition**                                                                     |
|----------|---------------------------------------|-----------------------------------------------------------------------------------|
| 1        | Official Meta Ad Library API          | Use if the target country and ad type are covered.                                |
| 2        | Licensed third-party ad-data provider | Use if Tier 1 is not available and terms permit.                                  |
| 3        | Manual intake                         | User pastes ad links or uploads screenshots; analysis covers only supplied items. |

| **ID**    | **Requirement**          | **Expected behavior**                                                                                                                      |
|-----------|--------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|
| **MI-01** | **Search input**         | Keyword, country (default Bangladesh), product category; optional language and price segment.                                              |
| **MI-02** | **Top 5 result**         | Per ad: advertiser, ad URL, creative type, visible copy and hook, CTA, overlay text, visible price or offer, and the reasons for its rank. |
| **MI-03** | **Ranking transparency** | Ranking is labelled as AI relevance and creative quality. It never implies sales, revenue or ROAS.                                         |
| **MI-04** | **No invented data**     | Unavailable fields show “Not visible” or “Not available”.                                                                                  |
| **MI-05** | **Original suggestions** | Script, offer and CTA ideas that are inspired by patterns, not copies of competitor creative.                                              |

| **NOTE Suggested scoring (editable) (recommended)**<br>Relevance 40, message clarity 25, offer readability 20, CTA strength 15. Each score shows its evidence and the freshness of the data. Ad copy is untrusted input and is never executed as instructions. |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

| **Test**   | **Scenario and expected result**                                                          |
|------------|-------------------------------------------------------------------------------------------|
| **MI-T01** | A keyword search returns five ads ordered by score, each with visible fields and reasons. |
| **MI-T02** | An ad without a visible price shows “Not visible”; no value is invented.                  |

### 4.3 My Ads Performance

After the owner connects a Meta ad account, the system shows read-only performance and ranks the business's own ads using rules that match each campaign objective.

| **ID**    | **Requirement**             | **Expected behavior**                                                                                                                  |
|-----------|-----------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| **MP-01** | **Secure connection**       | OAuth connection, account selection, permission check. Read-only. No publishing or budget edits.                                       |
| **MP-02** | **Metrics**                 | Spend, impressions, reach, CTR, CPC, cost per result, conversions, CPA, ROAS where available; otherwise “N/A, tracking not available”. |
| **MP-03** | **Freshness**               | Always show last-synced time and warn when data is stale.                                                                              |
| **MP-04** | **Objective-aware ranking** | Deterministic rules from the stored snapshot (table below). Objectives are never mixed in one ranking.                                 |

| **Objective** | **Ranking order**                | **Guard**               |
|---------------|----------------------------------|-------------------------|
| **Sales**     | ROAS, then CPA, then conversions | Minimum spend threshold |
| **Traffic**   | CTR, then CPC                    | Minimum impressions     |
| **Leads**     | Cost per lead, then lead volume  | Minimum lead count      |

| **WATCH OUT Lead time**<br>Reading ad-account data needs Meta app review and business verification. Start these early; they can take longer than the build. |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------|

| **Test**   | **Scenario and expected result**                                                      |
|------------|---------------------------------------------------------------------------------------|
| **MP-T01** | A 7-day filter updates every metric and the last-synced time.                         |
| **MP-T02** | Conversion tracking is missing. ROAS and CPA show N/A; objective ranking stays valid. |

### 4.4 Collaboration Finder

| **ID**    | **Requirement**   | **Expected behavior**                                                                                            |
|-----------|-------------------|------------------------------------------------------------------------------------------------------------------|
| **CF-01** | **Suggestions**   | Suggest potential collaborators by category, product type, audience and geography from a legitimate data source. |
| **CF-02** | **Result fields** | Name, platform, niche, location, audience or follower metric if available, contact route if public.              |
| **CF-03** | **No outreach**   | The system never contacts anyone on the owner's behalf.                                                          |

### 4.5 Influencer Suggestions (optional)

| **ID**    | **Requirement**   | **Expected behavior**                                                                                            |
|-----------|-------------------|------------------------------------------------------------------------------------------------------------------|
| **IF-01** | **Niche view**    | Bangladesh-relevant influencers by niche with available follower metrics, marked **Unverified** until confirmed. |
| **IF-02** | **Not a blocker** | If disabled or unavailable, every other Creator Commerce feature works unchanged.                                |

| **Test**   | **Scenario and expected result**                                              |
|------------|-------------------------------------------------------------------------------|
| **CF-T01** | A suggestion shows category match, available fields and no outreach action.   |
| **IF-T01** | With Influencer Suggestions disabled, all other features remain fully usable. |

## 5. Agent Workspace

Agent Workspace gives users quick help inside the product. It has two parts: a **Smart Chat Assistant** (full page and floating launcher) and a **Website Tour**. Common questions are answered without any AI call; the model is used only for genuinely unique questions.

| **Feature**              | **IDs**        | **Where it lives**                 |
|--------------------------|----------------|------------------------------------|
| **Smart Chat Assistant** | AW-01 to AW-09 | Sidebar page and floating launcher |
| **Website Tour**         | AW-10 to AW-11 | Overlay on every main page         |

### 5.1 Smart Chat Assistant

**Chat routing** — Try a fixed FAQ → try an authorised data query → use AI for eligible unique questions. FAQ and data routes run without an LLM call.

| **ID**    | **Requirement**                | **Expected behavior**                                                                                   |
|-----------|--------------------------------|---------------------------------------------------------------------------------------------------------|
| **AW-01** | **Full chat page**             | A dedicated Agent Workspace entry in the sidebar.                                                       |
| **AW-02** | **Floating launcher**          | Available on all authenticated pages; the current page state is preserved.                              |
| **AW-03** | **Pre-built FAQ prompts**      | Selecting a prompt returns a fixed answer and, where useful, a link to the relevant screen.             |
| **AW-04** | **No tokens for FAQ**          | A FAQ match never calls the LLM; usage records zero tokens.                                             |
| **AW-05** | **Deterministic data answers** | Simple questions such as “how many active ads do I have?” use authorised queries, not the LLM.          |
| **AW-06** | **AI for unique questions**    | Read-only, allow-listed tools. Explains missing data. Never invents counts, rankings or customer facts. |
| **AW-07** | **Authorisation**              | Tenant and role checked on every tool call.                                                             |
| **AW-08** | **Usage monitoring**           | Per request: ID, route (faq, data or ai), tokens, latency, estimated cost.                              |
| **AW-09** | **Images unsupported in V1**   | A clear message states that image analysis is a future feature.                                         |

#### Matching rules (recommended)

| **Normalisation**  | Lower-case, strip punctuation and extra spaces, normalise Bangla Unicode forms and common Banglish spellings before matching. |
|--------------------|-------------------------------------------------------------------------------------------------------------------------------|
| **Matching**       | Exact FAQ ID first, then alias lists. Below the confidence threshold the message moves on to the next route.                  |
| **Ownership**      | Each FAQ has an owner and a review date. Editors are Owner and Admin (OD-09).                                                 |
| **Response shape** | answer, answer_type (faq, data, ai), references, data_as_of, usage.                                                           |

#### Routing examples

| **User asks**                             | **Route** | **Result**                                                      |
|-------------------------------------------|-----------|-----------------------------------------------------------------|
| “How do I use Review?” (FAQ prompt)       | FAQ       | Fixed answer plus link; zero tokens.                            |
| “How many active ads do I have?”          | Data      | Authorised query; count with “as of” time.                      |
| “Which of my ads should I pause and why?” | AI        | Read-only tools; recommendation with evidence; no changes made. |
| “Delete this customer.”                   | Blocked   | Clear refusal; no write tools exist.                            |

| **RISK AI safety rules**<br>Ad copy, reviews and customer text are **untrusted input** and cannot change instructions.<br>The tool registry has no write actions: no order edits, publishing, budget changes, outreach or deletions.<br>Customer personal data is minimised or redacted before it reaches the LLM provider (OD-10). |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

| **Test**   | **Scenario and expected result**                                                           |
|------------|--------------------------------------------------------------------------------------------|
| **AW-T01** | A pre-built FAQ is selected. Fixed answer returns; the usage log shows zero tokens.        |
| **AW-T02** | An alias, Bangla or Banglish variant of a FAQ matches the same answer without an LLM call. |
| **AW-T03** | A simple metric question uses the data handler and states its data time.                   |
| **AW-T04** | A unique question reaches the AI route with read-only tools only.                          |
| **AW-T05** | A prompt injected inside ad copy is ignored; no tool outside the allow-list runs.          |
| **AW-T06** | A Staff user cannot retrieve data outside their role or another tenant's data.             |
| **AW-T07** | An image is attached. The user sees the “future feature” message.                          |
| **AW-T08** | The floating chat opens on any page and returns the user to the same page state.           |

### 5.2 Website Tour

| **ID**    | **Requirement**     | **Expected behavior**                                                                                                         |
|-----------|---------------------|-------------------------------------------------------------------------------------------------------------------------------|
| **AW-10** | **Predefined tour** | Fixed steps, no LLM. Start or skip on first visit; Previous, Next, Skip and Finish; replay at any time.                       |
| **AW-11** | **Resilient steps** | Steps use stable IDs and selectors. A missing target is skipped or shown as a centred message; the tour never blocks the app. |

| **Step** | **Target**       | **Message**                                                                                                                 |
|----------|------------------|-----------------------------------------------------------------------------------------------------------------------------|
| 1        | Main dashboard   | Your overview of customers, marketing and help.                                                                             |
| 2        | Customer Genome  | See repeat buyers and history, get alerted when a returning customer messages, and notify customers when a product is back. |
| 3        | Creator Commerce | Collect customer reviews, study competitor ads, track your own ads and find collaborators.                                  |
| 4        | Agent Workspace  | Ask common questions for free, or use the AI assistant for unique ones.                                                     |
| 5        | Finish           | You are ready. Replay this tour anytime from the Agent Workspace.                                                           |

| **Test**   | **Scenario and expected result**                                                       |
|------------|----------------------------------------------------------------------------------------|
| **AW-T09** | A first-time user sees the tour offer; Skip closes it; Replay restarts it from step 1. |
| **AW-T10** | A tour target is missing. The step is skipped or centred; the app stays usable.        |

## 6. System Architecture

One tenant-aware application with clear service boundaries. Features share five platform services instead of each building its own messaging, identity and scheduling.

**Architecture flow** — Dashboard and inbound channels → API and webhooks → shared platform and module services → tenant-scoped storage, queues, and external adapters.

### 6.1 Shared platform services (recommended)

| **Service**            | **Responsibility**                                                                                                                                                                                              |
|------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Identity & Consent** | Messaging identity links, contact permissions, opt-outs and consent records. Used by bubbles, Restore Product and Review.                                                                                       |
| **Messaging Gateway**  | Inbound: webhook signature check, idempotent event store. Outbound: channel adapters (Email, SMS, Messenger, WhatsApp), send-time eligibility, rate limits, bounded retries, one delivery log for all purposes. |
| **Scheduler & Queue**  | Delayed jobs (review requests), batch sends (restock), retries, restock detection.                                                                                                                              |
| **Realtime**           | Server-sent events per business for bubble.created, bubble.updated and bubble.removed. Clients reconnect and refetch.                                                                                           |
| **Audit log**          | Batch approvals, exports, consent changes, identity links, role changes.                                                                                                                                        |

| **NOTE Reference stack (non-binding)**<br>A typed API service (for example FastAPI), PostgreSQL, a Redis-backed queue, server-sent events for realtime and a React front end (for example Next.js). Final choice: OD-11. |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

### 6.2 Cross-cutting rules

- **Tenant isolation:** every query, webhook route and cache key carries business_id; cross-tenant tests are part of Definition of Done.

- **Idempotency:** unique constraints on inbound event IDs and outbound idempotency keys; sends use an outbox pattern.

- **No fabricated data:** unknown values display as unavailable, never as guesses.

- **Least data to AI:** the LLM receives the minimum fields needed, with personal data redacted.

- **Time:** store UTC, display in the business time zone.

### 6.3 Data model

| **Entity**                                       | **Key fields**                                                                                                                            | **Used by** |
|--------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------|-------------|
| messaging_identity_links                         | business_id, channel, channel_user_id, customer_id, method, verified_at                                                                   | CG          |
| inbound_message_events                           | business_id, provider_event_id (unique), channel, conversation_id, channel_user_id, received_at                                           | CG, RV      |
| customer_bubbles                                 | business_id, customer_id, conversation_id, last_message_at, seen_at, dismissed_at                                                         | CG          |
| contact_permissions                              | business_id, customer_id, channel, eligible, source, updated_at                                                                           | RP, RV      |
| product_interests                                | business_id, customer_id, product_id, variant_id, requested_at, quantity                                                                  | RP          |
| restock_events                                   | business_id, product_id, variant_id, detected_at, stock_after                                                                             | RP          |
| restock_batches                                  | batch_id, restock_event_id, approved_by, approved_at, template_version, state                                                             | RP          |
| outbound_messages                                | id, business_id, purpose (restock or review), ref_id, channel, idempotency_key (unique), status, provider_message_id, error_code, sent_at | RP, RV      |
| review_settings, review_requests                 | delay_days, send_window, channel_order; request: order_id, due_at, state, token                                                           | RV          |
| review_replies, review_permissions, review_cards | verbatim text, message_id, received_at; consent state; card version                                                                       | RV          |
| ad_insight_snapshots                             | account_id, objective, metrics, synced_at                                                                                                 | MI, MP      |
| faq_entries, chat_sessions, ai_usage_events      | id, aliases, answer; route, tokens, latency, cost                                                                                         | AW          |
| tour_steps, tour_progress                        | step_id, target, message; user_id, completed_at                                                                                           | AW          |

### 6.4 API surface

This table records the v3.0 design surface. For integration, use the [technical API contracts](TRD.md#5-api-surface) and check the OpenAPI schema for the running environment. The current frontend uses versioned routes such as `/api/v1/customer-genome/repeat-buyers`, `/api/v1/creator-commerce/reviews/library`, and `/api/v1/agent-workspace/faqs`.

| **Method**     | **Endpoint**                                                  | **Purpose**                                                      |
|----------------|---------------------------------------------------------------|------------------------------------------------------------------|
| POST           | /webhooks/messaging/{channel}                                 | Verified, idempotent inbound events (bubbles and review replies) |
| GET            | /api/realtime/stream                                          | Server-sent events for bubbles                                   |
| GET            | /api/customer-genome/repeat-buyers                            | Repeat Buyers list                                               |
| GET            | /api/customers/{id}/history                                   | Customer history                                                 |
| POST           | /api/customers/{id}/link-identity                             | Link customer action                                             |
| GET, PATCH     | /api/customer-genome/returning-bubbles\[/{id}\]               | List, detail, seen and dismiss                                   |
| GET, POST      | /api/customer-genome/product-interests                        | Waiting-list entries                                             |
| GET            | /api/customer-genome/restocks/{eventId}/preview               | Batch preview                                                    |
| POST           | /api/customer-genome/restocks/{eventId}/notifications         | Owner-confirmed batch (idempotency key required)                 |
| GET, PATCH     | /api/creator-commerce/reviews/settings                        | Review configuration                                             |
| GET            | /api/creator-commerce/reviews\[/{id}\]                        | Review library and detail                                        |
| POST           | /api/creator-commerce/reviews/{id}/card, /permission, /export | Card, consent state, export                                      |
| GET            | /api/creator-commerce/ads/insights                            | Competitor and own-ad insights                                   |
| GET, POST, PUT | /api/workspace/faqs, /chat, /tour, /tour/progress             | FAQ list, chat, tour                                             |

### 6.5 Non-functional targets (recommended)

| **Area**          | **Target**                                                                                                         |
|-------------------|--------------------------------------------------------------------------------------------------------------------|
| **Performance**   | Bubble visible within 5 s (p95) of webhook receipt. Read endpoints under 500 ms (p95).                             |
| **Reliability**   | Webhooks acknowledged quickly and processed asynchronously with at-least-once handling. Availability target 99.5%. |
| **Security**      | HTTPS only, webhook signature verification, secrets in a managed store, RBAC per endpoint, tenant isolation tests. |
| **Privacy**       | Consent audit trail, defined retention and erasure handling (OD-07), personal data minimised for AI.               |
| **Language**      | FAQ and message templates in Bangla and English. UI language: OD-13.                                               |
| **Accessibility** | Bubbles, chat and tour are keyboard operable with sufficient contrast.                                             |
| **Observability** | Structured logs with request IDs, dashboards for delivery outcomes and AI cost.                                    |

## 7. Delivery Plan

Phases are sequenced by dependency, not by calendar. Phase 0 removes the biggest unknowns before the team commits to them.

**Delivery sequence** — Feasibility → foundation → Customer Genome → Creator Commerce → hardening. Agent Workspace can begin after the foundation.

| **Phase**                       | **Scope**                                                                                                                                                                                                                                                   | **Exit criteria**                                                          |
|---------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| **0 Feasibility**<br>Small      | Meta ad data access for Bangladesh commercial ads (OD-06)<br>Messenger and WhatsApp identity and message windows (OD-05)<br>SMS gateway and email provider selection<br>Meta app review and business verification lead time<br>Customer, order and inventory source (OD-01) | Go or no-go recorded for each integration. Decisions OD-01, 05, 06 closed. |
| **1 Foundation**<br>Medium      | Authentication, tenant model, roles, sidebar shell<br>Identity & Consent, Messaging Gateway, Scheduler & Queue, Realtime, Audit log<br>API conventions, logging, CI                                                                                                 | Tenant isolation and idempotency tests pass on the shared services.        |
| **2 Customer Genome**<br>Large  | Data adapter, history, Repeat Buyers<br>Identity linking and Returning Customer Bubbles<br>Restore Product: interests, waiting lists, restock detection, owner-confirmed batches                                                                                    | CG-T01 to T08 and RP-T01 to T08 pass.                                      |
| **3 Creator Commerce**<br>Large | Review first<br>Meta Ads Intelligence on the tier chosen in Phase 0<br>My Ads Performance, Collaboration Finder, optional Influencer view                                                                                                                           | RV, MI, MP, CF tests pass.                                                 |
| **4 Agent Workspace**<br>Medium | FAQ registry and matching<br>Chat routing, AI agent with read-only tools, usage metrics<br>Website tour                                                                                                                                                             | AW-T01 to T10 pass. Can start after Phase 1.                               |
| **5 Hardening**<br>Medium       | Security review, data correctness, failure and load tests<br>Responsive UI, owner acceptance, staged rollout                                                                                                                                                    | Definition of Done met for all modules.                                    |

| **DECISION Suggested first release (recommended)**<br>Customer Genome (history, bubbles, Restore Product), Review and Agent Workspace. Meta Ads Intelligence joins once Phase 0 confirms a viable data tier. |
|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

#### Definition of Done

- All acceptance tests for the feature pass.

- Cross-tenant access test and duplicate-event test pass.

- Empty, error and unavailable-data states are designed and tested.

- Requirements, API and data-model sections updated in this document.

## 8. Decision Register

The table preserves the original questions, owners, and phase dependencies. The linked decision records show the current status.

- **Closed** — OD-03 and OD-11.
- **Applied defaults** — OD-02, OD-04, OD-07, OD-08, OD-09, OD-12, and OD-13. Confirm OD-07 with legal before launch and OD-13 with the owner.
- **Open with interim approaches** — OD-01 uses an adapter boundary, OD-05 uses configurable eligibility, OD-06 uses manual ad intake as the baseline, and OD-10 applies caps and redaction while deferring the provider decision.

| **ID**    | **Decision**                                                                                  | **Why it matters**                      | **Owner**        | **Needed by** |
|-----------|-----------------------------------------------------------------------------------------------|-----------------------------------------|------------------|---------------|
| **[OD-01](decisions/OD-01.md)** | Customer, order and inventory data source and integration method                              | Blocks all of M1 and Restock detection  | Product + Eng    | Phase 0       |
| **[OD-02](decisions/OD-02.md)** | Qualifying-order rules (cancelled, refunded, partial) and the Returning vs Repeat definitions | Accuracy of totals, lists and bubbles   | Product          | Phase 1       |
| **[OD-03](decisions/OD-03.md)** | Tenant model: multi-tenant SaaS or single business                                            | Shapes data model and security          | Product          | Phase 1       |
| **[OD-04](decisions/OD-04.md)** | Bubble persistence and dismissal rules; confirm in-dashboard bubbles only                     | Daily staff experience                  | Product + Design | Phase 2       |
| **[OD-05](decisions/OD-05.md)** | Channel eligibility per provider (Meta windows, WhatsApp templates, SMS and email rules)      | Decides which channel actually delivers | Eng              | Phase 0       |
| **[OD-06](decisions/OD-06.md)** | Meta ad data access tier (official API, provider or manual)                                   | Feasibility of Meta Ads Intelligence    | Eng              | Phase 0       |
| **[OD-07](decisions/OD-07.md)** | Consent capture, retention periods and erasure handling for reviews and chats                 | Legal and trust                         | Product + Legal  | Phase 1       |
| **[OD-08](decisions/OD-08.md)** | Review defaults: delay, send window, reply window, one request per order                      | Review behaviour and cost               | Product          | Phase 3       |
| **[OD-09](decisions/OD-09.md)** | FAQ ownership, editing and review workflow                                                    | Answer quality                          | Product          | Phase 4       |
| **[OD-10](decisions/OD-10.md)** | AI provider and model, cost caps, chat retention, redaction policy                            | Cost and privacy                        | Product + Eng    | Phase 4       |
| **[OD-11](decisions/OD-11.md)** | Technology stack and hosting                                                                  | Build speed and operations              | Eng              | Phase 0       |
| **[OD-12](decisions/OD-12.md)** | Stock-warning thresholds and inventory authority                                              | Restock accuracy                        | Product          | Phase 2       |
| **[OD-13](decisions/OD-13.md)** | UI language or languages                                                                      | Content and layout                      | Product          | Phase 1       |

## 9. SWODAGAR workspace workflow

The quick guide describes a sourcing journey from setting up a business profile to adding supplier listings to a cart. The names and routes below come from that guide. The checked-out Xenovarients frontend defines `/dashboard` and M1–M3 routes. Its route table has no entries for the locale-prefixed SWODAGAR dashboard, onboarding, or research pages. This walkthrough documents the supplied behavior pending confirmation in a SWODAGAR environment.

**Typical flow** — Dashboard → Onboarding → Market Intelligence → Product Search.

### 9.1 Dashboard

Open **Dashboard** (`/en/dashboard`). The page is titled **Workspace**. Use the highlighted next action to pick up where you left off. If you’re new, choose **Open onboarding**. To go straight to market analysis, open **Research**.

The summary cards show how many products you’re tracking, your saved landed cost, and your recorded net financial result. The dashboard builds this summary from your saved workspace activity, so some cards will be empty at first.

### 9.2 Onboarding

Open **Onboarding** (`/en/onboarding`) and answer the AI chat one question at a time. Type your answers or use the quick replies when offered. The chat asks about your business type, location, product idea, investment budget, team size, account type, experience, and main sales channels.

Give a specific product idea, such as *wireless earbuds*. After the chat completes, it saves the onboarding details and opens Market Intelligence with that idea prefilled.

### 9.3 Market Intelligence

Open **Research** from the dashboard (`/en/research`). If you arrive from onboarding with a product idea, analysis starts automatically. Otherwise, enter a product idea and run the analysis.

- Check **demand and trends** to see where interest is concentrated and whether there’s a seasonal peak.
- Review **competition** to see the estimated number and density of competitors and how established the market is.
- Review **prices and risks** to see the estimated local price range in BDT, sourcing options, and risk factors. Check the data quality score when weighing those estimates.

Select **Continue to Products** to carry the same keyword into Product Search.

### 9.4 Product Intelligence

**Product Intelligence** is called **Product Search** on screen (`/en/research/products`). Open it directly to enter a keyword, or continue from Market Intelligence to search for the same product idea automatically.

1. Search for a product across Alibaba, AliExpress, DHgate, Pinduoduo, Xianyu, and SkyBuyBD.
2. Narrow the results by price or shipping time. Compare shortlisted listings side by side and check the supplier ratings and shipping estimates where available.
3. Add the listings you want to keep to your cart. Select **Go to Cart** to review your selections.

### 9.5 Workflow checks

Use these checks in an environment that serves the SWODAGAR routes.

| Workflow | Expected result |
|---|---|
| Dashboard | Saved activity populates tracked product, landed cost, and net financial result summaries. A fresh workspace can have empty summary cards. |
| Onboarding | Typed answers and quick replies advance the interview. Completion saves the profile and opens Market Intelligence with the product idea prefilled. |
| Market Intelligence | Entry from onboarding runs the supplied idea automatically. Direct entry supports manual analysis. Results show demand, trends, competition, BDT pricing, sourcing, risks, and data quality. |
| Product Search | **Continue to Products** carries the keyword into an automatic search. Direct entry supports manual search. Filters and comparison show available supplier and shipping details. |
| Cart | Adding listings and selecting **Go to Cart** shows the chosen listings. |

## Supporting documentation

- [Product requirements](PRD.md), [user flows](USER_FLOW.md), and [UI/UX design](UI_UX_DESIGN.md)
- [System architecture](ARCHITECTURE.md), [technical requirements](TRD.md), and [entity relationships](ERD.md)
- [Development plan](DEVELOPMENT_PLAN.md), [operations runbook](OPERATIONS_RUNBOOK.md), and [staging release checklist](STAGING_RELEASE_CHECKLIST.md)
