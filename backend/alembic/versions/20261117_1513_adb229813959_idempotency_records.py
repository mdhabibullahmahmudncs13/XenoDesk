"""idempotency records

Revision ID: adb229813959
Revises: 3d5c4cc0fa3c
Create Date: 2026-11-17 15:13:24.983052+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "adb229813959"
down_revision: str | None = "3d5c4cc0fa3c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.JSON(), nullable=False),
        sa.Column("response_headers", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            name=op.f("fk_idempotency_records_business_id_businesses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_records")),
        sa.UniqueConstraint(
            "business_id", "key", "endpoint", name="uq_idempotency_records_business_id_key_endpoint"
        ),
    )
    op.create_index(
        op.f("ix_idempotency_records_business_id"),
        "idempotency_records",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_idempotency_records_business_id_created_at",
        "idempotency_records",
        ["business_id", "created_at"],
        unique=False,
    )

    # The RLS migration lists the tables that existed when it ran. A table added
    # afterwards needs its own policy, or it is readable by every tenant.
    op.execute("ALTER TABLE idempotency_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE idempotency_records FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON idempotency_records")
    op.execute(
        "CREATE POLICY tenant_isolation ON idempotency_records "
        "USING (business_id::text = current_setting('app.business_id', true)) "
        "WITH CHECK (business_id::text = current_setting('app.business_id', true))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON idempotency_records")
    op.execute("ALTER TABLE idempotency_records NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE idempotency_records DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_idempotency_records_business_id_created_at", table_name="idempotency_records")
    op.drop_index(op.f("ix_idempotency_records_business_id"), table_name="idempotency_records")
    op.drop_table("idempotency_records")
