"""Apply the same RLS policies and immutability triggers the Alembic migration applies.

The test suite creates its schema from ``Base.metadata`` rather than running migrations,
so it has to install the database-level guarantees itself — otherwise the tests would
pass while the real deployment's RLS was broken.
"""

from sqlalchemy import text

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


async def install_rls(conn) -> None:
    """Enable RLS and the immutability triggers on a freshly created schema."""
    for table in TENANT_TABLES:
        await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        await conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        await conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
        await conn.execute(
            text(
                f"CREATE POLICY tenant_isolation ON {table} "
                f"USING (business_id::text = current_setting('app.business_id', true)) "
                f"WITH CHECK (business_id::text = current_setting('app.business_id', true))"
            )
        )

    await conn.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION xenovarients_forbid_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION xenovarients_forbid_reply_content_change()
            RETURNS trigger AS $$
            BEGIN
                IF NEW.content IS DISTINCT FROM OLD.content THEN
                    RAISE EXCEPTION 'review_replies.content is immutable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    await conn.execute(
        text("DROP TRIGGER IF EXISTS trg_review_replies_immutable_content ON review_replies")
    )
    await conn.execute(
        text(
            """
            CREATE TRIGGER trg_review_replies_immutable_content
            BEFORE UPDATE ON review_replies
            FOR EACH ROW EXECUTE FUNCTION xenovarients_forbid_reply_content_change()
            """
        )
    )
    await conn.execute(text("DROP TRIGGER IF EXISTS trg_audit_log_no_update ON audit_log"))
    await conn.execute(
        text(
            """
            CREATE TRIGGER trg_audit_log_no_update
            BEFORE UPDATE OR DELETE ON audit_log
            FOR EACH ROW EXECUTE FUNCTION xenovarients_forbid_mutation()
            """
        )
    )


async def drop_rls(conn) -> None:
    for table in TENANT_TABLES:
        await conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
        await conn.execute(text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
        await conn.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
