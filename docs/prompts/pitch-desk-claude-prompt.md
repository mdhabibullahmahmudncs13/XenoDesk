# Prompt for Claude — build the XenoDesk Pitch Desk

Paste everything below the line into Claude Code (run at the repository root, `/home/xenon/Documents/GitHub/Xenovarients`).

---

You are working in the XenoDesk repository: a sourcing and customer-intelligence
workspace for small online sellers in Bangladesh. Stack: FastAPI (Python 3.13) +
PostgreSQL/pgvector, Redis, MongoDB, and a Next.js 16 App Router frontend
(`frontend/`, React 19, TypeScript, **one** global stylesheet).

## Task

Build a **Pitch Desk**: a presentation-grade deck living inside the frontend at the
route `/pitch`, reachable without signing in, meant to be shown full-screen in a demo
or investor call and also exported to PDF.

It is a single self-contained page, not a marketing site and not a dashboard screen.
No backend changes, no new API routes, no database, no auth.

## Read these first (do not guess at facts)

1. `README.md` — what is live today, the market-intelligence and Customer Genome
   sections, the MCP section, and the **Known limitations** section.
2. `docs/Project.md` — module scope (M1 Customer Genome, M2 Creator Commerce,
   M3 Agent Workspace), roles, delivery phases.
3. `docs/ARCHITECTURE.md` and `docs/SYSTEM_DESIGN.md` — the shape of the system you
   will describe on the architecture slide.
4. `docs/decisions/OD-*.md` — which decisions are still open (notably OD-01).
5. `frontend/src/app/[...slug]/page.tsx` — existing route conventions.
6. `frontend/src/components/LandingPage.tsx` — the existing public surface and copy voice.
7. `frontend/src/styles/globals.css` — the design tokens you must reuse
   (`--ink`, `--muted`, `--line`, `--surface`, `--page`, `--brand`, `--brand-hover`,
   `--brand-pale`, `--danger`) and the existing class conventions.

## Hard rule: the deck may not invent anything

This repository's whole culture is "numbers are computed, never generated", and
`available: false` with a reason is a valid answer. The deck follows the same rule.

- **No fabricated traction.** XenoDesk has no paying customers, no revenue, no GMV, no
  user counts, no growth chart, no logos of partners, no testimonials. Never imply
  otherwise, and never invent a number to fill a slide. If a slide needs a business
  figure that does not exist yet, render an explicit placeholder — a dashed card
  reading `TO FILL — <what the number must be>` — so the founder can fill it in.
- **Label maturity honestly** on every slide that claims a capability: `Live`,
  `Scaffolded`, or `Blocked`. Use the README's own status table as the source of truth.
- **State limitations on their own slide** rather than hiding them: Google Trends and
  Daraz are unofficial keyless endpoints; Daraz `robots.txt` disallows `/catalog/` so
  commercial use needs a licensed vendor; supplier cost, landed price, customs duty and
  certification are "not assessed"; Customer Genome reads from `StubSource` until OD-01
  is answered.
- Do not describe M2 Creator Commerce or M3 Agent Workspace as working. Ads,
  collaborations and influencer screens are deliberately blocked.
- Do not claim the third-party MCP integrations are in use: all four are disabled until
  a vendor URL is configured, and the correct answer today is "not configured / none in
  use".

## Deck content (12 slides, in this order)

1. **Title** — `XENODESK`, the line "Know your customers. Act with confidence.", a
   one-sentence positioning statement, and a `TO FILL` block for presenter name, date
   and contact.
2. **The problem** — a small seller in Bangladesh sells through a Facebook page and
   Daraz: order history is scattered, returning buyers are unrecognisable at the moment
   they message, and customers waiting for a restock are lost. Frame it as the seller's
   three questions: what should I sell, who already buys from me, what do I say to them.
3. **Why this is unsolved today** — the tools that answer these questions are built for
   Western DTC stores with a clean Shopify order stream; local sellers have neither the
   data plumbing nor the budget. Keep this qualitative; no market-size number unless a
   figure is supplied.
4. **The product** — three modules on one workspace: M1 Customer Genome, M2 Creator
   Commerce, M3 Agent Workspace. One line each, each with its honest status chip.
5. **Market Intelligence — the differentiator** — free, keyless sources (Google Trends
   geo `BD`, Daraz public catalogue); demand, competition and BDT price band with
   p25/median/p75 and risk labels; a 0–100 data-quality score; 12-hour tenant-scoped
   snapshots. The headline on this slide is the rule: **numbers are computed, never
   generated** — the LLM layer never touches the figures.
6. **Customer Genome — the workflow that is already live** — repeat buyers, customer
   history with date and product filters, returning-customer bubbles, Restore Product
   with waiting lists grouped by product **and** variant, restock events, and
   owner-only batch confirm with an `Idempotency-Key`. Say plainly that nothing is sent
   without a human confirming the batch.
7. **Trust is the product** — tenant isolation via PostgreSQL RLS on a non-owner app
   role, two intentional database URLs (app role vs schema owner for Alembic),
   read-only MCP tooling, no LLM write actions, consent-gated reviews, and
   preview → confirm → result for anything irreversible.
8. **Architecture** — one page, built from CSS boxes and text (no images, no diagram
   library): browser → Next.js → FastAPI → Postgres/pgvector, with Redis, MongoDB, the
   job worker, and the optional MCP layer as side boxes. Label optional parts as
   optional.
9. **What is actually shipped** — a table with three columns: Area / Status / Evidence.
   Rows mirror the README status table, including the routes that exist but are not
   connected (Product Search, Cart) and the blocked ads/collaboration screens.
10. **Limitations and open decisions** — the honest list from the rule above, each with
    the mitigation already in the codebase (adapters behind `fetch_listings()`,
    `CustomerOrderSource` protocol, explicit "not assessed").
11. **Roadmap** — phases taken from `docs/Project.md` §7 only. Do not invent quarters,
    dates, funding milestones or headcount.
12. **Close** — the single sentence you want the audience to remember, the three live
    modules, and a `TO FILL` block for the ask (what you want from this conversation:
    design partners, a pilot, an introduction) plus contact.

## Interaction and presentation requirements

- Full-viewport slide layout: one slide visible at a time, no page scroll.
- Keyboard: `ArrowRight` / `ArrowLeft` / `Space` / `PageDown` / `PageUp` to move,
  `Home` / `End` to jump, `f` to toggle a minimal full-screen presentation mode.
- Visible slide counter (`03 / 12`), a slim progress bar, and previous/next controls
  that are real `<button>` elements with accessible labels.
- Deep links: selecting slide *n* updates `location.hash` to `#slide-n`, and a page
  load with that hash opens on that slide. Back/forward must work.
- `prefers-reduced-motion: reduce` disables transitions. No autoplaying motion, no
  sound, no timers.
- Print: a `@media print` block that renders **all** slides stacked, one per page
  (`break-after: page`), on the light palette, with no controls or progress bar — so
  `Ctrl/Cmd+P → Save as PDF` produces a usable handout.
- Accessible: today's slide is announced via an `aria-live="polite"` region; the deck
  is one `<main>` with `aria-roledescription="slide deck"`; every slide has a heading.
- Must survive a narrow viewport (sidebar-free page, single column, type scaling down
  gracefully) because it will sometimes be shown on a laptop next to a call window.

## Implementation constraints

- Create `frontend/src/components/PitchDesk.tsx` (the deck) and, if it helps, one small
  child component for the slide chrome. Keep it to a **client component** (`"use client"`)
  because of the keyboard and hash handling.
- Register the route by adding `pitch: { title: "Pitch Desk" }` to the `screens` map in
  `frontend/src/app/[...slug]/page.tsx` and rendering `<PitchDesk />` for the key
  `"pitch"`. Nothing else in that file changes.
- Append a clearly-commented `/* Pitch Desk */` section to the end of
  `frontend/src/styles/globals.css`. Reuse the existing tokens; do not restyle existing
  selectors and do not introduce a second stylesheet or CSS framework. The palette is
  the existing one: page `#e8ebe6`, surfaces white, ink `#0e0f0c`, accent `#9fe870`.
- **No new dependencies.** No Tailwind, no framer-motion, no icon packages, no chart
  libraries, no image assets, no fonts. Numbers are set in type, not plotted.
- No API calls, no `fetch`, no auth check — the deck is static content and must render
  identically for a signed-out visitor.
- Do not touch `backend/`, `docker-compose.yml`, `package.json` or any doc outside this
  one. Do not add analytics, SEO metadata, translations, a dark-mode switch, or tests.
- Do not commit or push anything.

## Definition of done

```bash
cd frontend
npx tsc --noEmit
npm run build
```

Both must pass with no new warnings. Then start `npm run dev` and confirm `/pitch`
returns the deck, that arrow keys and the hash deep link move between slides, and that
printing produces one slide per page. Do not click through anything beyond that.

## Report back

1. Files created and changed, with one line each on what they do.
2. The 12 slides as written, one line each, with the status chip you gave it.
3. Every `TO FILL` placeholder you left, listed explicitly — these are the founder's
   homework, and none of them may be guessed.
4. The exact commands you ran and their outcomes; state plainly which checks you did
   not run.
5. Anything in the brief you chose to change, and why.
