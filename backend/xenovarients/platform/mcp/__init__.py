"""Read-only MCP servers for XenoDesk.

Seven servers, twenty-three tools, no writes. They read the same platform services the
API uses, with the same tenant and role checks; anything that changes data stays on the
owner-confirmed HTTP endpoints.

The six request-scoped servers are mounted at ``/mcp/<name>`` by
:func:`xenovarients.platform.mcp.app.create_mcp_app`; ``faq`` runs over stdio from
:mod:`xenovarients.platform.mcp.faq_server`.

Four of the tools reach an *optional* third-party MCP source (an outbound gateway, a
demand signal, a social-listening source and an export destination) through
:mod:`xenovarients.platform.mcp.external`. An unconfigured source answers
``available: false`` with the reason, so the API works exactly as before without one.
"""
