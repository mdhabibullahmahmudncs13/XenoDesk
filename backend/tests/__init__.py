"""Test package init.

Runs before ``tests/conftest.py`` and therefore before the app modules are imported.
The app reads its settings at import time, so the test database URL has to be in the
environment before anything imports ``xenovarients.db.session``.
"""

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://xenovarients_app:xenovarients_app@localhost:55432/xenovarients_test",
)
os.environ.setdefault(
    "TEST_ADMIN_DATABASE_URL",
    "postgresql+asyncpg://xenovarients:xenovarients@localhost:55432/xenovarients_test",
)
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-thirty-two-characters-long")
