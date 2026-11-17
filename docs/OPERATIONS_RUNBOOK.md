# Operations Runbook

## Health checks

- `GET /health` confirms the process is serving requests.
- `GET /health/ready` confirms the database connection.
- Check the job runner and database connection pool before restarting workers.

## Safe rollout

1. Run the backend unit and integration suites and the frontend production build.
2. Apply Alembic migrations during the expand step before deploying code that reads new columns.
3. Deploy to internal traffic, then 5%, 25%, and 100% while watching error rate, queue age, and outbound failure rate.
4. Roll back application code first if the error-rate threshold is breached; do not roll back an expand migration until dependent code is removed.

## Incident response

- **Provider outage:** leave outbox rows pending; bounded retry logic records attempts and backoff.
- **Duplicate event:** inspect the unique inbound/idempotency key and do not manually resend.
- **Tenant isolation alert:** stop traffic to the affected endpoint and preserve audit logs before remediation.
- **Stale data:** show the unavailable/stale state; never backfill a guessed value.

## Secrets

Provider tokens and JWT secrets are environment-managed. Never print authorization headers,
access tokens, or decrypted provider credentials in logs or support output.
