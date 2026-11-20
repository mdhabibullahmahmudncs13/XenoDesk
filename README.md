# XenoDesk

A sourcing and customer-intelligence workspace for small online sellers in Bangladesh.
It takes a business from "here is a product I want to sell" to "here is the market, the
competition, the local price band and what could go wrong".

FastAPI (Python 3.13) + PostgreSQL/pgvector, Redis, MongoDB, and a Next.js 16 frontend.

## What works today

| Area | Status |
| :--- | :--- |
| **Onboarding** — chat that captures the business profile, one question at a time | Live |
| **Market Intelligence** — demand, competition, BDT prices, risks, data-quality score | Live, free sources only |
| **Sourcing profile** — edit the saved details Market Intelligence reads | Live |
| Product Search, Cart | Routes exist; supplier search is not connected |
| **Customer Genome** — repeat buyers, history, bubbles, Restore Product | Live screens over real APIs |
| Creator Commerce, Agent Workspace | Scaffolded screens and APIs; ads, collaboration and influencer screens are deliberately blocked |

### Market Intelligence

`/research` answers three questions from **free, keyless** public sources:

- **Demand and trends** — Google Trends (geo `BD`, 5 years of relative interest):
  current index, quarter-on-quarter direction, peak months, seasonality ratio,
  interest by division, related queries.
- **Competition** — Daraz Bangladesh's public catalogue endpoint: distinct sellers,
  density, HHI concentration, share of sellers with 50+ reviews, median reviews and
  rating, price dispersion.
- **Prices and risks** — p25 / median / p75 / min / max in BDT after outlier removal,
  median discount, plus risk labels (shelf competition, entrenched sellers,
  seasonality, regional concentration, discount dependence) and an explicit
  **"not assessed"** for supplier cost and import/certification.

A **data-quality score** (0–100, from source coverage, sample size and freshness) is
shown per panel and overall, and each run is stored as a tenant-scoped snapshot with
a 12-hour TTL.

The rule the module is built around: **numbers are computed, never generated**. A
source that fails, or a sample that is too small, yields `available: false` with a
reason — never a default or an estimate. The LLM layer never touches these figures.

```http
POST /api/v1/sourcing/research          {"keyword": "wireless earbuds"}
GET  /api/v1/sourcing/research/latest  ?keyword=wireless%20earbuds
```

Both require a bearer token. Snapshots are scoped to the caller's business by
PostgreSQL RLS.

### Customer Genome

The whole Release 1 workflow is live at `/customer-genome`, not scaffolded:

- **Repeat buyers** (`/customer-genome/repeat-buyers`) and **customer history**
  (`/customer-genome/history`) — derived lists and a chronological order timeline
  with date and product filters; figures count qualifying orders only.
- **Returning-customer bubbles** — floated by the shell on every page; expanding one
  shows previous orders, spend and last purchase, plus mark-seen and dismiss.
- **Restore Product** (`/customer-genome/restore-product`, `/waiting-lists`) — staff
  customer search, waiting lists grouped by product *and* variant, and adding a
  customer's interest with channel, address and quantity.
- **Restock events** (`/customer-genome/restock-events`) from the inventory mirror,
  and **batch preview & confirm** per event: recipients, chosen channel, message,
  eligibility with skip reasons, stock warning, owner-only confirm with an
  `Idempotency-Key`, and per-recipient delivery history.
- **Message template** — `GET`/`PUT /api/v1/customer-genome/restock-template`; a save
  creates a new version and deactivates the old one, and a template that promises
  reserved stock is rejected.

```http
GET  /api/v1/customer-genome/repeat-buyers
GET  /api/v1/customers/{id}/history
GET  /api/v1/customer-genome/customers?q=...
GET  /api/v1/customer-genome/products
GET  /api/v1/customer-genome/product-interests
GET  /api/v1/customer-genome/restocks
GET  /api/v1/customer-genome/restocks/{id}/notifications
```

A restock event never sends anything by itself: detection records the event and
notifies the owner, and only an owner-confirmed batch queues messages. Data reaches
these screens only through the `source_sync` and `restock_detection` job handlers, so
a fresh tenant correctly shows empty states until a sync runs. The source is still
`StubSource` behind the `CustomerOrderSource` protocol until OD-01 is answered.

## Quickstart

Requirements: Docker, Python 3.13+, Node 22+.

```bash
# 1. Infrastructure: Postgres (55432), Redis (56379), Mongo (57017),
#    MailHog (1025/8025), Ollama (11435)
docker compose up -d

# 2. Backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # then set JWT_SECRET to 32+ random characters
alembic upgrade head          # also creates the restricted xenovarients_app role

# 3. Frontend
cd ../frontend
npm install
npm run dev                   # http://localhost:3000
```

Then start the API and the job worker in separate terminals:

```bash
cd backend && . .venv/bin/activate
uvicorn xenovarients.main:app --host 127.0.0.1 --port 8001 --reload

# second terminal, same venv
xenovarients-worker
```

- API docs: <http://127.0.0.1:8001/api/docs>
- Health: `/health`, `/health/ready`, `/health/dependencies`
- Create the first account at `/signup`; the workspace needs a signed-in session.
- The frontend calls `http://localhost:8001` by default; override with
  `NEXT_PUBLIC_API_BASE`.

Sign in through `localhost`, not `127.0.0.1` — tokens live in `localStorage` and the
origin must stay stable.

## MCP servers

The six read-only MCP servers are an optional extra: `pip install -e ".[mcp]"`. Without
it the API is unchanged; with it, five of them are mounted inside the API process at
`/mcp/<server>` — `customer_genome`, `restock`, `reviews`, `meta_ads`, `sourcing` — over
Streamable HTTP, using the same `Authorization: Bearer …` and `X-Business-Id` headers
as the API. The sixth runs over stdio and takes its tenant from the environment:

```bash
XENODESK_BUSINESS_ID=<business uuid> python -m xenovarients.platform.mcp.faq_server
```

Every tool is read-only: they preview, compute or report, and never write.

## Configuration

All settings come from the environment (`backend/.env`, see
[`backend/.env.example`](backend/.env.example)). There are no secret defaults:
`JWT_SECRET` is required and must be at least 32 characters.

Two database URLs are intentional:

- `DATABASE_URL` — the app connects as `xenovarients_app`, a non-owner role that is
  subject to Row Level Security.
- `MIGRATION_DATABASE_URL` — Alembic connects as the schema owner, which alone has
  DDL rights.

Provider keys (Meta, SMS, email, hosted LLM) are optional and left empty until the
matching feature is enabled.

## Development checks

```bash
cd backend
ruff check xenovarients tests
pytest tests/unit -q          # no services needed
pytest -q                     # full suite, needs Postgres + Redis

cd ../frontend
npx tsc --noEmit
npm run build
```

CI runs `ruff`, the unit suite and the frontend build on every push and pull request
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Layout

```
backend/
  xenovarients/
    api/           routers: auth, sourcing, genome, reviews, ads, workspace, …
    models/        SQLAlchemy models (tenant-scoped by default)
    platform/      adapters and pure logic: market/, source/, llm/, vector/, …
    jobs/          job runner, handlers and the worker entrypoint
    db/            session, tenant filter, RLS binding
  alembic/         migrations (owner role, RLS policies, app-role grants)
  tests/           unit (no services) and integration (live services)
frontend/
  src/app/         routes
  src/components/  screens, including SourcingWorkspace (onboarding + research)
  src/styles/      one global stylesheet
docs/              PRD, TRD, ERD, architecture, runbook and feature specs
```

## Known limitations

- **Google Trends and Daraz are unofficial endpoints.** They are free but can change
  shape or rate-limit; the UI reports that honestly instead of guessing. A persistent
  429 is retried once, then surfaced. Both live behind small adapters
  (`platform/market/trends.py`, `daraz.py`) so a licensed provider can replace them.
- **Daraz's `robots.txt` disallows `/catalog/`.** The adapter makes one polite request
  per research run, but commercial use needs a licensed data vendor or a partner
  agreement behind the same `fetch_listings()` interface.
- **No supplier cost, landed price, customs duty or certification.** The module says
  "not assessed" rather than estimating them.
- **Customer Genome data is stub-backed until OD-01 is answered.** The screens and
  APIs work, but the customer and order records they read come from `StubSource` via
  the sync job, so a new tenant sees empty states rather than invented rows.

## Documentation

- [`docs/Project.md`](docs/Project.md) — consolidated product requirements
- [`docs/TRD.md`](docs/TRD.md) — technical requirements
- [`docs/SYSTEM_DESIGN.md`](docs/SYSTEM_DESIGN.md) — architecture and data design
- [`docs/xenovarients_features_structure_and_user_workflow.md`](docs/xenovarients_features_structure_and_user_workflow.md) — feature specs and journeys
- [`docs/OPERATIONS_RUNBOOK.md`](docs/OPERATIONS_RUNBOOK.md) — running and troubleshooting
