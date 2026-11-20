# XenoDesk — The Project Document, in Plain Language

**Version:** 1.0 · 20 November 2026
**Written for:** the person paying for this, the people selling it, the people who will
run it, and anyone who has to explain it in a meeting without opening the code.
**No technical knowledge is assumed.** Every term that matters is explained the first
time it appears, and again in the glossary at the end.

---

## 1. The one-page summary

XenoDesk is a workspace for small online sellers in Bangladesh. It answers three
questions a seller actually has:

1. **"What should I sell?"** — is there demand, who is already selling it, and what does
   it sell for locally?
2. **"Who already buys from me?"** — which customers came back, what did they buy, and
   how much have they spent?
3. **"What do I say to them?"** — a message that reaches the right customers at the right
   moment, without spamming anyone or promising something untrue.

Most tools that do this are built for Western shops with tidy, connected order systems.
A seller here usually has a Facebook page, a Daraz shop, a phone full of chat threads and
an order book. XenoDesk is built for that reality: it works with messy, separate sources,
and where it cannot know something it says so instead of guessing.

**What makes it different is a promise, not a feature:** every number on the screen is
either calculated from a real source or clearly marked as unavailable. Nothing is
estimated to fill a gap, and nothing is sent to a customer without a human pressing
confirm.

**Where it stands today (November 2026):** the first two pieces are real. The product
research tool works on live, free public data, and the customer-history module works
end to end over the system's own data. Reviews, advertising intelligence and the AI
assistant have screens and structure but are not finished. Four things are deliberately
switched off because the business questions behind them are unanswered — and that is a
decision, not an accident.

---

## 2. The problem, described by the person who has it

A seller with 400 orders a month cannot answer simple questions:

- *A customer messages "is the blue one back?"* — the seller has no idea this person
  already bought twice, so the reply is generic and the sale is smaller than it could be.
- *A popular item sells out.* Fifty people asked about it. When it returns, there is no
  list of those fifty, no way to reach them, and no memory of who asked for which size.
- *Should I stock wireless earbuds?* The answer lives in scattered places: a search trend,
  a competitor's listing page, a supplier's price. Nobody has the afternoon to assemble it.
- *Can I advertise this?* The seller has no idea which ads already work in this market,
  and no time to study them.

None of these are hard problems individually. Together they are a full-time job, which is
why small sellers do none of them and lose the repeat business that keeps a shop alive.

---

## 3. Who uses it

| Who | What they do in XenoDesk | What they cannot do |
| :--- | :--- | :--- |
| **Owner** — the business owner | Everything, including the decisions only an owner should make: approving a batch of customer messages, connecting ad accounts | Nothing is hidden from them |
| **Admin** — a trusted manager | Reviews settings, exports, FAQ and tour content, all customer views | Cannot approve restock message batches, cannot connect ad accounts |
| **Staff** — a shop assistant | Sees returning-customer alerts, customer history, links a chat identity to a customer, adds someone to a waiting list | Cannot send anything to customers in bulk, cannot change settings |
| **Customer** — the seller's own buyer | Messages the business, answers a review request, gives or refuses permission | Never sees the workspace at all |

The split is deliberately lopsided. Anything that reaches a customer, or spends money,
belongs to the owner alone.

---

## 4. What it does — the four parts, in plain words

### Part 1 · Sourcing Workspace — "should I sell this?"

The seller types a product idea, in a short conversation that asks one question at a time
(business type, location, budget, experience, where they sell). Then the workspace reports
three things about that product:

- **Demand:** is interest rising or falling, when is the peak season, which parts of the
  country care most.
- **Competition:** how many different sellers are already selling it, how crowded that is,
  and how established they are.
- **Prices and risks:** what it sells for locally, in taka, as a range rather than one
  figure; plus honest warnings such as "this market is seasonal" or "a few sellers
  dominate".

Every report carries a **data-quality score** — a mark out of 100 saying how much to trust
it, based on how many sources answered, how large the sample was, and how recent it is.
Each screen states the time the figures were taken. Reports are kept for 12 hours, then
refreshed.

**Two honesty points that matter commercially:** the demand and competitor data come from
free public sources, not a paid data vendor, and the competitor source is a public listing
page whose site rules disallow automated reading at scale. That is fine for a polite,
low-volume pilot. Selling this feature at scale needs a licensed data supplier plugged into
the same slot — the software is built so that swap is a plug change, not a rewrite.

### Part 2 · Customer Genome — "who already buys from me?"

This is the heart of the product, and the part that is most built.

- **Repeat buyers:** a list of everyone who has ordered twice or more, with how much they
  spent and when they last bought.
- **Customer history:** one customer's full order timeline, filterable by date and product.
- **Returning-customer bubbles:** when a known customer messages the business, a small
  floating card appears in the workspace, on any page, saying this person has bought
  before, how many times, how much, and when. Staff can open the full history from it in
  one click. It does not need the browser's notification permission, and a dismissed card
  comes back if the customer writes again.
- **Restore Product:** staff keep a waiting list of who asked for which item — and which
  *variant*, because "blue, size M" is not "blue, size L". When stock returns, the system
  prepares a message for everyone on that list. **Nothing is sent until the owner reviews
  the list, the channels and the wording and presses confirm once.** The owner sees a
  warning if there is less stock than there are people waiting, and the message is written
  so it never promises a reserved item.

Two small rules do a lot of work here. When the system is not sure which customer a chat
belongs to, it shows no customer data at all and offers staff a "link this person"
button — it never guesses, because showing one customer's spending to another is the kind
of mistake a business does not recover from. And if the same message arrives twice from
the chat platform, the customer still gets one message, not two.

### Part 3 · Creator Commerce — "how do I market this with proof?"

Four pieces, all waiting on business decisions before they can be finished:

- **Reviews:** after a confirmed delivery, ask the customer for a review; keep their exact
  words; ask separately whether the business may publish it, and under what name. A card
  made from a review is labelled as a customer review and never dressed up to look like a
  screenshot of a chat app. If the customer later withdraws permission, future use stops.
- **Competitor ad research:** look up ads already running in this market, show the best
  five with the reasons they were picked, and suggest *original* angles — never a copy.
- **Own ad performance:** connect the business's own ad account read-only, see what is
  actually happening, and rank ads only against others with the same objective. It never
  publishes ads or changes a budget.
- **Collaboration and influencer suggestions:** names to approach, with no automatic
  outreach. The business makes the first move itself.

### Part 4 · Agent Workspace — "help me without a support desk"

A chat assistant with three speeds. Common questions get a written answer written by the
business, at no cost and with no AI involved. Simple factual questions ("how many active
ads do I have?") are answered from the business's own records. Only genuinely new
questions go to an AI, which can look but not touch — it cannot delete a customer, publish
an ad, change a budget or message anyone. It also announces how much each answer cost.

Plus a short guided tour for first-time users, skippable and replayable.

---

## 5. What is actually working, right now

This table is the honest one. It is the same information the engineering team reports to
itself, and it is deliberately unflattering.

| Area | Reality in November 2026 |
| :--- | :--- |
| Sign up, sign in | Working |
| Onboarding conversation | Working |
| Market research (demand, competition, prices, risks, quality score) | **Working on live free public data** |
| Customer repeat-buyer list and history | **Working** |
| Returning-customer bubbles | **Working** |
| Restore Product, waiting lists, owner-confirmed batches | **Working** |
| Product search across supplier marketplaces | Screens exist; no supplier is connected yet |
| Cart | Screen exists; nothing to put in it yet |
| Reviews | Screens and rules specified; sending not live |
| Competitor ads, own ad performance, collaborations, influencers | Deliberately switched off |
| AI assistant and guided tour | Scaffolded |
| Third-party data connections (message gateway, demand signal, social listening, export destination) | Built but **disabled**; none is switched on, so the honest answer to "which outside services do you use?" is "none yet" |

Two details that belong next to this table:

- The customer and order data currently comes from a **stand-in source** — realistic
  sample records, not a real shop's books. Everything around it is real; only the feed is
  temporary. Until the business says where its real order data lives, a new workspace
  correctly shows empty screens rather than invented customers.
- There are no paying customers, no revenue and no usage numbers to report yet. Any
  document or pitch that implies otherwise would be inaccurate.

---

## 6. The five rules the product does not break

These are not features. They are the constraints everything else was designed around,
and they are the reason to trust the output.

1. **Numbers are calculated, never written by an AI.** The AI layer never touches a
   figure. If a source fails or a sample is too small, the screen says "not available"
   and gives the reason. A blank space is preferred to a plausible guess.
2. **Nothing reaches a customer without a human confirming it.** Restock messages and
   review requests are prepared by the system and released by one deliberate action from
   the owner. Stock is never promised on the business's behalf.
3. **The assistant cannot change anything.** It reads. It has no ability to delete, edit,
   publish, spend or send. That limit is enforced in the design, not in a warning message.
4. **One business can never see another's data.** Every record is tied to one business and
   the database itself refuses cross-business reads, not just the screens.
5. **A customer's words are theirs.** Reviews are kept exactly as written, permission is
   recorded and dated, and withdrawing permission stops future use.

---

## 7. What the business still has to decide

Four decisions are genuinely open. Each one blocks something visible, and each one is a
business question, not a coding question.

| Decision | In plain terms | What is waiting on it |
| :--- | :--- | :--- |
| **Where order and stock data comes from** | Does the seller use a shop system with an export, a spreadsheet, or something else? Is stock tracked per size/colour, or only per product? | All customer features. If stock is only tracked per product, the promise "we will tell you about *your* size" cannot be kept — and that has to be said out loud rather than quietly softened |
| **Which channels may actually send** | Facebook and WhatsApp only allow free replies for a short window after a customer writes. Days later, a different, approved message is needed. What are the real rules and accounts? | Whether a restock or review message can reach anyone at all |
| **Competitor ad data** | Official access, a paid data provider, or a person pasting ad links in by hand? | The whole competitor ad feature. A manual version is the current fallback |
| **Which AI, and at what cost ceiling** | Which provider, what monthly cap, what is removed from a question before it is sent | The AI assistant. Cost caps and data redaction are already built in |

Two further defaults are in place and need only a nod: the consent and data-retention
rules (should be confirmed with a lawyer before launch) and the language of the interface
(Bangla, English, or both).

---

## 8. Risks, stated plainly

| Risk | How serious | What is already done about it |
| :--- | :--- | :--- |
| The free public data sources can change shape, slow down or block automated reading | Medium — it undermines the research feature if it becomes the main selling point | Each source sits behind a small, replaceable connector; failures are shown to the user with a reason; a licensed supplier can be swapped in |
| The competitor listing site's own rules disallow bulk automated reading | Medium — a commercial problem, not a technical one | Reading is kept to one polite request per research run; commercial scale needs a partner or licence |
| Customer data depends on a system the business has not named | High — the customer module is the core of the product | Built behind a plug-in boundary; a stand-in feed lets everything be built and tested now |
| Sending messages days after a conversation may be impossible on Facebook/WhatsApp | Medium | Email and SMS are the default; the other two are used only when actually allowed at that moment |
| Cost of AI answers | Low | Most questions are answered without AI; usage and cost are shown per answer |
| Trust damage from one wrong number or one wrong message | High — it is the entire promise | Human confirmation before sending, duplicate-send protection, and "not available" instead of guesses |

---

## 9. The plan

Work is sequenced by dependency, not by calendar. The first stage exists purely to remove
the unknowns above before more is built on top of them.

| Stage | What it means in plain terms |
| :--- | :--- |
| **0 · Feasibility** | Answer the four open questions. Record a go / no-go for each outside connection |
| **1 · Foundation** | Accounts, roles, the workspace shell, and the shared plumbing for messages, scheduling and permissions |
| **2 · Customer Genome** | Order data in, repeat buyers, history, returning-customer alerts, restock outreach |
| **3 · Creator Commerce** | Reviews first, then competitor ads, then own-ad performance, then collaborations |
| **4 · Agent Workspace** | Written answers, factual lookups, the AI assistant, the guided tour |
| **5 · Hardening** | Security review, load testing, real-owner acceptance, staged rollout |

The suggested first release is the customer module, reviews and the assistant. Competitor
ad research joins only once stage 0 proves a legitimate way to get the data.

**Build order note:** the sourcing workspace (research) shipped first because it needs no
outside permission from anyone — no shop system, no ad account, no messaging window. It
was the fastest honest demonstration that the product can produce trustworthy numbers.

---

## 10. How success is judged

Not by pages built, and not by activity. Each feature has a written list of behaviours
that must pass, in front of a person, before it is called done. Examples of the standard:

- A returning customer messages: exactly one alert appears, with the right order count.
- A first-time buyer messages: no alert and no "returning customer" label.
- Two customers with the same name message: the wrong history is never shown.
- The same message from the chat platform arrives twice: the customer still receives one.
- The owner confirms a restock batch twice by mistake: each person still gets one message.
- Stock is lower than demand: a warning appears and the wording makes no promise.
- One business tries to open another business's record: access is refused without revealing
  that the record exists.
- A data source is down: the screen says so, with the time of the last good figures.

A release also counts as done only when the empty, broken and "we do not know" versions of
every screen have been designed and tested — because those are the states a real shop
spends its first week in.

---

## 11. Where the money and effort have gone so far

Stated without spin, because it affects what the next conversation should be about:

- **Where the value is:** the research tool produces genuine, defensible numbers from free
  sources, and the customer module is a complete working loop rather than a mock-up. Those
  two are demonstrable today.
- **Where the cost is:** the parts that touch outside platforms — chat channels, ad
  accounts, shop systems — each need an approval, an account, or a permission that no
  amount of coding can obtain. That is why four features sit switched off.
- **What has not been spent on:** paying for data, paying for messaging, or paying for AI.
  Nothing recurring is being billed today.

---

## 12. Questions people ask

**Is this finished?** No. Two of the four parts are real; one is specified; one is
switched off on purpose. The honest summary is "the parts that need nobody's permission
are built".

**Can I show it to a seller tomorrow?** Yes, for research and the customer history
screens — with the caveat that the customer records are sample data until the business
names its real order system.

**Does it send messages to customers by itself?** Never. It prepares; a person releases.

**Does it use AI to make up numbers?** No. AI is used for wording and for answering open
questions, and it is structurally unable to see or write the figures.

**Does it work in Bangla?** The interface is English today; written answers and message
templates are built to hold Bangla, and the interface language is one of the decisions
waiting for an answer.

**Can it serve more than one business?** Yes. It was designed for many businesses from the
start, with a hard boundary between them.

**What happens to a customer's review if they change their mind?** Publishing stops.
Their original words stay accurate in the record, but they are no longer used publicly.

**Where does the customer data live now?** In the system's own database, fed by a temporary
stand-in source that produces realistic sample records. No real shop's data is involved
yet.

**What is the single biggest risk?** That the customer and order data never gets a clean
source. Everything valuable in the product depends on knowing who bought what.

---

## 13. Glossary

| Word you will hear | What it actually means |
| :--- | :--- |
| **Workspace / tenant** | One business's area. Data from one can never appear in another |
| **Qualifying order** | An order that counts: paid or completed. Cancelled and fully refunded ones do not |
| **Returning customer** | Someone with at least one earlier order — this is what makes the alert appear |
| **Repeat buyer** | Someone with two or more orders — this is what puts them on the list |
| **Bubble** | The small floating card that appears when a known customer messages |
| **Restock event** | An item going from "out of stock" to "available" in the stock record |
| **Waiting list** | The people who asked for a specific item, kept separate per size/colour |
| **Batch** | The whole group of messages prepared for one restock, released together by the owner |
| **Duplicate guard** (idempotency key) | A unique stamp on each send so a double-click, a retry or a replayed message cannot produce a second message |
| **Adapter / connector** | A small replaceable part that talks to one outside system, so the rest of the product does not care which supplier is behind it |
| **RLS** (row-level security) | The database itself refusing to return another business's rows, even if the software asks wrongly |
| **Snapshot** | A saved copy of a research result, valid for 12 hours, with the time it was taken |
| **Scaffolded** | The screens and structure exist; the real behaviour is not finished |
| **Blocked** | Deliberately switched off until a business decision is made — not broken |

---

## 14. Where to read more

| If you want… | Read |
| :--- | :--- |
| The feature list and user journeys, module by module | `docs/xenovarients_features_structure_and_user_workflow.md` |
| The formal requirements, roles and delivery plan | `docs/Project.md` |
| How each screen is supposed to look and behave | `docs/UI_UX_DESIGN.md` |
| The exact journeys, including what happens when something goes wrong | `docs/USER_FLOW.md` |
| What is built today, in engineering's own words | `README.md` |
| The reasoning behind each open decision | `docs/decisions/OD-01.md` … `OD-13.md` |
| How to run and operate it | `docs/OPERATIONS_RUNBOOK.md` |
