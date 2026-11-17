# Staging Release Checklist

This checklist is the execution plan for the work that cannot be proven in the local
workspace. It must be completed against a deployed staging API, database, Redis, worker,
and frontend before production rollout.

## Preconditions

- [ ] Staging Postgres, Redis, worker, API, and frontend URLs are available.
- [ ] Staging secrets are injected through the deployment platform, never committed.
- [ ] A disposable staging tenant and Owner/Admin/Staff accounts exist.
- [ ] Provider adapters point to sandbox/test credentials.
- [ ] Backups and restore destination are confirmed.

## Migration and rollback

1. Record the current migration revision and database backup identifier.
2. Run `alembic upgrade head` against a clean staging database.
3. Run the application smoke checks and API contract checks.
4. Verify the expand/contract rollback procedure on a disposable copy.
5. Confirm no migration is rolled back while dependent application code is live.

## Load and failure

- [ ] Burst signed webhook traffic and verify bubble p95 is at or below 5 seconds.
- [ ] Run concurrent restock previews and confirmations; verify idempotency and no duplicate sends.
- [ ] Run concurrent chat requests; verify tenant and user isolation.
- [ ] Stop a worker during a batch; verify retries do not duplicate outbound messages.
- [ ] Simulate provider outage; verify bounded retries and visible delivery attempts.
- [ ] Restart Redis and verify SSE reconnects and REST state refresh.
- [ ] Exercise database failover and verify inbound events are not lost.

## Accessibility and browser acceptance

- [ ] Run Lighthouse against login, dashboard, repeat buyers, reviews, chat, and tour.
- [ ] Confirm accessibility score is at least 95 on the main screens.
- [ ] Complete a keyboard-only pass for navigation, forms, tables, bubble actions, chat, and tour.
- [ ] Verify unknown values show `Unavailable`, never blank or fabricated zeroes.

## Owner acceptance

- [ ] Owner signs up and reaches the workspace.
- [ ] Owner confirms a restore-product batch after reviewing recipients and skip reasons.
- [ ] Owner configures review settings and verifies consent-gated export.
- [ ] Staff can use read-only chat but cannot access Owner/Admin actions.
- [ ] Owner verifies customer bubbles never expose unresolved identity figures.
- [ ] Owner signs off the Release 1 scope and deferred ads scope.

## Rollout

1. Deploy to internal traffic and watch error rate, queue age, SSE disconnects, and outbound failures.
2. Expand to 5%, then 25%, then 100% only when the previous stage is stable.
3. Roll back application code on breach; retain expand migrations until old code is removed.
4. Record the release, migration, smoke, and owner-acceptance evidence.
