"""Add tenant-scoped market intelligence snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261119_market_snapshots"
down_revision: str | None = "20261118_embedding_storage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("keyword", sa.String(255), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
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
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_market_snapshots_business_id", "market_snapshots", ["business_id"])
    op.create_index("ix_market_snapshots_keyword", "market_snapshots", ["keyword"])

    op.execute("ALTER TABLE market_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE market_snapshots FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON market_snapshots")
    op.execute(
        "CREATE POLICY tenant_isolation ON market_snapshots "
        "USING (business_id::text = current_setting('app.business_id', true)) "
        "WITH CHECK (business_id::text = current_setting('app.business_id', true))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON market_snapshots")
    op.execute("ALTER TABLE market_snapshots NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE market_snapshots DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_market_snapshots_keyword", table_name="market_snapshots")
    op.drop_index("ix_market_snapshots_business_id", table_name="market_snapshots")
    op.drop_table("market_snapshots")
