# XenoDesk submission answers

Repository snapshot: `cd3bc96` plus the local working tree reviewed on 2026-11-20. Use the English copy below for the screenshot fields.

| Form field | Copy-ready answer |
|---|---|
| MCP Clients / Hosts | No MCP host/client integration is implemented in the product. XenoDesk Agent Workspace uses Python function calls and direct Ollama HTTP calls. The repository tests use Starlette TestClient to exercise the HTTP MCP server contract. |
| Transports used | Select **stdio** and **Streamable HTTP**. Leave **SSE (legacy)** and **WebSocket** unchecked. |
| Reuse, architecture & integration notes | Five stateless, JSON-response Streamable HTTP servers are mounted in the FastAPI process. Tool calls reuse API bearer-token authentication, business membership and role checks via X-Business-Id, and tenant-bound database sessions that roll back. The separate stdio FAQ process takes its tenant from XENODESK_BUSINESS_ID and reuses the Workspace FAQ matcher. API and MCP modules share domain logic, including review lookup and restock eligibility. Per-server health routes and API request correlation are available. The Redis rate limiter is used for outbound messaging. MCP-specific quotas and tool telemetry are future work. |
| Anything else about MCP in this build? | Six optional Python MCP servers expose 18 read-only tools. Write actions remain on the existing authorized API paths. Missing facts are returned explicitly. The repository includes HTTP tool listing, health, and missing-token tests. Agent Workspace MCP hosting and third-party MCP integrations are planned. |
| Open Source Tools & Libraries | MCP Python SDK for tool registration and transports. FastAPI and Starlette for the API and mounted MCP apps. SQLAlchemy, Alembic and PostgreSQL for tenant-scoped data and migrations. pgvector for chat retrieval. Ollama and HTTPX for local model inference, embeddings and HTTP calls. Redis for realtime pub/sub, outbound quotas and scheduler wakeups. Next.js and React for the product UI. |
| Agent Frameworks & Orchestration | Custom Python orchestration in FastAPI. Chat checks the tenant FAQ registry first, then blocks write intents, handles the active-ads count through a deterministic read function, or retrieves tenant embeddings from pgvector and calls Ollama with guarded context. A stub handles Ollama unavailability. Chat usage events record the route, latency and invoked tools. A separate database-backed worker dispatches background jobs. The chat flow has no external agent framework or multi-agent coordinator. |

## Server inventory

All servers use the Python MCP SDK, declared as `mcp==2.3.0` in [backend/pyproject.toml](../backend/pyproject.toml).

| Server | Transport | Registered tools |
|---|---|---|
| [customer_genome](../backend/xenovarients/platform/mcp/customer_genome/server.py) | Streamable HTTP | `get_customer_history`, `list_repeat_buyers`, `get_returning_bubbles`, `link_identity`, `resolve_customer` |
| [restock](../backend/xenovarients/platform/mcp/restock/server.py) | Streamable HTTP | `list_waiting_lists`, `list_restock_events`, `preview_batch`, `check_eligibility` |
| [reviews](../backend/xenovarients/platform/mcp/reviews/server.py) | Streamable HTTP | `list_reviews`, `review_consent`, `preview_card` |
| [meta_ads](../backend/xenovarients/platform/mcp/meta_ads/server.py) | Streamable HTTP | `search_ads`, `get_ad_details`, `rank_ads` |
| [sourcing](../backend/xenovarients/platform/mcp/sourcing/server.py) | Streamable HTTP | `get_market_prices`, `refresh_demand` |
| [faq](../backend/xenovarients/platform/mcp/faq_server.py) | stdio | `match_faq` |

`link_identity` reports identity evidence without persisting links. `refresh_demand` can fetch an external signal without storing a new snapshot. The product's [realtime event SSE](../backend/xenovarients/api/events.py) is separate from MCP. No Claude Desktop, Cursor, or third-party MCP integration was found in the product sources. The optional Qdrant Compose service is available for experimentation. The current chat retrieval path uses pgvector.

Evidence comes from the [API factory](../backend/xenovarients/main.py), [MCP mounts](../backend/xenovarients/platform/mcp/app.py), [shared MCP auth and tenant scope](../backend/xenovarients/platform/mcp/shared.py), [chat handler](../backend/xenovarients/api/workspace.py), [worker](../backend/xenovarients/jobs/worker.py), [dependencies](../backend/pyproject.toml), [frontend manifest](../frontend/package.json), and [Compose](../docker-compose.yml). The earlier [server design guide](future%20implementation/mcp-servers.md) contains pre-implementation descriptions. Use the current code for server count and transport claims. The [MCP tests](../backend/tests/unit/test_mcp_servers.py) were located, but the local test run stopped during setup because the environment lacked `motor`. Live deployment and desktop-client compatibility were not verified.

See the [future implementation guide](future%20implementation/mcp-host-and-operations.md) for missing capabilities.
