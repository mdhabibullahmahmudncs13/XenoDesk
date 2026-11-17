"""Make review reply ingestion idempotent."""

from collections.abc import Sequence

from alembic import op

revision: str = "1520_review_reply_inbound_unique"
down_revision: str | None = "adb229813959"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_review_replies_inbound_message_id",
        "review_replies",
        ["inbound_message_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_review_replies_inbound_message_id",
        "review_replies",
        type_="unique",
    )
