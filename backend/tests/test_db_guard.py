"""Chốt chặn reset DB của bộ test (không cần DB)."""

import pytest

from tests.db_guard import reset_refusal

URL = "postgresql+asyncpg://u:p@localhost:5432/{}"


@pytest.mark.parametrize(
    ("db", "env", "ci", "allowed"),
    [
        ("caulong_be_test", "development", None, True),
        ("postgres", "development", "true", True),  # CI: DB trong container dùng một lần
        ("caulong_be", "development", None, False),
        ("caulong", "development", "false", False),
        ("caulong_test_backup", "development", None, False),
        ("caulong_be_test", "production", None, False),
        ("postgres", "production", "true", False),
    ],
)
def test_reset_refusal(db, env, ci, allowed):
    reason = reset_refusal(URL.format(db), env, ci)
    assert (reason is None) == allowed
    if not allowed:
        assert db in reason
