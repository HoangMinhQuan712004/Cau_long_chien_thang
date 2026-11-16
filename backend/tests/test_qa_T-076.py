# ruff: noqa: E501
"""QA T-076 (API, phần đăng ký / chống SSRF / giới hạn / riêng tư): Web Push.

Góc nhìn độc lập với ``test_web_push.py`` của BACKEND: bảng endpoint giả mạo rộng hơn (userinfo, host giả danh, IP dạng số / hex / IPv6,
cổng, khoảng trắng, ký tự điều khiển, chữ hoa, dấu chấm cuối, nhãn rỗng), không dòng nào được lưu và không lần gửi nào được thử,
lỗi dữ liệu → 422 không bao giờ 500, mọi vai đăng nhập đều dùng được còn khách vãng lai / Origin lạ thì bị chặn, chuyển chủ thiết bị
làm đổi số thiết bị của cả hai tài khoản, một thiết bị lỗi không cản các thiết bị khác, log (mức DEBUG) không chứa endpoint đầy đủ / khóa /
SĐT / họ tên, phản hồi cấu hình không lộ khóa riêng.

Phần chưa có trong nhánh BE lúc viết (nhắc giờ AC8–AC11, đổi sân/giờ AC12, gom thanh toán AC14, phòng AC15–AC16, nhân viên AC17–AC20,
luồng chính không hỏng khi push lỗi AC23) sẽ bổ sung khi BE bàn giao tiếp.
"""

import logging
import uuid

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.web_push import service
from app.modules.web_push.models import PushSubscription
from app.modules.web_push.sender import Message
from tests.conftest import ENQUEUED_JOBS, PUSH, new_customer, unique_phone
from tests.conftest import push_testing as testing
from tests.test_web_push import body, fcm, sub_row, subscribe

API = "/api/v1/push"

GOOD_ENDPOINTS = [
    "https://fcm.googleapis.com/fcm/send/abc",
    "https://fcm.googleapis.com:443/fcm/send/abc",
    "https://updates.push.services.mozilla.com/wpush/v2/abc",
    "https://web.push.apple.com/abc",
    "https://x.push.apple.com:443/abc",
    "https://a.b.push.apple.com/abc",
    "https://abc.notify.windows.com/w/?token=abc",
    "HTTPS://FCM.GOOGLEAPIS.COM/fcm/send/abc",  # chữ hoa vẫn là chính host đó
]
BAD_ENDPOINTS = [
    "http://fcm.googleapis.com/fcm/send/abc",  # không https
    "https://evil.com/x",
    "https://fcm.googleapis.com@evil.com/x",  # userinfo giả danh
    "https://user:pw@fcm.googleapis.com/x",
    "https://fcm.googleapis.com:pw@evil.com/x",
    "https://evil.com/#fcm.googleapis.com",
    "https://evil.com/?h=fcm.googleapis.com",
    "https://fcm.googleapis.com.evil.com/x",
    "https://evilfcm.googleapis.com/x",
    "https://fcm.googleapis.com.:443/x",  # dấu chấm cuối
    "https://fcm.googleapis.com./x",
    "https://push.apple.com/x",  # tên miền gốc (Q7)
    "https://notify.windows.com/x",
    "https://.push.apple.com/x",  # nhãn rỗng, host trùng đúng đuôi
    "https://..push.apple.com/x",  # T-76-1: nhãn rỗng liên tiếp
    "https://x..notify.windows.com/x",
    "https://evilpush.apple.com/x",  # thiếu dấu chấm trước push
    "https://x.push.apple.com.evil.io/x",
    "https://x.push.apple.com:8443/x",  # cổng lạ
    "https://fcm.googleapis.com:80/x",
    "https://127.0.0.1/x",
    "https://[::1]/x",
    "https://[::ffff:127.0.0.1]/x",
    "https://169.254.169.254/latest/meta-data/",
    "https://10.0.0.1/x",
    "https://2130706433/x",  # 127.0.0.1 dạng số
    "https://0x7f000001/x",  # dạng hex
    "https://localhost/x",
    "https://fcm.googleapis.com/x y",  # khoảng trắng
    "https://fcm.googleapis.com/x\r\nHost: evil.com",  # xuống dòng
    "https://fcm.googleapis.com/\tx",
    "https://fcm.googleapis.com\\@evil.com/x",
    "https://fcm.gооgleapis.com/x",  # chữ о Kirin giống chữ Latin
    "ftp://fcm.googleapis.com/x",
    "javascript:alert(1)",
    "//fcm.googleapis.com/x",
    "fcm.googleapis.com/fcm/send/abc",  # thiếu scheme
    "https://",
    "https:///fcm/send/abc",
    "https://fcm.googleapis.com/" + "a" * 1000,  # > 1000 ký tự
]


async def rows_for(endpoint: str) -> int:
    async with SessionLocal() as s:
        return (
            await s.scalar(select(func.count()).where(PushSubscription.endpoint == endpoint)) or 0
        )


async def device_total(user_id: int) -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).where(PushSubscription.user_id == user_id)) or 0


async def user_id_of(endpoint: str) -> int:
    row = await sub_row(endpoint)
    assert row is not None
    return row.user_id


# ---------------------------------------------------------------- AC7: chống SSRF


@pytest.mark.parametrize("endpoint", BAD_ENDPOINTS)
async def test_ac7_forged_endpoints_are_rejected_stored_nowhere_and_never_contacted(
    customer, endpoint
):
    before = len(PUSH.attempts)
    r = await customer.post(f"{API}/subscriptions", json=body(endpoint))
    assert r.status_code == 422, (endpoint, r.status_code, r.text[:200])
    detail = r.json()["detail"]
    # 422 nghiệp vụ {detail:{code}} hoặc 422 kiểm dữ liệu chuẩn (detail là danh sách) đều hợp lệ
    code = detail["code"] if isinstance(detail, dict) else "E-001"
    assert code in ("E-PUSH-1", "E-001"), r.text[:200]
    assert await rows_for(endpoint) == 0, "không được lưu"
    assert len(PUSH.attempts) == before, "không được thử gửi tới host giả"
    if code == "E-PUSH-1":  # thông báo lỗi nghiệp vụ không lặp lại endpoint
        assert endpoint not in r.text


@pytest.mark.parametrize("endpoint", GOOD_ENDPOINTS)
async def test_ac7_known_push_hosts_are_accepted(customer, endpoint):
    endpoint = f"{endpoint}{uuid.uuid4().hex}"
    r = await customer.post(f"{API}/subscriptions", json=body(endpoint))
    assert r.status_code == 201, (endpoint, r.text[:200])
    assert await rows_for(endpoint) == 1
    await customer.request("DELETE", f"{API}/subscriptions", json={"endpoint": endpoint})


async def test_ac7_endpoint_edited_in_db_to_foreign_host_is_not_contacted_at_send_time(customer):
    """Phòng thủ lúc gửi: dòng bị sửa tay sang host lạ thì lần gửi bỏ qua, không 500, không gọi ra ngoài."""
    good = await subscribe(customer)
    uid = await user_id_of(good)
    evil = "https://evil.example.com/steal"
    async with SessionLocal() as s:
        row = await s.scalar(select(PushSubscription).where(PushSubscription.endpoint == good))
        row.endpoint = evil
        await s.commit()
    PUSH.clear()
    async with SessionLocal() as s:
        sent = await service.deliver(s, {uid}, Message(title="t", body="b", url="/hoi-vien"))
    assert sent == 0 and all(x.endpoint != evil for x in PUSH.sent)
    assert evil not in PUSH.attempts, "tuyệt đối không được thử gửi tới host ngoài danh sách"


# ---------------------------------------------------------------- dữ liệu sai → 422, không 500


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"endpoint": fcm()},  # thiếu keys
        {"endpoint": fcm(), "keys": {}},
        {"endpoint": fcm(), "keys": {"p256dh": "x"}},
        {"endpoint": fcm(), "keys": {"auth": "x"}},
        {"endpoint": fcm(), "keys": {"p256dh": "", "auth": "x"}},
        {"endpoint": fcm(), "keys": {"p256dh": "x" * 201, "auth": "x"}},
        {"endpoint": fcm(), "keys": {"p256dh": "x", "auth": "x" * 101}},
        {"endpoint": fcm(), "keys": {"p256dh": 1, "auth": ["x"]}},
        {"endpoint": fcm(), "keys": "abc"},
        {"endpoint": fcm(), "keys": {"p256dh": "x", "auth": "x"}, "device_label": "n" * 101},
        {"endpoint": 123, "keys": {"p256dh": "x", "auth": "x"}},
        {"endpoint": None, "keys": {"p256dh": "x", "auth": "x"}},
        {"endpoint": ["https://fcm.googleapis.com/x"], "keys": {"p256dh": "x", "auth": "x"}},
        {"endpoint": "", "keys": {"p256dh": "x", "auth": "x"}},
    ],
)
async def test_malformed_subscription_bodies_are_422_never_500(customer, payload):
    r = await customer.post(f"{API}/subscriptions", json=payload)
    assert r.status_code == 422, (payload, r.status_code, r.text[:200])


async def test_non_json_and_wrong_types_on_all_writes_are_422(customer):
    for method, path in (("POST", "/subscriptions"), ("DELETE", "/subscriptions")):
        r = await customer.request(
            method,
            f"{API}{path}",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 422, (method, r.status_code)
    for bad in (
        {},
        {"endpoint": ""},
        {"endpoint": 5},
        {"endpoint": None},
        {"endpoint": "x" * 1001},
    ):
        r = await customer.request("DELETE", f"{API}/subscriptions", json=bad)
        assert r.status_code == 422, (bad, r.status_code)


# ---------------------------------------------------------------- vai và Origin


async def test_every_signed_in_role_can_subscribe_and_anonymous_cannot(
    anon, customer, staff, admin
):
    for who in (customer, staff, admin):
        ep = fcm()
        assert (await who.post(f"{API}/subscriptions", json=body(ep))).status_code == 201
        assert (
            await who.request("DELETE", f"{API}/subscriptions", json={"endpoint": ep})
        ).status_code == 204
    assert (await anon.post(f"{API}/subscriptions", json=body(fcm()))).status_code == 401
    assert (
        await anon.request("DELETE", f"{API}/subscriptions", json={"endpoint": fcm()})
    ).status_code == 401
    assert (await anon.post(f"{API}/test")).status_code == 401
    # cookie rác cũng chỉ là khách vãng lai
    anon.cookies.set("access_token", "rac")
    assert (await anon.post(f"{API}/subscriptions", json=body(fcm()))).status_code == 401


async def test_foreign_origin_is_blocked_on_every_write_even_when_signed_in(customer):
    ep = await subscribe(customer)
    evil = {"Origin": "https://evil.example.com"}
    r = await customer.post(f"{API}/subscriptions", json=body(fcm()), headers=evil)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-SEC-1"
    r = await customer.request(
        "DELETE", f"{API}/subscriptions", json={"endpoint": ep}, headers=evil
    )
    assert r.status_code == 403
    assert await sub_row(ep) is not None, "Origin lạ không được xóa thiết bị"
    assert (await customer.post(f"{API}/test", headers=evil)).status_code == 403


# ---------------------------------------------------------------- AC5: số thiết bị khi chuyển chủ


async def test_ac5_moving_a_device_changes_both_accounts_counts_and_never_evicts_others():
    async with new_customer() as a, new_customer() as b:
        eps = [await subscribe(a) for _ in range(10)]
        uid_a = await user_id_of(eps[0])
        assert await device_total(uid_a) == 10
        # B bật trên cùng máy với thiết bị #4 của A
        r = await b.post(f"{API}/subscriptions", json=body(eps[4]))
        assert r.status_code == 200, r.text
        uid_b = (await sub_row(eps[4])).user_id
        assert uid_b != uid_a
        assert await device_total(uid_a) == 9 and await device_total(uid_b) == 1
        # A thêm một máy mới: còn 10, không ai bị đuổi
        new = await subscribe(a)
        assert await device_total(uid_a) == 10
        assert (
            all([await sub_row(e) is not None for e in eps if e != eps[4]])
            and await sub_row(new) is not None
        )
        # Thông báo gửi cho A không còn tới máy đã chuyển chủ
        PUSH.clear()
        async with SessionLocal() as s:
            await service.deliver(s, {uid_a}, Message(title="t", body="b", url="/hoi-vien"))
        assert eps[4] not in {x.endpoint for x in PUSH.sent}
        assert {x.endpoint for x in PUSH.sent} == set(eps) - {eps[4]} | {new}


async def test_ac5_resubscribe_same_account_is_a_noop_for_count_and_resets_fail_count(customer):
    ep = await subscribe(customer)
    uid = await user_id_of(ep)
    async with SessionLocal() as s:
        row = await s.scalar(select(PushSubscription).where(PushSubscription.endpoint == ep))
        row.fail_count = 3
        await s.commit()
    r = await customer.post(f"{API}/subscriptions", json=body(ep, device_label="Máy mới"))
    assert r.status_code == 200
    row = await sub_row(ep)
    assert row.fail_count == 0 and row.device_label == "Máy mới" and await device_total(uid) == 1


# ---------------------------------------------------------------- AC4: gửi thử


async def test_ac4_test_push_with_no_device_is_202_zero_and_sends_nothing():
    async with new_customer() as c:
        ENQUEUED_JOBS.clear()
        r = await c.post(f"{API}/test")
        assert r.status_code == 202 and r.json() == {"devices": 0}
        assert await testing.drain(ENQUEUED_JOBS) == 0


async def test_ac4_test_push_message_has_no_identity_and_goes_to_the_right_area(customer):
    me = await customer.get("/api/v1/auth/me")
    phone = me.json().get("phone") or ""
    ep = await subscribe(customer)
    ENQUEUED_JOBS.clear()
    assert (await customer.post(f"{API}/test")).json()["devices"] == 1
    PUSH.clear()
    await testing.drain(ENQUEUED_JOBS)
    assert [x.endpoint for x in PUSH.sent] == [ep]
    sent = PUSH.sent[0]
    assert sent.body == "Thông báo đã được bật trên thiết bị này" and sent.url == "/hoi-vien"
    text = f"{sent.title} {sent.body} {sent.url} {sent.tag}"
    assert ep not in text and (not phone or phone[-6:] not in text)


# ---------------------------------------------------------------- AC23: một thiết bị lỗi không cản thiết bị khác


async def test_ac23_one_failing_device_does_not_block_the_others_and_nothing_raises():
    async with new_customer() as c:
        eps = [await subscribe(c) for _ in range(4)]
        uid = await user_id_of(eps[0])
    PUSH.clear()
    PUSH.fail(eps[0], "timeout")
    PUSH.fail(eps[1], 500)
    PUSH.fail(eps[2], 410)
    async with SessionLocal() as s:
        sent = await service.deliver(s, {uid}, Message(title="t", body="b", url="/hoi-vien"))
    assert sent == 1 and [x.endpoint for x in PUSH.sent] == [eps[3]]
    assert await sub_row(eps[2]) is None
    assert (await sub_row(eps[0])).fail_count == 1 and (await sub_row(eps[1])).fail_count == 1
    PUSH.clear()


async def test_ac23_deliver_to_unknown_or_empty_user_sets_is_a_noop():
    async with SessionLocal() as s:
        assert await service.deliver(s, set(), Message(title="t", body="b", url="/")) == 0
        assert await service.deliver(s, {2**62}, Message(title="t", body="b", url="/")) == 0


# ---------------------------------------------------------------- AC22: log và phản hồi không lộ gì


async def test_ac22_logs_never_contain_full_endpoint_keys_phone_or_name(caplog):
    phone = unique_phone()
    name = "QA Họ Tên Riêng"
    async with new_customer(phone) as c:
        caplog.set_level(logging.DEBUG)
        ep = fcm()
        keys = {"p256dh": "BPkSECRETKEY" + "z" * 50, "auth": "SECRETAUTH" + "q" * 8}
        r = await c.post(
            f"{API}/subscriptions", json={"endpoint": ep, "keys": keys, "device_label": name}
        )
        assert r.status_code == 201
        uid = await user_id_of(ep)
        ENQUEUED_JOBS.clear()
        await c.post(f"{API}/test")
        await testing.drain(ENQUEUED_JOBS)
        for outcome in (410, 500, "timeout", 301):
            ep2 = fcm()
            await subscribe(c, ep2)
            PUSH.fail(ep2, outcome)
            async with SessionLocal() as s:
                await service.deliver(s, {uid}, Message(title="t", body="b", url="/hoi-vien"))
            PUSH.fail(ep2, None)
        await c.request("DELETE", f"{API}/subscriptions", json={"endpoint": ep})
        await c.post(f"{API}/subscriptions", json=body("https://evil.example.com/" + "x" * 30))
    PUSH.clear()
    log = "\n".join(f"{rec.getMessage()} {rec.args}" for rec in caplog.records)
    for secret in (
        ep,
        keys["p256dh"],
        keys["auth"],
        phone,
        phone[-6:],
        "evil.example.com/xxxx",
        name,
    ):
        assert secret not in log, f"log lộ: {secret[:25]}"
    assert "fcm.googleapis.com" in log, "log vẫn ghi host để truy vết"


async def test_config_never_leaks_the_private_key_and_has_exactly_the_contract_keys(anon):
    r = await anon.get(f"{API}/config")
    assert r.status_code == 200 and set(r.json()) == {"enabled", "public_key"}
    assert settings.VAPID_PRIVATE_KEY and settings.VAPID_PRIVATE_KEY not in r.text
    assert r.json()["public_key"] == settings.VAPID_PUBLIC_KEY


async def test_subscription_responses_contain_only_the_id_and_are_not_cacheable(customer):
    ep = fcm()
    r = await customer.post(f"{API}/subscriptions", json=body(ep))
    assert r.status_code == 201 and set(r.json()) == {"id"} and r.json()["id"] > 0
    assert "no-store" in r.headers.get("cache-control", "")
    r = await customer.post(f"{API}/subscriptions", json=body(ep))
    assert r.status_code == 200 and set(r.json()) == {"id"}
    assert ep not in r.text and "p256dh" not in r.text and "auth" not in r.text


async def test_push_routes_ignore_idempotency_key_header_entirely(customer):
    """Q5: có hay không có Idempotency-Key kết quả như nhau (không phát lại phản hồi cũ)."""
    ep = fcm()
    h = {"Idempotency-Key": uuid.uuid4().hex}
    a = await customer.post(f"{API}/subscriptions", json=body(ep), headers=h)
    b = await customer.post(f"{API}/subscriptions", json=body(ep), headers=h)
    assert (a.status_code, b.status_code) == (201, 200), "cùng khóa vẫn xử lý như lệnh mới (upsert)"
