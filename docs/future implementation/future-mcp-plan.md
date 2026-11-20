# Future implementation — third-party MCP servers

**Project:** XenoDesk — Customer Genome · Creator Commerce · Agent Workspace
**Place:** `docs/future implementation/`
**Status:** capability layer implemented (see §5a) — the four read-only tools exist, are mounted, and are unit-tested. **No third-party MCP server has been used yet**, so the form's "MCP Servers Used (third-party)" section is answered *none* in §8 and stays empty until a vendor is selected and its URL/token are configured (§5a, last bullet).
**Audience:** engineers adding read-only third-party MCP servers that improve the agent workflow.

These four recommendations extend the custom MCP servers already in `backend/xenovarients/platform/mcp/`. They are **third-party capability MCP servers**, not new XenoDesk modules, and they are optional on purpose (a missing SDK must never break the API, exactly as `[project.optional-dependencies].mcp` is designed).

---

## 1. Shared guardrails (apply to every third-party MCP here)

Reused from `backend/xenovarients/platform/mcp/shared.py` — **no exceptions**:

1. **Read-only for the LLM.** A third-party MCP call is a *tool* the agent may invoke, never a write. Real writes travel over the owner-confirmed FastAPI endpoints (`notifications.py`, `outbound.py`, `ads.py` admin paths), not through the MCP surface. This is why `export_snapshot` (§5) *builds* a snapshot and reports the destination rather than pushing to it.
2. **Tenant-scoped.** `business_id` must be re-derived on every call; a third-party MCP never accepts a tenant argument — it reads the tenant from headers/its own config and restricts to this business.
3. **No invented data.** Missing values return explicit `found: false`, `available: false` with a reason — never a fabricated zero or placeholder.
4. **Plan is the answer; confirm is the action.** A third-party MCP that would change state must instead *plan* the change and let the owner-confirmed endpoint execute it.

---

## 2. Recommendation 1 — Outbound messaging gateway MCP

| Item | Value |
|---|---|
| **Purpose** | The `restock_mcp` batch preview already computes *who* and *what* to send. A gateway MCP turns that approved preview into real sends, closing the loop end-to-end. |
| **Coupled to** | `restock_mcp`, `notifications.py`, `outbound.py` |
| **What it adds** | Read-only gate tools (`list_sendable_batches`, `get_batch_status`, channel/status queries) so the agent can see what's queued; the actual send stays on the owner-confirmed HTTP endpoint that calls the gateway SDK. |
| **Transport** | HTTP/SSE |
| **Priority** | High (closes the preview → send loop; most workflow impact) |
| **Scope in MVP** | Add read-only batch/status tools only; send remains owner-confirmed. |
| **Form row (Section 2)** | Source/Vendor: *to verify* · Endpoints called: `list_sendable_batches`, `get_batch_status` (example names) · Capabilities: `tools` · Called by: Agent Workspace / Agent Workspace chat · Task: "Send the restored-product batch the customer preview approved." |

**Architecture note:** the MCP *plans* the send; the owner-confirmed API *executes*. This is the only way it stays consistent with the project's "MCP tools are read-only" rule.

---

## 3. Recommendation 2 — Demand / product-discovery signal MCP

| Item | Value |
|---|---|
| **Purpose** | Extends the free Google Trends fallback in `sourcing_mcp` with richer daily price/social signals for a keyword, strengthening the Market Intelligence answer. |
| **Coupled to** | `sourcing_mcp`, `platform/market/trends.py` |
| **What it adds** | A read-only `get_enriched_demand(keyword)` that merges the cached Google Trends snapshot with an optional second source (price/social discovery MCP), returning `available: false` with a reason if the extra source is absent. |
| **Transport** | HTTP/SSE |
| **Priority** | Medium-High |
| **Scope in MVP** | New `get_enriched_demand` read-only tool on `sourcing_mcp`; no write, no store. |
| **Form row (Section 2)** | Source/Vendor: *to verify* · Endpoints called: `get_enriched_demand` (example name) · Capabilities: `tools` · Called by: Agent Workspace chat · Task: "Enrich the sourcing demand answer for a keyword within the budget/latency envelope." |

**Data note:** the project already has a free, keyless Google Trends path (`platform/market/trends.py`). A third-party source should degrade gracefully so the single source remains the fallback.

---

## 4. Recommendation 3 — Review / social-listening MCP

| Item | Value |
|---|---|
| **Purpose** | Adds external sentiment/review context on top of the consumer reviews the project already captures via `reviews_mcp`. |
| **Coupled to** | `reviews_mcp` |
| **What it adds** | Read-only social-sentiment/review signals scoped to a keyword or brand, surfaced next to the captured consumer reviews so the LLM can distinguish "our customer's words" from "public noise." |
| **Transport** | HTTP/SSE |
| **Priority** | Medium |
| **Scope in MVP** | New read-only social/listening tool; integrates with `review_consent`-style consent awareness. |
| **Form row (Section 2)** | Source/Vendor: *to verify* · Endpoints called: e.g. `get_sentiment`, `list_social_mentions` (example names) · Capabilities: `tools` · Called by: Agent Workspace chat · Task: "Contextualise a review or product question with external sentiment." |

---

## 5. Recommendation 4 — Analytics / export MCP

| Item | Value |
|---|---|
| **Purpose** | Exports `genome`, `ads`, and `sourcing` snapshots to a spreadsheet/BI destination rather than a chat readout. |
| **Coupled to** | `genome`, `ads`, `sourcing` |
| **What it adds** | Read-only export tools (`export_insights`, `export_snapshot`) that push snapshots to a sheet/BI destination. |
| **Transport** | HTTP/SSE |
| **Priority** | Low–Medium (nice-to-have, not workflow-critical) |
| **Scope in MVP** | One generic `export_snapshot` with a `destination` param; later per-destination tooling. |
| **Form row (Section 2)** | Source/Vendor: *to verify* · Endpoints called: `export_snapshot`, `export_insights` (example names) · Capabilities: `tools` · Called by: Agent Workspace chat · Task: "Persist an insight snapshot to the chosen BI destination." |

---

## 5a. Implementation status

Implemented in `backend/xenovarients/platform/mcp/`:

| Capability | Tool(s) now exposed | Server | Behaviour without a vendor |
|---|---|---|---|
| Outbound messaging gateway | `list_sendable_batches`, `get_batch_status` | `restock` | Local delivery log is the answer; the `gateway` panel is `available: false, reason: "not_configured"`. |
| Demand / product-discovery signal | `get_enriched_demand` | `sourcing` | Cached (or `refresh`-ed live) Google Trends demand is returned; `enrichment` is `available: false`. |
| Review / social-listening | `get_social_sentiment` | `reviews` | Captured-review counts (matching / quotable) are returned; `external` is `available: false`. |
| Analytics / export | `export_snapshot` | `analytics` (new server) | Snapshot of `genome`/`sourcing`/`ads` is returned; `persisted` is always false. |

How it is wired:

- `platform/mcp/external.py` is the only place that talks to a third-party MCP server. It connects over MCP Streamable HTTP using the already-pinned `mcp` 2.3.0 SDK client, so **no vendor SDK is installed and no optional dependency group is needed** until a vendor is chosen. If one ships a Python SDK, add it as its own extra at that point rather than folding it into `mcp`.
- Each capability declares the tools it may be asked for. A tool outside that list is refused with `reason: "tool_not_allowed"` before any request, so a write tool on the third-party server is unreachable through XenoDesk.
- A call is bounded to 10 s. Timeout, connection failure and a tool error are returned as panels with `reason: "timeout"`, `"source_unavailable"` or `"tool_error"`; none of them fail the local tool call.
- Configuration is environment-only, empty by default: `MCP_OUTBOUND_GATEWAY_URL` / `_TOKEN`, `MCP_DEMAND_SIGNAL_URL` / `_TOKEN`, `MCP_SOCIAL_LISTENING_URL` / `_TOKEN`, `MCP_ANALYTICS_EXPORT_URL` / `_TOKEN`. See `backend/.env.example`. Tokens are never included in a tool's answer.
- Still open: choosing the vendors, pointing the four URLs at them, verifying their real tool names against the allowlist, and filling in Section 2 below.

## 6. Recommended order

1. **Outbound messaging gateway** — closes the preview→send loop; highest workflow impact; the gateway MCP adds read-only status tools while `restock_mcp` + `notifications.py`/`outbound.py` keep the confirmed sends.
2. **Demand/product-discovery signal** — materially strengthens the `#sourcing`/`#mci` chat answering with a second, graceful-degrade data source.
3. **Review/social-listening** — contextualises reviews; medium value, lower risk.
4. **Analytics/export** — lowest immediate impact; build once the above are settled.

## 7. Implementation checklist (per recommendation)

- [x] Map a read-only tool set matching the plan (no write tools).
- [x] Add the gateway/source client (`platform/mcp/external.py`) — over the pinned MCP SDK, so no new dependency group is required yet. Add a vendor extra only if a chosen vendor ships an SDK.
- [x] Implement the tool against the plan; return `found: false`/`available: false` for missing data.
- [x] Add unit tests in `backend/tests/unit/test_mcp_servers.py` style (no DB needed).
- [x] Wire the client/config (`core/config.py`, `backend/.env.example`) and keep every source disabled by default.
- [ ] Document the `mcpServers` entry for the Agent Workspace once a vendor URL exists.
- [x] Run `ruff check` + `pytest tests/unit` in `backend/` to keep CI green.

## 8. Submission-form answer key (copy from here once verified)

### Section 1 — MCP Servers Built (existing custom servers, completed)

| Server | Tools | Transport | Language/SDK | Purpose | Tool names |
|---|---|---|---|---|---|
| `customer_genome` | 5 | HTTP | Python / `mcp` 2.3.0 | Customer history, repeat buyers, bubbles, identity | `get_customer_history, list_repeat_buyers, get_returning_bubbles, link_identity, resolve_customer` |
| `restock` | 6 | HTTP | Python / `mcp` 2.3.0 | Waiting lists, restock events, batch preview, eligibility, queued-batch status | `list_waiting_lists, list_restock_events, preview_batch, check_eligibility, list_sendable_batches, get_batch_status` |
| `reviews` | 4 | HTTP | Python / `mcp` 2.3.0 | Review consent, review library, card preview, public sentiment context | `list_reviews, review_consent, preview_card, get_social_sentiment` |
| `meta_ads` | 3 | HTTP | Python / `mcp` 2.3.0 | Competitor/own ad intelligence | `search_ads, get_ad_details, rank_ads` |
| `sourcing` | 3 | HTTP | Python / `mcp` 2.3.0 | Cached market intelligence, live demand refresh, enriched demand | `get_market_prices, refresh_demand, get_enriched_demand` |
| `analytics` | 1 | HTTP | Python / `mcp` 2.3.0 | Export-shaped snapshots of genome, sourcing and ads | `export_snapshot` |
| `faq` | 1 | stdio | Python / `mcp` 2.3.0 | Zero-token FAQ routing | `match_faq` |

### Section 2 — MCP Servers Used (third-party)

**Answer today: none.** No third-party MCP server has ever been contacted by this project. The four capabilities in §2–§5 exist as *clients* (`platform/mcp/external.py`) and their local tools are live, but every call reports `available: false, reason: "not_configured"` until a vendor URL and token are set — so there is no vendor name, no endpoint count and no traffic to claim. The guardrails in §1 rule out inventing one.

Per field of the submission form (leave all five empty; do not click "Add server we used"):

| Form field | What to enter | Why |
|---|---|---|
| Server name | — | No third-party server was called. |
| Source / vendor | — | No vendor selected; the four URL settings are empty in `backend/.env.example`. |
| # endpoints actually called | `0` | `external.call()` is the only outbound path and nobody has configured a URL to reach. |
| Capabilities exposed | — | Nothing consumed from a third party; only the local tools in Section 1. |
| How did you use it / which agent | — | The Agent Workspace chat calls only the seven custom servers in Section 1. |

For reference, if a vendor is later chosen, the capability it would satisfy and the local tool that would reach it (these are *plans*, not usage):

| Planned capability | Vendor | Endpoints a vendor would receive | Capabilities | Called by / task |
|---|---|---|---|---|
| Outbound messaging gateway | *to verify* | one or two read-only batch/status tools (vendor names TBD, added to the allowlist first) | `tools` | Agent Workspace chat — show the approved restock batch's send status |
| Demand / product-discovery signal | *to verify* | one read-only demand/enrichment tool | `tools` | Agent Workspace chat — enrich sourcing demand answers |
| Review / social-listening | *to verify* | one read-only sentiment/mention tool | `tools` | Agent Workspace chat — contextualise review / product questions |
| Analytics/export | *to verify* | one read-only export tool — never called: `export_snapshot` only reports a destination, `persisted: false` | `tools` | Agent Workspace chat — propose a BI destination, not push to it |

To turn a row into a real "used" entry: (1) pick the vendor, (2) set `MCP_*_URL` / `MCP_*_TOKEN` and confirm the vendor's real tool names against the allowlist in `external.py`, (3) call the local tool once against that URL, then (4) fill this section with the exact tool names that answered and the agent that invoked them. Until step 3 succeeds, the section stays empty.
