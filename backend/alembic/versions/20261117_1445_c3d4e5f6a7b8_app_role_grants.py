"""app role grants

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-17 14:45:00

The application must connect as a role that is NOT superuser and does NOT have BYPASSRLS.
Without this the Row Level Security policies from the previous revision are decorative —
the owner/superuser role silently bypasses them.

This revision creates ``xenovarients_app`` if missing and grants it the DML privileges
the app needs. The role is intentionally not a table owner, so RLS applies to it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "xenovarients_app"
APP_PASSWORD = "xenovarients_app"


def upgrade() -> None:
    op.execute(
        f"DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
        f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}' "
        f"NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE; "
        f"END IF; "
        f"END $$;"
    )
    # Usage on the schema plus DML on every table. The app never creates or alters
    # tables — Alembic runs as the owner role.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    # Default privileges cover tables created by later migrations.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )


def downgrade() -> None:
    # Revoke privileges but keep the role: dropping it needs CREATEROLE + ADMIN
    # options that the migration owner does not normally hold, and a failed
    # downgrade would otherwise abort the whole chain.
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
