# Version 3.1 Implementation Plan

## Phase 1: Sourcing foundation

1. Persist one onboarding profile per business.
2. Add tracked products and saved cart listings.
3. Add tenant-scoped dashboard, onboarding, and cart API routes.
4. Add `/sourcing/dashboard`, `/onboarding`, `/research`, `/research/products`, and `/cart`.
5. Keep `/en/...` as a future-compatible route alias; do not duplicate screen logic.

## Phase 2: Existing module completion

- Preserve Customer Genome, Creator Commerce, and Agent Workspace behavior.
- Complete restock, review, ads, and collaboration provider integrations separately.
- Add the new four-module dashboard only after sourcing summaries are backed by real data.

## Phase 3: External research

- Integrate an approved data provider before showing demand, competitor, or supplier claims.
- Until then, research and product search show explicit unavailable states rather than estimates or mock listings.

## Acceptance

- Onboarding saves and returns the tenant profile.
- Cart operations are tenant-isolated and idempotent.
- Dashboard counts come only from persisted sourcing activity.
- Existing auth, sidebar, and module routes continue to work.
