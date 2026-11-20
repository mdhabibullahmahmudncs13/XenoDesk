# MongoDB and Neo4j storage integration

**Status:** Planned. The current application uses PostgreSQL, pgvector, and Redis. MongoDB is configured with a trace repository, and Workspace currently records usage events in PostgreSQL. Neo4j would be a read model for Customer Genome.

## MongoDB for Agent Workspace traces

1. Connect the [Workspace chat handler](../../backend/xenovarients/api/workspace.py) to [DocumentRepository](../../backend/xenovarients/platform/documents/repository.py) after the chat transaction commits. Emit a trace for the actual route and outcome, including FAQ, deterministic lookup, model response, blocked request, or provider fallback. Keep PostgreSQL usage events as the primary usage record.
2. Reuse an application-managed MongoDB client and add a short write deadline. Store the verified business ID, request ID, route, outcome, duration, tool names, and UTC timestamp. Keep prompts, tool arguments, customer identifiers, and credentials out of the trace payload.
3. Index business ID and timestamp for lookups. Add a TTL index on `created_at` and configure a retention window. Count failed trace writes and allow the chat response to complete when MongoDB is unavailable. Scope any trace query to the authenticated business. [MongoDB TTL indexes](https://www.mongodb.com/docs/manual/core/index-ttl/)
4. Verify that an authorized chat creates a trace, MongoDB unavailability leaves the chat usable, and test traces expire according to the configured policy. Exercise two businesses when testing trace access.

## Neo4j for Customer Genome co-purchase insights

1. Add Neo4j as an optional service and a backend graph adapter. Keep PostgreSQL as the source of truth. Represent persisted customers, orders, and product variants as `Customer → Order → ProductVariant`. Build relationships from committed order items and apply the existing qualifying-order rules.
2. Enqueue a projection job alongside the order transaction and process it with the existing [job worker](../../backend/xenovarients/jobs/worker.py). Start with a tenant-scoped backfill. Read current PostgreSQL records on each job, upsert nodes by business and record ID, and reconcile removed or changed relationships. Apply uniqueness constraints and make retries idempotent. [Neo4j MERGE documentation](https://neo4j.com/docs/cypher-manual/current/clauses/merge/)
3. Add a read endpoint to the [Genome API](../../backend/xenovarients/api/genome.py) that answers which product variants repeat buyers purchase together. Use parameterized queries and constrain every traversal to the verified business. Return aggregate counts and projection freshness. Show an unavailable state when the projection is missing or unhealthy.
4. Verify co-purchase counts against a seeded PostgreSQL fixture. Cover repeated jobs, edited or deleted orders, nonqualifying orders, and cross-business isolation. Verify existing PostgreSQL workflows with Neo4j disabled.

Select **NoSQL** and **Graph DB** only after their respective product workflows are implemented and verified.
