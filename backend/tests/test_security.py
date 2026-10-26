"""T-005 mục B / ADR-004: rate limit, Origin check, giới hạn body, idempotency, audit, che SĐT."""

import asyncio
import uuid

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core import ratelimit
from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.idempotency import Idempotency
from app.modules.booking_engine.models import Resource
from tests.conftest import API, ORIGIN, idem

BK = f"{API}/booking"


def resource_body(name: str | None = None) -> dict:
    return {
        "name": name or f"Sân {uuid.uuid4().hex[:8]}",
        "resource_type_code": "thuong",
        "open_time": "05:00",
        "close_time": "22:00",
        "peak_bands": [["17:00", "21:00"]],
    }


async def count_resources(name: str) -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).where(Resource.name == name))


# ------------------------------------------------------------------ SEC1 rate limit


async def test_sec1_global_rate_limit_per_ip(anon, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 120)
    for _ in range(120):
        r = await anon.get(f"{API}/courts")
        assert r.status_code == 200
    r = await anon.get(f"{API}/courts")
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "E-SEC-5"
    assert 1 <= int(r.headers["retry-after"]) <= 60
    # Ngoài /api (health check) không bị tính
    assert (await anon.get("/health")).status_code == 200


async def test_rate_limit_disabled_flag(anon, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 2)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    for _ in range(5):
        assert (await anon.get(f"{API}/courts")).status_code == 200


async def test_rate_limit_uses_forwarded_ip_only_from_trusted_proxies(anon, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 1)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
    # Prod/dev: Caddy -> Next -> API, chỉ Caddy nối IP khách vào cuối XFF -> lấy phần tử cuối.
    # Client tự thêm giá trị giả ở đầu (6.6.6.6 / 7.7.7.7) không đổi được khóa rate limit.
    h1 = {"X-Forwarded-For": "6.6.6.6, 1.1.1.1"}
    h2 = {"X-Forwarded-For": "7.7.7.7, 1.1.1.1"}
    assert (await anon.get(f"{API}/courts", headers=h1)).status_code == 200
    assert (await anon.get(f"{API}/courts", headers=h2)).status_code == 429
    assert (
        await anon.get(f"{API}/courts", headers={"X-Forwarded-For": "2.2.2.2"})
    ).status_code == 200
    # Hai proxy ghi XFF -> phần tử thứ 2 từ cuối
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 2)
    h3 = {"X-Forwarded-For": "6.6.6.6, 3.3.3.3, 10.0.0.2"}
    assert (await anon.get(f"{API}/courts", headers=h3)).status_code == 200
    assert (await anon.get(f"{API}/courts", headers=h3)).status_code == 429


async def test_quote_rate_limit_per_user(staff):
    body = {"resource_code": "S01", "date": "2031-03-04", "start_hour": 8, "end_hour": 9}
    for _ in range(60):
        r = await staff.post(f"{BK}/quote", json=body)
        assert r.status_code == 200, r.text
    r = await staff.post(f"{BK}/quote", json=body)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "E-SEC-5"


async def test_rate_limit_fails_open_when_backend_down(anon, monkeypatch):
    class Broken:
        async def hit(self, key, window_s):
            raise ConnectionError("redis down")

    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 1)
    monkeypatch.setattr(ratelimit, "_backend", Broken())
    for _ in range(3):
        assert (await anon.get(f"{API}/courts")).status_code == 200


# ------------------------------------------------------------------ SEC3 Origin check


async def test_sec3_cross_origin_write_with_cookie_rejected(admin):
    for method in ("post", "put", "patch", "delete"):
        r = await admin.request(
            method.upper(),
            f"{BK}/resources",
            json=resource_body(),
            headers={"Origin": "https://evil.example", **idem()},
        )
        assert r.status_code == 403, method
        assert r.json()["detail"]["code"] == "E-SEC-1"


async def test_origin_missing_falls_back_to_referer(admin):
    admin.headers.pop("Origin")
    # Thiếu cả Origin và Referer -> 403 (T-005 Q3)
    r = await admin.post(f"{BK}/resources", json=resource_body(), headers=idem())
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-SEC-1"
    r = await admin.post(
        f"{BK}/resources",
        json=resource_body(),
        headers={"Referer": "https://evil.example/page", **idem()},
    )
    assert r.status_code == 403
    r = await admin.post(
        f"{BK}/resources",
        json=resource_body(),
        headers={"Referer": f"{ORIGIN}/admin/san", **idem()},
    )
    assert r.status_code == 201, r.text


async def test_origin_check_skips_requests_without_session_cookie(anon):
    # Không có cookie phiên (vd. đăng nhập lần đầu) -> không áp Origin check
    r = await anon.post(
        f"{API}/auth/login",
        json={"email": "nobody@test.vn", "password": "x"},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 401
    # GET kèm cookie từ origin lạ không bị chặn (chỉ chặn lệnh ghi)


async def test_origin_check_allows_safe_methods(admin):
    r = await admin.get(f"{BK}/resources", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200


# ------------------------------------------------------------------ body 64 KB


async def test_body_too_large_rejected(admin):
    big = {"name": "x" * (65 * 1024)}
    r = await admin.post(f"{BK}/resources", json=big, headers=idem())
    assert r.status_code == 413
    assert r.json()["detail"]["code"] == "E-SEC-6"


# ------------------------------------------------------------------ SEC5 extra forbid


async def test_sec5_server_controlled_fields_rejected(admin):
    for extra in ({"price": 1}, {"amount": 1}, {"code": "S01"}, {"created_by": "x"}):
        r = await admin.post(f"{BK}/resources", json={**resource_body(), **extra}, headers=idem())
        assert r.status_code == 422, extra
    table = (await admin.get(f"{BK}/prices")).json()
    r = await admin.put(
        f"{BK}/prices",
        json={"version": table["version"], "prices": table["prices"], "updated_by": "hacker"},
        headers=idem(),
    )
    assert r.status_code == 422
    r = await admin.post(
        f"{BK}/quote",
        json={
            "resource_code": "S01",
            "date": "2031-03-04",
            "start_hour": 8,
            "end_hour": 9,
            "price": 1,
        },
    )
    assert r.status_code == 422


# ------------------------------------------------------------------ SEC6 idempotency


async def test_sec6_same_key_replays_response(admin):
    body = resource_body()
    headers = idem()
    r1 = await admin.post(f"{BK}/resources", json=body, headers=headers)
    assert r1.status_code == 201, r1.text
    r2 = await admin.post(f"{BK}/resources", json=body, headers=headers)
    assert r2.status_code == 201
    assert r2.json() == r1.json()
    assert r2.headers.get("idempotent-replayed") == "true"
    assert await count_resources(body["name"]) == 1

    # Cùng key, khác nội dung -> 422 E-SEC-4
    r3 = await admin.post(f"{BK}/resources", json=resource_body(), headers=headers)
    assert r3.status_code == 422
    assert r3.json()["detail"]["code"] == "E-SEC-4"


async def test_idempotency_key_required_and_must_be_uuid4(admin):
    body = resource_body()
    r = await admin.post(f"{BK}/resources", json=body)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "E-SEC-2"
    for bad in ("abc", str(uuid.uuid1())):
        r = await admin.post(f"{BK}/resources", json=body, headers={"Idempotency-Key": bad})
        assert r.status_code == 400, bad
    assert await count_resources(body["name"]) == 0


async def test_idempotency_failed_request_can_be_retried(admin):
    body = resource_body()
    body["close_time"] = "05:30"  # E-CFG-2
    headers = idem()
    r = await admin.post(f"{BK}/resources", json=body, headers=headers)
    assert r.status_code == 422
    body["close_time"] = "22:00"
    # Lỗi không được lưu -> có thể gửi lại cùng key (nội dung khác vẫn chạy vì chưa có kết quả)
    r = await admin.post(f"{BK}/resources", json=body, headers=headers)
    assert r.status_code == 201, r.text


async def test_idempotency_concurrent_same_key_conflicts(admin):
    """Đang xử lý cùng key ở request khác -> 409 E-SEC-3 (giả lập bằng giữ advisory lock)."""
    key = uuid.uuid4()
    me = (await admin.get(f"{API}/auth/me")).json()
    lock_id = Idempotency(key, "", "")._lock_id(f"admin:{me['id']}")
    async with engine.connect() as conn:
        await conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": lock_id})
        try:
            r = await admin.post(
                f"{BK}/resources", json=resource_body(), headers={"Idempotency-Key": str(key)}
            )
            assert r.status_code == 409
            assert r.json()["detail"]["code"] == "E-SEC-3"
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_id})


async def test_idempotency_parallel_double_click_creates_one(admin):
    body = resource_body()
    headers = idem()
    results = await asyncio.gather(
        *(admin.post(f"{BK}/resources", json=body, headers=headers) for _ in range(5))
    )
    statuses = sorted(r.status_code for r in results)
    assert set(statuses) <= {201, 409}
    assert 201 in statuses
    assert await count_resources(body["name"]) == 1


async def test_idempotency_key_scoped_per_actor(admin, staff):
    """Cùng key nhưng người thao tác khác -> không trả kết quả của người khác."""
    headers = idem()
    r = await admin.post(
        f"{BK}/special-days", json={"date_from": "2033-01-02", "name": "A"}, headers=headers
    )
    assert r.status_code == 201
    r2 = await staff.post(
        f"{BK}/special-days", json={"date_from": "2033-01-02", "name": "A"}, headers=headers
    )
    assert r2.status_code == 403  # quầy không có quyền -> không lộ response của Admin
    await admin.delete(f"{BK}/special-days/{r.json()['id']}", headers=idem())


async def test_idempotent_delete_replay(admin):
    r = await admin.post(
        f"{BK}/special-days", json={"date_from": "2034-03-03", "name": "Xóa"}, headers=idem()
    )
    headers = idem()
    path = f"{BK}/special-days/{r.json()['id']}"
    assert (await admin.delete(path, headers=headers)).status_code == 204
    replay = await admin.delete(path, headers=headers)
    assert replay.status_code == 204
    assert replay.headers.get("idempotent-replayed") == "true"


# ------------------------------------------------------------------ SEC7 audit append-only


async def test_sec7_audit_log_is_append_only(admin):
    r = await admin.post(
        f"{BK}/special-days", json={"date_from": "2035-05-05", "name": "Audit"}, headers=idem()
    )
    assert r.status_code == 201
    async with engine.connect() as conn:
        row_id = await conn.scalar(select(func.max(AuditLog.id)))
        for sql in (
            "UPDATE audit_log SET actor_label = 'x' WHERE id = :id",
            "DELETE FROM audit_log WHERE id = :id",
            "TRUNCATE audit_log",
        ):
            try:
                await conn.execute(text(sql), {"id": row_id})
                raise AssertionError(f"{sql} should fail")
            except DBAPIError as e:
                assert "audit_log" in str(e.orig)
            await conn.rollback()

        # Dòng quá 12 tháng được xóa (job dọn)
        old_id = await conn.scalar(
            text(
                "INSERT INTO audit_log (at, actor_type, actor_label, action, entity_type) "
                "VALUES (now() - interval '13 months', 'system', 'test', 'test.old', 'x') "
                "RETURNING id"
            )
        )
        await conn.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": old_id})
        await conn.commit()


async def test_audit_written_in_same_transaction(admin):
    """Thao tác lỗi (rollback) không để lại nhật ký."""
    async with SessionLocal() as s:
        before = await s.scalar(select(func.count()).select_from(AuditLog))
    r = await admin.post(
        f"{BK}/special-days", json={"date_from": "2026-02-18", "name": "Trùng Tết"}, headers=idem()
    )
    assert r.status_code == 409
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).select_from(AuditLog)) == before


# ------------------------------------------------------------------ SEC8 dữ liệu nhạy cảm


async def test_sec8_admin_users_list_masks_phone(admin, staff):  # staff: tạo tài khoản quầy
    r = await admin.get(f"{API}/admin/users")
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        assert "phone" not in row and "hashed_password" not in row
    staff_row = next(u for u in rows if u["email"] == "quay@test.vn")
    assert staff_row["phone_masked"] == "0911 xxx 333"
    assert "0911222333" not in r.text


async def test_sec8_responses_have_no_secrets(admin):
    for path in ("/resources", "/prices", "/special-days"):
        r = await admin.get(f"{BK}{path}")
        assert r.status_code == 200
        for word in ("hashed_password", "token", "password"):
            assert word not in r.text, (path, word)


# ------------------------------------------------------------------ B7 request id


async def test_request_id_generated_and_echoed(anon):
    r = await anon.get(f"{API}/courts")
    assert len(r.headers["x-request-id"]) == 32
    r = await anon.get(f"{API}/courts", headers={"X-Request-ID": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"
    r = await anon.get(f"{API}/courts", headers={"X-Request-ID": "bad id with spaces"})
    assert r.headers["x-request-id"] != "bad id with spaces"


def test_access_log_strips_query_string():
    import logging

    from app.core.context import StripQueryLogFilter

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", "/api/v1/members/search?q=0912345678", "1.1", 200),
        None,
    )
    StripQueryLogFilter().filter(record)
    assert "0912345678" not in record.getMessage()
