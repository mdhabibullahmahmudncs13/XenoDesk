"""Read-only MCP servers for XenoDesk.

Six servers, eighteen tools, no writes. They read the same platform services the API
uses, with the same tenant and role checks; anything that changes data stays on the
owner-confirmed HTTP endpoints.

The five request-scoped servers are mounted at ``/mcp/<name>`` by
:func:`xenovarients.platform.mcp.app.create_mcp_app`; ``faq`` runs over stdio from
:mod:`xenovarients.platform.mcp.faq_server`.
"""
