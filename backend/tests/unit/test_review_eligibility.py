from datetime import UTC, datetime

from xenovarients.platform.reviews import _due_at


def test_review_due_time_remains_inside_the_send_window():
    due = _due_at(
        delivery_confirmed_at=datetime(2026, 11, 17, 18, 30, tzinfo=UTC),
        timezone="Asia/Dhaka",
        delay_days=3,
        send_window_start="09:00",
        send_window_end="20:00",
    )
    assert due.hour == 3
