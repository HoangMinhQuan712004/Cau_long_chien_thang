import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core import queue
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth.models import (
    AuditAction,
    PasswordResetCode,
    Role,
    User,
)
from app.modules.notifications import zalo
from app.workers import worker
from tests.client import API
from tests.helpers import (
    ADMIN,
    RESET_CONFIRM,
    RESET_REQUEST,
    RESET_VERIFY,
    SIGN_IN,
    anon_post,
    audit_count,
    code_count,
    get_me,
    get_reset_token,
    request_otp,
    rewind_requests,
)


async def test_password_reset_full_flow(customer, anon, sent_otps):
    user = await get_me(customer)
    otp = await request_otp(anon, sent_otps, user)
    assert len(otp) == 6 and otp.isdigit()
    assert await audit_count(AuditAction.PASSWORD_RESET_REQUESTED, user["id"]) == 1

    # SĐT viết dạng khác vẫn là một số (BR-002)
    token = await get_reset_token(anon, "+84 " + user["phone"][1:], otp)
    r = await anon.post(RESET_CONFIRM, json={"reset_token": token, "password": "MatKhau@moi1"})
    assert r.status_code == 204
    assert await audit_count(AuditAction.PASSWORD_RESET_DONE, user["id"]) == 1

    r = await anon.post(SIGN_IN, json={"login": user["phone"], "password": "Password@123"})
    assert r.json()["detail"]["code"] == "E-001"
    r = await anon.post(SIGN_IN, json={"login": user["phone"], "password": "MatKhau@moi1"})
    assert r.status_code == 200

    # Token chỉ dùng một lần
    r = await anon.post(RESET_CONFIRM, json={"reset_token": token, "password": "MatKhau@moi2"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "reset_token_invalid"


async def test_password_reset_unknown_phone_same_response(customer, anon, sent_otps):
    """SĐT chưa đăng ký ⇒ 202 y hệt SĐT có tài khoản, không tạo mã, không gửi."""
    known = await anon.post(RESET_REQUEST, json={"phone": (await get_me(customer))["phone"]})
    unknown = await anon.post(RESET_REQUEST, json={"phone": "0999 000 111"})
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json() == {"resend_after": settings.OTP_RESEND_SECONDS}
    assert len(sent_otps) == 1
    async with SessionLocal() as s:
        assert len((await s.scalars(select(PasswordResetCode))).all()) == 1

    # Tên đăng nhập nhân viên không phải SĐT ⇒ 422 (nhân viên không có SĐT, không nhận mã)
    r = await anon.post(RESET_REQUEST, json={"phone": "nv1.le"})
    assert r.status_code == 422
    # SĐT chưa từng yêu cầu mã ⇒ như SĐT thật chưa yêu cầu
    r = await anon.post(RESET_VERIFY, json={"phone": "0999000999", "otp": "123456"})
    assert r.json()["detail"]["code"] == "otp_expired"


async def test_password_reset_verify_unknown_phone_like_real_wrong_otp(customer, anon, sent_otps):
    """/verify không lộ SĐT: SĐT lạ trả y hệt SĐT thật nhập sai (đếm lùi rồi hết hạn)."""
    user = await get_me(customer)
    otp = await request_otp(anon, sent_otps, user)
    assert (await anon.post(RESET_REQUEST, json={"phone": "0999000444"})).status_code == 202
    wrong = f"{(int(otp) + 1) % 10**6:06d}"

    async def verify(phone: str) -> tuple[int, dict]:
        r = await anon.post(RESET_VERIFY, json={"phone": phone, "otp": wrong})
        return r.status_code, r.json()

    for _ in range(settings.OTP_MAX_ATTEMPTS + 1):
        assert await verify(user["phone"]) == await verify("0999000444")
    assert (await verify("0999000444"))[1]["detail"]["code"] == "otp_expired"

    # Mã giả cũng hết hạn sau OTP_TTL_MINUTES như mã thật
    await rewind_requests(settings.OTP_TTL_MINUTES * 60 + 1)
    assert (await anon.post(RESET_REQUEST, json={"phone": "0999000555"})).status_code == 202
    await rewind_requests(settings.OTP_TTL_MINUTES * 60 + 1)
    assert (await verify("0999000555"))[1]["detail"]["code"] == "otp_expired"


async def test_password_reset_wrong_otp_five_times_cancels(customer, anon, sent_otps):
    user = await get_me(customer)
    otp = await request_otp(anon, sent_otps, user)
    wrong = f"{(int(otp) + 1) % 10**6:06d}"
    for left in range(settings.OTP_MAX_ATTEMPTS - 1, -1, -1):
        r = await anon.post(RESET_VERIFY, json={"phone": user["phone"], "otp": wrong})
        assert r.status_code == 400
        assert r.json()["detail"] == {
            "code": "otp_invalid",
            "message": "Mã xác minh không đúng.",
            "attempts_left": left,
        }
    # Đã hủy: mã đúng cũng không dùng được
    r = await anon.post(RESET_VERIFY, json={"phone": user["phone"], "otp": otp})
    assert r.json()["detail"]["code"] == "otp_expired"

    r = await anon.post(RESET_VERIFY, json={"phone": user["phone"], "otp": "12345"})
    assert r.status_code == 422


async def test_password_reset_otp_expires(customer, anon, sent_otps):
    user = await get_me(customer)
    otp = await request_otp(anon, sent_otps, user)
    async with SessionLocal() as s:
        await s.execute(
            update(PasswordResetCode).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    r = await anon.post(RESET_VERIFY, json={"phone": user["phone"], "otp": otp})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "otp_expired"


async def test_password_reset_resend_limit_and_new_code_cancels_old(customer, anon, sent_otps):
    user = await get_me(customer)
    old = await request_otp(anon, sent_otps, user)

    r = await anon.post(RESET_REQUEST, json={"phone": user["phone"]})
    assert r.status_code == 429
    body = r.json()["detail"]
    assert body["code"] == "otp_rate_limited"
    assert settings.OTP_RESEND_SECONDS - 5 <= body["retry_after"] <= settings.OTP_RESEND_SECONDS
    assert r.headers["retry-after"] == str(body["retry_after"])

    await rewind_requests(settings.OTP_RESEND_SECONDS + 1)
    new = await request_otp(anon, sent_otps, user)
    assert await code_count(user["id"]) == 1
    if new != old:
        r = await anon.post(RESET_VERIFY, json={"phone": user["phone"], "otp": old})
        assert r.json()["detail"]["code"] == "otp_invalid"
    await get_reset_token(anon, user["phone"], new)


@pytest.mark.usefixtures("sent_otps")
async def test_password_reset_concurrent_requests_one_sent(customer):
    """Hai yêu cầu cùng lúc: khóa theo SĐT ⇒ đúng một mã, yêu cầu kia 429."""
    phone = (await get_me(customer))["phone"]

    async def attempt() -> int:
        return (await anon_post(RESET_REQUEST, {"phone": phone})).status_code

    assert sorted(await asyncio.gather(attempt(), attempt(), attempt())) == [202, 429, 429]


@pytest.mark.usefixtures("sent_otps")
async def test_password_reset_hourly_limits(customer, anon, monkeypatch):
    monkeypatch.setattr(settings, "OTP_RESEND_SECONDS", 0)
    phone = (await get_me(customer))["phone"]
    for _ in range(settings.OTP_MAX_PER_HOUR):
        assert (await anon.post(RESET_REQUEST, json={"phone": phone})).status_code == 202
    r = await anon.post(RESET_REQUEST, json={"phone": phone})
    assert r.status_code == 429
    assert 3500 <= r.json()["detail"]["retry_after"] <= 3600
    # Đếm cả SĐT chưa đăng ký
    for _ in range(settings.OTP_MAX_PER_HOUR):
        await anon.post(RESET_REQUEST, json={"phone": "0999000222"})
    assert (await anon.post(RESET_REQUEST, json={"phone": "0999000222"})).status_code == 429

    # Giới hạn theo IP (mọi SĐT cộng lại); IP khác vẫn gửi được
    monkeypatch.setattr(settings, "OTP_IP_MAX_PER_HOUR", 3)
    office = {"X-Forwarded-For": "198.51.100.30"}
    for n in range(3):
        r = await anon.post(RESET_REQUEST, json={"phone": f"099900033{n}"}, headers=office)
        assert r.status_code == 202
    r = await anon.post(RESET_REQUEST, json={"phone": "0999000339"}, headers=office)
    assert r.status_code == 429
    r = await anon.post(
        RESET_REQUEST, json={"phone": "0999000339"}, headers={"X-Forwarded-For": "198.51.100.31"}
    )
    assert r.status_code == 202


async def test_password_reset_token_expires(customer, anon, sent_otps):
    user = await get_me(customer)
    token = await get_reset_token(anon, user["phone"], await request_otp(anon, sent_otps, user))
    async with SessionLocal() as s:
        await s.execute(
            update(PasswordResetCode).values(
                reset_expires_at=datetime.now(UTC) - timedelta(seconds=1)
            )
        )
        await s.commit()
    r = await anon.post(RESET_CONFIRM, json={"reset_token": token, "password": "MatKhau@moi1"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "reset_token_invalid"
    r = await anon.post(RESET_CONFIRM, json={"reset_token": "bia", "password": "MatKhau@moi1"})
    assert r.json()["detail"]["code"] == "reset_token_invalid"


async def test_password_reset_admin_revokes_sessions_and_unlocks(admin, anon, sent_otps):
    """Admin (có SĐT) đặt lại được; mọi phiên quản trị kết thúc, khóa E-002 được gỡ."""
    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.role == Role.ADMIN))
        assert user is not None
        admin_id, old_hash = user.id, user.hashed_password
    wrong = {**ADMIN, "password": "sai-mat-khau"}
    for _ in range(settings.LOGIN_MAX_ATTEMPTS):
        r = await anon.post(SIGN_IN, json=wrong)
    assert r.json()["detail"]["code"] == "E-002"

    try:
        otp = await request_otp(anon, sent_otps, {"id": admin_id, "phone": ADMIN["login"]})
        token = await get_reset_token(anon, ADMIN["login"], otp)
        r = await anon.post(RESET_CONFIRM, json={"reset_token": token, "password": "AdminMoi@2026"})
        assert r.status_code == 204

        r = await admin.get(f"{API}/admin/auth/me")
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "password_changed"
        r = await anon.post(SIGN_IN, json={**ADMIN, "password": "AdminMoi@2026"})
        assert r.status_code == 200
        assert r.json()["kind"] == "admin"
    finally:
        # Trả mật khẩu seed cho các test khác
        async with SessionLocal() as s:
            await s.execute(
                update(User).where(User.id == admin_id).values(hashed_password=old_hash)
            )
            await s.commit()


async def test_zalo_without_keys_logs_otp_in_dev_only(
    customer, anon, sent_otps, caplog, monkeypatch
):
    user = await get_me(customer)
    await request_otp(anon, sent_otps, user)
    async with SessionLocal() as s:
        code_id = await s.scalar(
            select(PasswordResetCode.id).where(PasswordResetCode.user_id == user["id"])
        )
    otp = queue.SecretArg("246810")
    caplog.set_level(logging.INFO)

    # Job chỉ mang id mã: worker tra SĐT nhận mã
    await worker.send_zalo_otp({}, code_id, otp)
    assert f"OTP cho {user['phone']}: 246810" in caplog.text
    # Mã đã bị thay (không còn) ⇒ không gửi
    caplog.clear()
    await worker.send_zalo_otp({}, code_id + 10**6, otp)
    assert "246810" not in caplog.text

    caplog.clear()
    # Chỉ ENV=development mới in mã: staging/production quên đặt ENV cũng không lộ
    for env in ["production", "staging", ""]:
        caplog.clear()
        monkeypatch.setattr(settings, "ENV", env)
        await zalo.send_otp(user["phone"], otp)
        assert "246810" not in caplog.text
        assert "Chưa cấu hình Zalo ZNS" in caplog.text
    assert zalo.mask_phone("0912345678") == "09•••••678"


async def test_enqueue_without_redis_does_not_raise(monkeypatch, caplog):
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setattr(queue, "_pool", None)
    await queue.enqueue("send_zalo_otp", 1, queue.SecretArg("135790"))
    assert "Không đẩy được job send_zalo_otp" in caplog.text
    assert "135790" not in caplog.text


async def test_worker_startup_shows_app_info_logs(capsys):
    """CLI `arq` chỉ cấu hình logger "arq" ⇒ startup phải gắn handler để dev thấy dòng OTP."""
    app_logger = logging.getLogger("app")
    saved_handlers, saved_level = app_logger.handlers[:], app_logger.level
    app_logger.handlers.clear()
    try:
        await worker.startup({})
        await zalo.send_otp("0912345678", queue.SecretArg("482913"))
        assert "OTP cho 0912345678: 482913" in capsys.readouterr().err
    finally:
        app_logger.handlers[:] = saved_handlers
        app_logger.setLevel(saved_level)
