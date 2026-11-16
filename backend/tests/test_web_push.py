"""T-076 Web Push: cấu hình, đăng ký / xóa thiết bị, gửi thử, chống SSRF, dọn endpoint chết."""

import uuid

import pytest
from sqlalchemy import select, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.web_push import endpoints, service
from app.modules.web_push.models import PushSubscription
from app.modules.web_push.sender import Message
from tests.conftest import ENQUEUED_JOBS, PUSH, new_customer
from tests.conftest import push_testing as testing

API = "/api/v1/push"


def fcm() -> str:
    return f"https://fcm.googleapis.com/fcm/send/{uuid.uuid4().hex}"


def body(endpoint: str, **extra) -> dict:
    return {"endpoint": endpoint, "keys": {"p256dh": "BPk" + "a" * 60, "auth": "x" * 16}, **extra}


async def sub_row(endpoint: str) -> PushSubscription | None:
    async with SessionLocal() as s:
        return await s.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))


async def subscribe(client, endpoint: str | None = None) -> str:
    endpoint = endpoint or fcm()
    r = await client.post(f"{API}/subscriptions", json=body(endpoint, device_label="iPhone"))
    assert r.status_code == 201, r.text
    return endpoint


@pytest.fixture
def push_off(monkeypatch):
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "")


async def test_config_public(anon, push_off):
    assert (await anon.get(f"{API}/config")).json() == {"enabled": False, "public_key": None}


async def test_config_enabled(anon):
    r = await anon.get(f"{API}/config")
    assert r.status_code == 200
    assert r.json() == {"enabled": True, "public_key": settings.VAPID_PUBLIC_KEY}


async def test_subscribe_upsert_and_move_between_accounts(anon, customer, admin):
    """AC5: endpoint đã có -> 200, chuyển sang tài khoản đang đăng nhập; tài khoản cũ hết nhận."""
    r = await anon.post(f"{API}/subscriptions", json=body(fcm()))
    assert r.status_code == 401
    endpoint = await subscribe(customer)
    first = await sub_row(endpoint)
    assert first.device_label == "iPhone" and first.fail_count == 0
    again = await customer.post(f"{API}/subscriptions", json=body(endpoint))
    assert again.status_code == 200 and again.json() == {"id": first.id}
    moved = await admin.post(f"{API}/subscriptions", json=body(endpoint))
    assert moved.status_code == 200 and moved.json() == {"id": first.id}
    assert (await sub_row(endpoint)).user_id != first.user_id


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/x",
        "https://evil.example.com/push",
        "https://127.0.0.1/push",
        "https://10.0.0.5/push",
        "https://[::1]/push",
        "https://push.apple.com/x",  # tên miền gốc: không khớp *.push.apple.com
        "https://web.push.apple.com.evil.com/x",
        "https://fcm.googleapis.com:8443/x",
        "https://user:pw@fcm.googleapis.com/x",
        "https://fcm.googleapis.com.evil.com/x",
        "fcm.googleapis.com/x",
    ],
)
async def test_bad_endpoint_is_e_push_1(customer, endpoint):
    """AC7: endpoint giả -> 422 E-PUSH-1, không lưu, không gửi request nào."""
    r = await customer.post(f"{API}/subscriptions", json=body(endpoint))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-PUSH-1", r.text
    assert await sub_row(endpoint) is None
    assert endpoint not in PUSH.attempts


def test_allowed_hosts():
    ok = [
        "https://fcm.googleapis.com/fcm/send/a",
        "https://web.push.apple.com/abc",
        "https://wns2-par02p.notify.windows.com/w/?token=abc",
        "https://updates.push.services.mozilla.com/wpush/v2/x",
        "https://FCM.googleapis.com:443/x",
    ]
    assert [endpoints.host_of(e) is not None for e in ok] == [True] * len(ok)
    assert endpoints.host_of("https://notify.windows.com/x") is None


async def test_subscribe_disabled_is_503(customer, push_off):
    r = await customer.post(f"{API}/subscriptions", json=body(fcm()))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "E-PUSH-2"
    r = await customer.post(f"{API}/test")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "E-PUSH-2"


async def test_unsubscribe_only_own_device(customer, admin):
    endpoint = await subscribe(customer)
    r = await admin.request("DELETE", f"{API}/subscriptions", json={"endpoint": endpoint})
    assert r.status_code == 204
    assert await sub_row(endpoint) is not None  # của người khác: không xóa
    r = await customer.request("DELETE", f"{API}/subscriptions", json={"endpoint": endpoint})
    assert r.status_code == 204 and await sub_row(endpoint) is None
    r = await customer.request("DELETE", f"{API}/subscriptions", json={"endpoint": endpoint})
    assert r.status_code == 204  # gửi lại vô hại


async def test_send_test_reaches_own_devices_only(customer, admin):
    """AC4: gửi thử chỉ tới thiết bị của chính tài khoản."""
    mine = [await subscribe(customer), await subscribe(customer)]
    other = await subscribe(admin)
    ENQUEUED_JOBS.clear()
    r = await customer.post(f"{API}/test")
    assert r.status_code == 202 and r.json() == {"devices": 2}
    PUSH.clear()
    assert await testing.drain(ENQUEUED_JOBS) == 1
    assert sorted(s.endpoint for s in PUSH.sent) == sorted(mine)
    assert other not in PUSH.attempts
    assert {s.body for s in PUSH.sent} == {service.TEST_BODY}
    assert {s.url for s in PUSH.sent} == {"/hoi-vien"}
    r = await admin.post(f"{API}/test")  # Admin dùng chung giữa các test: có thể nhiều máy
    assert r.status_code == 202 and r.json()["devices"] >= 1
    await testing.drain(ENQUEUED_JOBS)
    to_other = [x for x in PUSH.sent if x.endpoint == other]
    assert len(to_other) == 1 and to_other[0].url == "/admin"
    assert not set(mine) & {x.endpoint for x in PUSH.sent[2:]}


async def test_send_test_rate_limited():
    async with new_customer() as c:
        await subscribe(c)
        for _ in range(5):
            assert (await c.post(f"{API}/test")).status_code == 202
        r = await c.post(f"{API}/test")
        assert r.status_code == 429 and r.json()["detail"]["code"] == "E-SEC-5"
    ENQUEUED_JOBS.clear()


async def test_ten_devices_per_account():
    """Thiết bị thứ 11 -> xóa thiết bị lâu không dùng nhất."""
    async with new_customer() as c:
        eps = [await subscribe(c) for _ in range(10)]
        async with SessionLocal() as s:  # máy đầu tiên lâu không dùng nhất
            await s.execute(
                update(PushSubscription)
                .where(PushSubscription.endpoint == eps[3])
                .values(last_seen_at=PushSubscription.last_seen_at.op("-")(text_interval()))
            )
            await s.commit()
        await subscribe(c)
        assert await sub_row(eps[3]) is None
        assert all([await sub_row(e) is not None for e in eps if e != eps[3]])


def text_interval():
    from sqlalchemy import text

    return text("interval '1 day'")


async def test_dead_endpoints_are_cleaned():
    """AC23: 404 / 410 -> xóa · 3xx / 500 / timeout -> fail_count, 5 lần liền -> xóa · gửi được
    -> fail_count = 0."""
    async with new_customer() as c:
        gone, flaky, slow, moved = [await subscribe(c) for _ in range(4)]
        user_id = (await sub_row(gone)).user_id
    PUSH.fail(gone, 410)
    PUSH.fail(flaky, 500)
    PUSH.fail(slow, "timeout")
    PUSH.fail(moved, 301)
    msg = Message(title="t", body="b", url="/hoi-vien")
    async with SessionLocal() as s:
        assert await service.deliver(s, {user_id}, msg) == 0
    assert await sub_row(gone) is None
    assert [(await sub_row(e)).fail_count for e in (flaky, slow, moved)] == [1, 1, 1]
    PUSH.fail(flaky, None)
    async with SessionLocal() as s:
        assert await service.deliver(s, {user_id}, msg) == 1
    ok = await sub_row(flaky)
    assert ok.fail_count == 0 and ok.last_success_at is not None
    for _ in range(4):
        async with SessionLocal() as s:
            await service.deliver(s, {user_id}, msg)
    assert await sub_row(slow) is None and await sub_row(moved) is None
    assert await sub_row(flaky) is not None
    for e in (gone, slow, moved):
        PUSH.fail(e, None)


async def test_deliver_skips_when_disabled(push_off):
    async with new_customer() as c:
        endpoint = await subscribe_enabled(c)
        user_id = (await sub_row(endpoint)).user_id
    PUSH.clear()
    async with SessionLocal() as s:
        assert await service.deliver(s, {user_id}, Message("t", "b", "/")) == 0
    assert PUSH.attempts == []


async def subscribe_enabled(client) -> str:
    endpoint = fcm()
    async with SessionLocal() as s:  # push_off chặn API: ghi thẳng
        s.add(
            PushSubscription(
                user_id=await _user_id(client), endpoint=endpoint, p256dh="k", auth="a"
            )
        )
        await s.commit()
    return endpoint


async def _user_id(client) -> int:
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _device_keys() -> tuple[str, str]:
    import base64
    import os

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    pub = (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    )
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
    return b64(pub), b64(os.urandom(16))


async def test_real_sender_encrypts_signs_and_never_follows_redirects():
    """Bộ gửi thật (qua transport giả, không ra mạng): VAPID + aes128gcm; 3xx trả về như lỗi,
    không theo ``Location``; endpoint ngoài danh sách -> không gửi."""
    import httpx

    from app.modules.web_push.sender import Target, WebPushSender

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/moved"):
            return httpx.Response(301, headers={"Location": "https://10.0.0.1/steal"})
        return httpx.Response(201)

    real = WebPushSender(httpx.MockTransport(handler))
    p256dh, auth = _device_keys()
    msg = Message(title="Sắp đến giờ chơi", body="Sân 1 · 18h–19h hôm nay", url="/hoi-vien")
    ok = await real.send(Target(1, 1, "https://fcm.googleapis.com/fcm/send/ok", p256dh, auth), msg)
    assert ok.ok and ok.status == 201
    req = seen[0]
    assert req.headers["authorization"].startswith("vapid t=")
    assert req.headers["content-encoding"] == "aes128gcm" and req.headers["ttl"] == "3600"
    assert "Sân 1".encode() not in req.content and len(req.content) > 100  # đã mã hóa
    moved = await real.send(
        Target(2, 1, "https://fcm.googleapis.com/fcm/send/moved", p256dh, auth), msg
    )
    assert moved.status == 301 and not moved.ok and not moved.gone
    assert [r.url.host for r in seen] == ["fcm.googleapis.com", "fcm.googleapis.com"]
    bad = await real.send(Target(3, 1, "https://10.0.0.1/x", p256dh, auth), msg)
    assert bad.status is None and len(seen) == 2


async def test_push_routes_need_no_idempotency_key(customer):
    """Q5: /push/* không bắt Idempotency-Key; gửi kèm thì bỏ qua."""
    endpoint = fcm()
    r = await customer.post(
        f"{API}/subscriptions", json=body(endpoint), headers={"Idempotency-Key": "abc-123"}
    )
    assert r.status_code == 201, r.text
