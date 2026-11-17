"""tenant RLS policies and immutability triggers

Revision ID: b2c3d4e5f6a7
Revises: ae2fbad8d2ab
Create Date: 2026-11-17 14:40:00

Enables Row Level Security on every tenant-scoped table and binds each policy to the
``app.business_id`` session variable that ``db/session.py`` sets per request. Also
installs the immutability triggers the ERD requires:

- ``review_replies.content`` is the verbatim customer reply — it must never change.
- ``audit_log`` is append-only — no UPDATE, no DELETE.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "ae2fbad8d2ab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = [
    "ad_account_connections",
    "ad_insight_snapshots",
    "ai_usage_events",
    "audit_log",
    "chat_messages",
    "chat_sessions",
    "collaboration_suggestions",
    "contact_permissions",
    "customer_bubbles",
    "customer_orders",
    "customers",
    "faq_aliases",
    "faq_entries",
    "identity_conflicts",
    "inbound_message_events",
    "message_templates",
    "messaging_identity_links",
    "notifications",
    "order_items",
    "outbound_messages",
    "product_interests",
    "product_variants",
    "products",
    "restock_batches",
    "restock_events",
    "review_cards",
    "review_permissions",
    "review_replies",
    "review_reply_products",
    "review_requests",
    "review_settings",
    "scheduled_jobs",
    "tour_progress",
    "tour_steps",
]


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (business_id::text = current_setting('app.business_id', true)) "
            f"WITH CHECK (business_id::text = current_setting('app.business_id', true))"
        )

    # The app role owns the tables; RLS is bypassed for owners unless FORCE is set.
    # FORCE is applied above, so the app role is subject to the policies like anyone else.
    # Superusers and roles with BYPASSRLS still bypass — that is the intended escape hatch
    # for migrations and manual DBA work.

    op.execute(
        """
        CREATE OR REPLACE FUNCTION xenovarients_forbid_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION xenovarients_forbid_reply_content_change() RETURNS trigger AS $$
        BEGIN
            IF NEW.content IS DISTINCT FROM OLD.content THEN
                RAISE EXCEPTION 'review_replies.content is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    op.execute("DROP TRIGGER IF EXISTS trg_review_replies_immutable_content ON review_replies")
    op.execute(
        """
        CREATE TRIGGER trg_review_replies_immutable_content
        BEFORE UPDATE ON review_replies
        FOR EACH ROW EXECUTE FUNCTION xenovarients_forbid_reply_content_change()
        """
    )

    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_update ON audit_log")
    op.execute(
        """
        CREATE TRIGGER trg_audit_log_no_update
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION xenovarients_forbid_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_update ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS trg_review_replies_immutable_content ON review_replies")
    op.execute("DROP FUNCTION IF EXISTS xenovarients_forbid_reply_content_change()")
    op.execute("DROP FUNCTION IF EXISTS xenovarients_forbid_mutation()")

    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
