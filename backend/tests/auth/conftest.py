import pytest

from app.core import queue
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth import utils
from app.modules.auth.models import (
    PasswordResetCode,
)
from tests.helpers import CLIENT_ID, FakeJwksClient


@pytest.fixture
def sent_otps(monkeypatch) -> dict[int, str]:
    """Thay enqueue (CI không có Redis): ghi lại OTP cuối cùng gửi cho từng user_id."""
    sent: dict[int, str] = {}

    async def fake_enqueue(job: str, code_id: int, otp: str) -> None:
        assert job == "send_zalo_otp"
        assert isinstance(otp, queue.SecretArg) and repr(otp) == "'******'"
        async with SessionLocal() as s:
            code = await s.get(PasswordResetCode, code_id)
        assert code is not None
        sent[code.user_id] = str(otp)

    monkeypatch.setattr(queue, "enqueue", fake_enqueue)
    return sent


@pytest.fixture(autouse=True)
def fake_google(monkeypatch) -> None:
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(utils, "_jwks_client", lambda: FakeJwksClient())
