from datetime import UTC, datetime

from xenovarients.platform.reviews import _due_at


def test_due_at_uses_business_timezone_and_next_send_window():
    due = _due_at(
        delivery_confirmed_at=datetime(2026, 11, 17, 18, 30, tzinfo=UTC),
        timezone="Asia/Dhaka",
        delay_days=3,
        send_window_start="09:00",
        send_window_end="20:00",
    )

    assert due == datetime(2026, 11, 21, 3, 0, tzinfo=UTC)
