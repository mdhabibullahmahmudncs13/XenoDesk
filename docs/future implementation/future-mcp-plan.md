# Future implementation — third-party MCP servers

**Project:** XenoDesk — Customer Genome · Creator Commerce · Agent Workspace
**Place:** `docs/future implementation/`
**Status:** planning stage — recommendations mapped to existing custom MCP servers. Tool names/vendors are **to be verified** before the form's "MCP Servers Used" section is filled.
**Audience:** engineers adding read-only third-party MCP servers that improve the agent workflow.

These four recommendations extend the custom MCP servers already in `backend/xenovarients/platform/mcp/`. They are **third-party capability MCP servers**, not new XenoDesk modules, and they are optional on purpose (a missing SDK must never break the API, exactly as `[project.optional-dependencies].mcp` is designed).

---

## 1. Shared guardrails (apply to every third-party MCP here)

Reused from `backend/xenovarients/platform/mcp/shared.py` — **no exceptions**:

1. **Read-only for the LLM.** A third-party MCP call is a *tool* the agent may invoke, never a write. Real writes travel over the owner-confirmed FastAPI endpoints (`notifications.py`, `outbound.py`, `ads.py` admin paths), not through the MCP surface.
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

## 6. Recommended order

1. **Outbound messaging gateway** — closes the preview→send loop; highest workflow impact; the gateway MCP adds read-only status tools while `restock_mcp` + `notifications.py`/`outbound.py` keep the confirmed sends.
2. **Demand/product-discovery signal** — materially strengthens the `#sourcing`/`#mci` chat answering with a second, graceful-degrade data source.
3. **Review/social-listening** — contextualises reviews; medium value, lower risk.
4. **Analytics/export** — lowest immediate impact; build once the above are settled.

## 7. Implementation checklist (per recommendation)

- [ ] Map a read-only tool set matching the plan (no write tools).
- [ ] Add the gateway/source client to a *new* optional dependency group in `backend/pyproject.toml` (`mcp[gateway]` etc.), keeping `mcp==2.3.0` separate.
- [ ] Implement the tool against the plan; return `found: false`/`available: false` for missing data.
- [ ] Add a unit test in `backend/tests/unit/test_mcp_servers.py` style (no DB needed).
- [ ] Wire the client/config and document the `mcpServers` entry for the Agent Workspace.
- [ ] Run `make lint` + `pytest tests/unit` in `backend/` to keep CI green.

## 8. Submission-form answer key (copy from here once verified)

### Section 1 — MCP Servers Built (existing custom servers, completed)

| Server | Tools | Transport | Language/SDK | Purpose | Tool names |
|---|---|---|---|---|---|
| `customer_genome` | 5 | HTTP | Python / `mcp` 2.3.0 | Customer history, repeat buyers, bubbles, identity | `get_customer_history, list_repeat_buyers, get_returning_bubbles, link_identity, resolve_customer` |
| `restock` | 4 | HTTP | Python / `mcp` 2.3.0 | Waiting lists, restock events, batch preview, eligibility | `list_waiting_lists, list_restock_events, preview_batch, check_eligibility` |
| `reviews` | 3 | HTTP | Python / `mcp` 2.3.0 | Review consent, review library, card preview | `list_reviews, review_consent, preview_card` |
| `meta_ads` | 3 | HTTP | Python / `mcp` 2.3.0 | Competitor/own ad intelligence | `search_ads, get_ad_details, rank_ads` |
| `sourcing` | 2 | HTTP | Python / `mcp` 2.3.0 | Cached market intelligence + live demand refresh | `get_market_prices, refresh_demand` |
| `faq` | 1 | stdio | Python / `mcp` 2.3.0 | Zero-token FAQ routing | `match_faq` |

### Section 2 — MCP Servers Used (third-party / planned)

| Server | Source/Vendor | Endpoints actually called | Capabilities consumed | Called by / task |
|---|---|---|---|---|
| **Outbound messaging gateway** | *to verify* | `list_sendable_batches`, `get_batch_status` (example names) | `tools` | Agent Workspace chat — send the approved restock batch end-to-end |
| **Demand / product-discovery signal** | *to verify* | `get_enriched_demand` (example name) | `tools` | Agent Workspace chat — enrich sourcing demand answers |
| **Review / social-listening** | *to verify* | `get_sentiment`, `list_social_mentions` (example names) | `tools` | Agent Workspace chat — contextualise review / product questions |
| **Analytics/export** | *to verify* | `export_snapshot`, `export_insights` (example names) | `tools` | Agent Workspace chat — persist a snapshot to a BI destination |

> These four are **proposed third-party capability MCP servers, not yet integrated.** Tool names and vendors above are placeholders to be replaced with verified third-party MCP server names once selected. Until then, Section 2 remains empty in the submitted tree.
