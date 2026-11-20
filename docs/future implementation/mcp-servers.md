# Adding custom MCP servers to XenoDesk (hackathon build guide)

**Project:** XenoDesk — Customer Genome · Creator Commerce · Agent Workspace
**Place:** `docs/future implementation/` · **Status:** hackathon implementation guide
**Audience:** engineers building custom MCP servers so the Agent Workspace's LLM can call them as read-only tools.

This document tells you exactly how to build **multiple custom MCP servers** on top of XenoDesk, which servers to build, what each exposes, and how to wire them in. It also serves as the answer key for the "MCP Servers Built" section of the submission form.

---

## 1. What's already in the tree (and what is not MCP)

XenoDesk's AI layer is a **bespoke client**, not MCP:

- `backend/xenovarients/platform/llm/client.py` → `OllamaClient` POSTs directly to `http://localhost:11434/api/chat` and `/api/embed`. A plain HTTP client; **not** an MCP client.
- `backend/xenovarients/platform/llm/guard.py` → `build_prompt(system, user, retrieved)` builds the system + user messages with retrieved chunks marked as untrusted data.

So before you add anything, the submission form's **"MCP Servers Built"** has **0 rows**. What follows is the exact set of custom MCP servers to build.

---

## 2. Transport decision for this project

| Transport | Best fit here | Why |
|---|---|---|
| **HTTP/SSE** | Project-internal servers that share the data tier and must be tenant-scoped | Reuses the existing auth (`X-Business-Id`, Bearer token) and tenant filtering in one FastAPI process. XenoDesk is already an HTTP service (`uvicorn xenovarients.main:app --port 8001`), so a second FastAPI app mounted at `/mcp` is the natural fit. |
| **stdio** | Tiny local helpers the agent/IDE runs itself (e.g. FAQ lookup, routing) | Spawned as a child process of the agent client; no network. Use only for tools that don't touch the data tier or for pure routing. |

**Decision rule for XenoDesk:** internal + tenant-scoped + data-tier-sharing → **HTTP/SSE** (recommended). External or IDE-local helper → `stdio`.

---

## 3. Hard guardrail: MCP tools must be read-only

XenoDesk already enforces that *sending* happens only after owner confirmation (Restore Product RP-07, Review RV-04/RV-05). A custom MCP server is reachable by the LLM, so it must **never** expose a write action on its own:

- MCP tools are **read-only**: they prepare, preview, compute, quote; they never mutate.
- Write actions stay in the FastAPI API behind owner-confirmed batches. An MCP server *prepares and returns what would be sent*; the API *sends*, with consent and eligibility checked at send time.
- MCP tools must never fabricate data: unknown values return an explicit `available: false` / `not_found` style response, never a guessed value.

This is why every tool in §4 is a *read/preview/compute* tool.

---

## 4. Concrete custom MCP servers to build for the hackathon

Each entry documents: purpose, transport, language/SDK, exact tool count, exact tool names (the MCP surface), and where it lives. Tool names map to functionality already present in the corresponding `api/`, `platform/` module or `models/`.

### 4.1 `customer_genome_mcp` — Customer Genome

Reads customer-history, repeat-buyer, and bubble facts for the chat so the LLM can answer "who bought what, when" questions from real rows instead of guessing.

- **Transport:** HTTP/SSE
- **Language/SDK:** Python / `mcp[http]`
- **Purpose (1–2 lines):** Give the LLM customer-history and repeat-buyer facts from real rows during chat, without the model inventing rows from another tenant.
- **Tool count:** 5
- **Exact tools:** `get_customer_history`, `list_repeat_buyers`, `get_returning_bubbles`, `link_identity`, `resolve_customer`
- **Maps to:** `api/genome.py`, `models/customer.py`, identity linking (CG-03, CG-05).
- **Where it lives:** `backend/xenovarients/platform/mcp/customer_genome/server.py`

### 4.2 `restock_mcp` — Restore Product

Prepares Restore Product batch details for the chat: waiting lists, restock events, stock warnings, and a preview of what would be sent — never sends.

- **Transport:** HTTP/SSE
- **Language/SDK:** Python / `mcp[http]`
- **Purpose (1–2 lines):** The LLM can tell a customer their preferred items are back in stock and who qualifies, using real stock and eligibility data.
- **Tool count:** 6
- **Exact tools:** `list_waiting_lists`, `list_restock_events`, `preview_batch`, `check_eligibility`, `list_sendable_batches`, `get_batch_status`
- **Maps to:** `api/restock.py`, `models/restock.py`, `models/product_interest`.
- **Where it lives:** `backend/xenovarients/platform/mcp/restock/server.py`

### 4.3 `review_mcp` — Review / Creator Commerce

Exposes review consent state and verbatim reviews for the chat, and previews marketing cards.

- **Transport:** HTTP/SSE
- **Language/SDK:** Python / `mcp[http]`
- **Purpose (1–2 lines):** The LLM can summarise a customer's review history or draft a card from verbatim words, respecting consent (RV-09/RV-10/RV-12).
- **Tool count:** 4
- **Exact tools:** `list_reviews`, `review_consent`, `preview_card`, `get_social_sentiment`
- **Maps to:** `api/reviews.py`, `models/review.py`, consent-state fields.
- **Where it lives:** `backend/xenovarients/platform/mcp/reviews/server.py`

### 4.4 `meta_ad_mcp` — Meta Ads / Creator Commerce

Accesses Meta ad data through the project's tier model (Tier 1 official, Tier 2 licensed, Tier 3 manual). Read-only.

- **Transport:** HTTP/SSE
- **Language/SDK:** Python / `mcp[http]`
- **Purpose (1–2 lines):** Returns ranking-tagged competitor/own-ad insight for "which ad should I pause?" questions, labelled as AI-relevance/creative-quality (MI-01/MI-03/MI-04).
- **Tool count:** 3
- **Exact tools:** `search_ads`, `get_ad_details`, `rank_ads`
- **Maps to:** `api/ads.py`, `models/ads.py`, `ad_insight_snapshots`.
- **Where it lives:** `backend/xenovarients/platform/mcp/meta_ads/server.py`

### 4.5 `sourcing_mcp` — Sourcing / Market Intelligence

Free, keyless market-intelligence data for the chat: demand trends and Daraz price/listing stats (the same numbers the Market Intelligence module computes) exposed read-only.

- **Transport:** HTTP/SSE
- **Language/SDK:** Python / `mcp[http]`
- **Purpose (1–2 lines):** Answers "what's the price band and demand trend for X in Bangladesh" from the existing free sources into chat.
- **Tool count:** 3
- **Exact tools:** `get_market_prices`, `refresh_demand`, `get_enriched_demand`
- **Maps to:** `api/sourcing.py`, `platform/market/metrics.py`, `platform/market/trends.py`.
- **Where it lives:** `backend/xenovarients/platform/mcp/sourcing/server.py`

### 4.6 `faq_mcp` — Agent Workspace FAQ routing (stdio)

A thin helper the IDE/agent runs locally. It doesn't touch the data tier; it just resolves FAQ IDs/aliases so the chat never calls the LLM for common questions.

- **Transport:** `stdio` (spawned by the agent client)
- **Language/SDK:** Python / `mcp[http]`
- **Purpose (1–2 lines):** Zero-token FAQ routing via exact and normalised fuzzy match.
- **Tool count:** 1
- **Exact tools:** `match_faq`
- **Maps to:** `api/workspace.py`, `models/workspace.py` (`FaqEntry`, `FaqAlias`).
- **Where it lives:** `backend/xenovarients/platform/mcp/faq_server.py`

### 4.7 `analytics_mcp` — Export-shaped snapshots

Returns a snapshot of Customer Genome, Market Intelligence or ad intelligence for export, and reports where an export would go. It builds the snapshot and never pushes it: writing to a destination stays an owner-confirmed action.

- **Transport:** HTTP/SSE
- **Language/SDK:** Python / `mcp[http]`
- **Purpose (1–2 lines):** Answer "what would we export?" from real rows, without writing to a third-party destination.
- **Tool count:** 1
- **Exact tools:** `export_snapshot`
- **Maps to:** `models/customer.py`, `models/restock.py`, `models/sourcing.py`, `models/ads.py`.
- **Where it lives:** `backend/xenovarients/platform/mcp/analytics/server.py`

> To make this a full MCP server (not stdio-only) use `mcp[http]` with a stdio transport; the tool functions stay identical, only the transport wiring changes.

---

## 5. Totals for the submission form

| Server name | Endpoints/tools | Transport | Language/SDK | Purpose (1–2 sentences) | Tool names |
|---|---|---|---|---|---|
| `customer_genome_mcp` | 5 | HTTP/SSE | Python / `mcp[http]` | Reads customer-history, repeat-buyer, and bubble facts for the chat. | `get_customer_history`, `list_repeat_buyers`, `get_returning_bubbles`, `link_identity`, `resolve_customer` |
| `restock_mcp` | 6 | HTTP/SSE | Python / `mcp[http]` | Prepares Restore Product batch details and eligibility for the chat without sending, plus the delivery status of confirmed batches. | `list_waiting_lists`, `list_restock_events`, `preview_batch`, `check_eligibility`, `list_sendable_batches`, `get_batch_status` |
| `review_mcp` | 4 | HTTP/SSE | Python / `mcp[http]` | Exposes review consent state and verbatim reviews so the LLM can draft cards and answer review-history questions, with optional public sentiment context. | `list_reviews`, `review_consent`, `preview_card`, `get_social_sentiment` |
| `meta_ad_mcp` | 3 | HTTP/SSE | Python / `mcp[http]` | Returns ranking-tagged competitor/own-ad insight following the tier model and no-invented-data rule. | `search_ads`, `get_ad_details`, `rank_ads` |
| `sourcing_mcp` | 3 | HTTP/SSE | Python / `mcp[http]` | Exposes free market-intelligence figures read-only into chat, with an optional second demand source. | `get_market_prices`, `refresh_demand`, `get_enriched_demand` |
| `analytics_mcp` | 1 | HTTP/SSE | Python / `mcp[http]` | Builds export-shaped snapshots of genome, sourcing and ads without writing to a destination. | `export_snapshot` |
| `faq_mcp` (stdio) | 1 | stdio | Python / `mcp[http]` | Zero-token FAQ routing so common questions never reach the LLM. | `match_faq` |

**Totals:** 7 servers · 23 tools · 6 × HTTP/SSE + 1 × stdio · 6 × Python/`mcp[http]` + 1 × Python/`mcp[http]`-stdio.

---

## 6. Reusable template — one FastAPI MCP server

Copy this to `backend/xenovarients/platform/mcp/<name>/server.py` for each HTTP/SSE server.

```python
"""Template: a tenant-scoped MCP FastAPI server for XenoDesk.

Run:
    . .venv/bin/activate
    pip install "mcp[http]"
    uvicorn xenovarients.platform.mcp.<name>.server:create_app --port 8010

Feeds the Agent Workspace over HTTP/SSE (recommended for tenant-scoped servers).
"""

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# The MCP protocol SDK:
#     pip install "mcp[http]"
# provides the SSE + JSON-RPC framing and the tool/prompt decorators.

from xenovarients.db.tenant import get_tenant_session
from xenovarients.platform.mcp.shared import json_rpc_success, json_rpc_error

app = FastAPI(
    title="XenoDesk MCP: <server-name>",
    version="0.1.0",
    summary="MCP server for <feature> in XenoDesk.",
)

# Tenant dependency — reuse the project's tenant binding so RLS holds.
async def get_tenant(request: Request) -> "TenantSession":
    session = await get_tenant_session(request)
    return session


# Tool definitions. Each public async function becomes a callable MCP tool.
# All tools are READ-ONLY: they prepare/compute/preview only.
async def list_waiting_interests(session: "TenantSession") -> dict:
    """Return waiting-list entries for this business."""
    # Use the existing service so the numbers already honour OD-02 and
    # tenant isolation.
    return {"count": 0, "items": []}


# Register the tools with your MCP SDK (e.g. @mcp.tool decorator), then map the
# tool name -> python function. Example:
#     @mcp.tool
#     async def list_waiting_interests_tool(session: TenantSession) -> dict:
#         return await list_waiting_interests(session)


class JsonRpcRequest(BaseModel):
    jsonrpc = "2.0"
    id = None
    method = "tools/call"
    params = {"name": "", "arguments": {}}


@app.post("/mcp")
async def mcp_post(request: Request, body: JsonRpcRequest):
    # HTTP/SSE transport: every request carries X-Business-Id so tenant
    # isolation holds even though the server is a separate process.
    session = await get_tenant(request)
    name = body.params.get("name")
    args = body.params.get("arguments", {})
    if name == "list_waiting_interests":
        return json_rpc_success(body.id, await list_waiting_interests(session))
    return json_rpc_error(body.id, -32601, "unknown tool")


@app.get("/mcp/sse")
async def mcp_sse(request: Request):
    async def heartbeat():
        while True:
            yield ": heartbeat\n\n"
            await asyncio.sleep(30)
    return StreamingResponse(heartbeat(), media_type="text/event-stream")


def create_app() -> FastAPI:
    return app
```

---

## 7. How to wire them into the app

1. **Add the route module** under `backend/xenovarients/platform/mcp/<name>/server.py` (or a single `platform/mcp.py` that exposes all servers).
2. **Mount in `create_app()`** in `backend/xenovarients/main.py`, right after the existing routers:

   ```python
   # MCP servers (read-only, tenant-scoped). Add under "future implementation".
   mcp_app = create_mcp_app()          # registers /mcp and /mcp/sse
   app.mount("/mcp", mcp_app, name="mcp")
   ```

   Mounting keeps the servers inside one FastAPI process and one middleware stack, so auth and RLS apply uniformly.
3. **Register in `docker-compose.yml`** as a separate service (or run alongside uvicorn) if the server must be a separate process.
4. **Point the Agent Workspace client** at `http://<host>:8010/mcp` (HTTP/SSE) or a stdio-config entry for the FAQ helper.
5. **Add a unit/contract test** per tool in `backend/tests/unit/` and a CI entry (`make lint` + `pytest tests/unit` in the `backend/` venv).

---

## 8. Implementation checklist

- [ ] Install `mcp[http]` into the MCP server's own venv (not the shared backend).
- [ ] Create `backend/xenovarients/platform/mcp/<name>/server.py` from §6's template.
- [ ] Implement read-only tools; keep write actions out of MCP and in the owner-confirmed API.
- [ ] Reuse the tenant dependency so RLS holds.
- [ ] Add a `/health/dependencies`-style probe to the new app.
- [ ] Add a golden-set / contract test in CI.
- [ ] Mount in `create_app()` and run `make lint` + `pytest tests/unit`.
- [ ] Register in `docker-compose.yml` if a separate process.
- [ ] Document the new tools in the Agent Workspace UX (no invented data guard).

---

## 9. CI / deployment notes

- **Backend:** `make lint` (ruff) and `pytest tests/unit` in the `backend/` venv must stay green after a new server is added. The LLM is an optional dependency — Ollama down must never fail core product.
- **Deployment:** if a server is a separate process, add it to `docker-compose.yml`; keep Ollama and the vector store optional so a failed MCP server doesn't break core readiness (mirroring the existing "Ollama degraded = core product unaffected" behaviour).
- **Tenant isolation:** every MCP request carries `X-Business-Id`; the server re-derives `business_id` per request and never trusts a body-supplied tenant.
- **Secrets:** MCP servers share the project's environment conventions (`.env`, no defaults, `JWT_SECRET`-style required values); never commit tokens.

---

## 10. Submission-form answer key (copy from here as needed)

### Section 1 — MCP Servers Built

| Server name | Endpoints/tools | Transport | Language/SDK | Purpose (1–2 sentences) | Tool names |
|---|---|---|---|---|---|
| `customer_genome_mcp` | 5 | HTTP/SSE | Python / `mcp[http]` | Reads customer-history, repeat-buyer, and bubble facts for the chat. | `get_customer_history`, `list_repeat_buyers`, `get_returning_bubbles`, `link_identity`, `resolve_customer` |
| `restock_mcp` | 4 | HTTP/SSE | Python / `mcp[http]` | Prepares Restore Product batch details and eligibility for the chat without sending. | `list_waiting_lists`, `list_restock_events`, `preview_batch`, `check_eligibility` |
| `review_mcp` | 3 | HTTP/SSE | Python / `mcp[http]` | Exposes review consent state and verbatim reviews so the LLM can draft cards and answer review-history questions. | `list_reviews`, `review_consent`, `preview_card` |
| `meta_ad_mcp` | 3 | HTTP/SSE | Python / `mcp[http]` | Returns ranking-tagged competitor/own-ad insight following the tier model and no-invented-data rule. | `search_ads`, `get_ad_details`, `rank_ads` |
| `sourcing_mcp` | 2 | HTTP/SSE | Python / `mcp[http]` | Exposes free market-intelligence figures read-only into chat. | `get_market_prices`, `refresh_demand` |
| `faq_mcp` (stdio) | 1 | stdio | Python / `mcp[http]` | Zero-token FAQ routing so common questions never reach the LLM. | `match_faq` |

**Totals:** 6 servers · 18 tools · 5 × HTTP/SSE + 1 × stdio · 6 × Python/`mcp[http]`.

### Section 2 — MCP Servers Used

| Server name | Source/Vendor | Endpoints called | Capabilities consumed | Called by / task |
|---|---|---|---|---|
| *(none in the committed tree — all six are custom-built, see §1)* | — | — | — | — |
| Ollama | Ollama (ollama.ai) | `POST /api/chat`, `POST /api/embed` on `OLLAMA_BASE_URL` | the custom servers call it only for LLM/embedding | Agent Workspace chat + embedding jobs |

> The only existing LLM-layer entry is the direct Ollama client (`platform/llm/client.py`), which is **not** an MCP server. Treat it as the closest equivalent only if the form asks what the LLM layer talks to. The form fields are empty until you add your first MCP server via the template in §6.
