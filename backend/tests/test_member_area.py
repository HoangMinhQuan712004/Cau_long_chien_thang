"""T-016 đợt 1: liên kết tài khoản ↔ hội viên, Hồ sơ của tôi, ảnh đại diện (ADR-009, SEC1–SEC5)."""

import io
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from PIL import Image
from sqlalchemy import func, select, update

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.members.models import Customer
from tests.conftest import API, CUSTOMER_PASSWORD, _client, new_customer, sign_in
from tests.helpers_booking import BK, book, new_court, random_phone, safe_hour
from tests.helpers_web import WEB

ME = f"{API}/member-area/me"
AVATAR = f"{API}/member-area/me/avatar"
RACKETS = f"{API}/rackets"


async def create_member(admin, phone: str, name: str = "Nguyễn Văn Minh", tier=None) -> str:
    """Hội viên qua màn quản trị (dev, PR #21). SĐT chưa có tài khoản -> sân tạo tài khoản."""
    r = await admin.post(f"{API}/members", json={"full_name": name, "phone": phone, "tier": tier})
    assert r.status_code == 201, r.text
    return r.json()["member_code"]


async def customer_id_of(code: str) -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(Customer.id).where(Customer.member_code == code))


async def verify_booking_phone(client, phone: str) -> dict:
    r = await client.post(f"{WEB}/phone/request", json={"phone": phone})
    assert r.status_code == 202, r.text
    r = await client.post(f"{WEB}/phone/verify", json={"phone": phone, "otp": r.json()["test_otp"]})
    assert r.status_code == 200, r.text
    return r.json()


@asynccontextmanager
async def linked_member(admin, name: str = "Nguyễn Văn Minh", tier: str | None = "Trung bình"):
    """Khách tự đăng ký + xác minh SĐT, rồi sân thêm hội viên cùng SĐT -> (client, id, mã, SĐT)."""
    phone = random_phone()
    async with new_customer(phone) as c:
        await verify_booking_phone(c, phone)
        code = await create_member(admin, phone, name, tier)
        yield c, await customer_id_of(code), code, phone


def image_bytes(fmt: str = "PNG", size=(800, 600), **save) -> bytes:
    img = Image.new("RGB", size, (30, 120, 80))
    buf = io.BytesIO()
    img.save(buf, fmt, **save)
    return buf.getvalue()


async def upload(client, data: bytes, crop=(0, 0, 600), name="anh.png", ctype="image/png"):
    x, y, size = crop
    return await client.put(
        AVATAR,
        files={"file": (name, data, ctype)},
        data={"crop_x": str(x), "crop_y": str(y), "crop_size": str(size)},
    )


def body_of(me: dict, **changes) -> dict:
    body = {
        "full_name": me["full_name"],
        "nickname": me["nickname"],
        "email": me["email"],
        "tier": me["tier"],
        "racket": me["racket"],
        "show_on_records": me["show_on_records"],
        "version": me["version"],
    }
    return {**body, **changes}


# ------------------------------------------------------------------ liên kết (AC1, AC2, SEC3)


async def test_verified_account_sees_own_member_profile(admin):
    async with linked_member(admin) as (c, _, code, phone):
        me = (await c.get(f"{API}/auth/me")).json()
        assert me["is_member"] is True
        r = await c.get(ME)
        assert r.status_code == 200, r.text
        assert r.headers["Cache-Control"] == "no-store"
        body = r.json()
        assert body["member_code"] == code and body["phone"] == phone
        assert body["full_name"] == "Nguyễn Văn Minh" and body["short_name"] == "Minh"
        assert body["tier"] == "Trung bình" and body["show_on_records"] is False
        assert body["avatar_url"] is None and body["racket"] is None
        assert body["nickname"] is None and body["email"] is None
        assert body["record_kmh"] is None and body["version"] == 1
        assert body["joined_at"] == datetime.now(settings.tz).date().isoformat()


async def test_unverified_self_registered_account_is_not_member(admin):
    """Ai đó tự đăng ký trước bằng SĐT của hội viên (không OTP) -> không vào khu hội viên."""
    phone = random_phone()
    async with new_customer(phone) as c:
        await create_member(admin, phone)
        assert (await c.get(f"{API}/auth/me")).json()["is_member"] is False
        r = await c.get(ME)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "E-HV-8"
        # Xác minh SĐT (AC40) -> thành hội viên, đăng nhập lại cũng thấy
        await verify_booking_phone(c, phone)
        assert (await c.get(ME)).status_code == 200
        r = await sign_in(c, phone, CUSTOMER_PASSWORD)
        assert r.json()["account"]["is_member"] is True


async def test_club_created_account_must_change_password_first(admin):
    """Sân tạo tài khoản (mật khẩu ban đầu = SĐT) -> phải đổi mật khẩu trước (E-AUTH-25)."""
    phone = random_phone()
    await create_member(admin, phone)
    async with _client() as c:
        r = await sign_in(c, phone, phone)
        assert r.status_code == 200, r.text
        assert r.json()["account"]["is_member"] is True
        r = await c.get(ME)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "E-AUTH-25"
        r = await c.post(f"{API}/auth/password/change", json={"new_password": "MatKhauMoi9"})
        assert r.status_code == 200, r.text
        assert (await c.get(ME)).status_code == 200


async def test_temp_profile_is_never_member(staff, admin):
    phone = random_phone()
    court = await new_court(admin)
    hour = await safe_hour()
    temp = {"temp": {"full_name": "T", "phone": phone}}
    r = await book(staff, court["code"], hour, customer=temp)
    assert r.status_code == 201
    async with new_customer(phone) as c:
        body = await verify_booking_phone(c, phone)
        assert body["account_verified"] is True
        assert (await c.get(f"{API}/auth/me")).json()["is_member"] is False
        r = await c.get(ME)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "E-HV-8"


async def test_member_area_needs_customer_session(anon, admin, staff):
    for client in (anon, admin, staff):
        r = await client.get(ME)
        assert r.status_code == 401 and r.json()["detail"]["code"] == "E-AUTH-1"


# ------------------------------------------------------------------ sửa hồ sơ (AC11–AC17)


async def test_update_profile_syncs_name_and_writes_audit(staff, admin):
    async with linked_member(admin, "Trần Thị Lan") as (c, customer_id, code, _):
        court = await new_court(admin)
        r = await book(staff, court["code"], await safe_hour(), customer={"member_code": code})
        booking_code = r.json()["code"]

        me = (await c.get(ME)).json()
        racket = f"Vợt Riêng {uuid.uuid4().hex[:6]}"  # chưa có trong danh mục -> tự thêm
        email = f"Lan.{uuid.uuid4().hex[:6]}@Gmail.com"
        r = await c.put(
            ME,
            json=body_of(
                me,
                full_name="  Trần Thị Lan Anh  ",
                nickname="  Lan Smash ",
                email=f" {email} ",
                tier="Khá",
                racket=f"  {racket} ",
                show_on_records=True,
            ),
        )
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["full_name"] == "Trần Thị Lan Anh" and out["short_name"] == "Anh"
        assert out["nickname"] == "Lan Smash" and out["email"] == email
        assert out["tier"] == "Khá" and out["racket"] == racket
        names = [r["name"] for r in (await c.get(RACKETS)).json()]
        assert racket in names  # danh mục vợt chung (dev) – hội viên đọc được
        assert out["show_on_records"] is True and out["version"] == me["version"] + 1
        assert out == (await c.get(ME)).json()

        assert (await c.get(f"{API}/auth/me")).json()["full_name"] == "Trần Thị Lan Anh"
        item = (await staff.get(f"{BK}/items/{booking_code}")).json()
        assert item["customer"]["name"] == "Trần Thị Lan Anh"
        assert item["customer"]["tier"] == "Trung bình"  # snapshot hạng lúc đặt giữ nguyên

        async with SessionLocal() as s:
            row = await s.scalar(
                select(AuditLog).where(
                    AuditLog.action == "member.self_update", AuditLog.entity_code == code
                )
            )
        assert row.actor_label == f"Hội viên (tự sửa) · {code}"
        changes = row.detail["changes"]
        assert changes["full_name"] == ["Trần Thị Lan", "Trần Thị Lan Anh"]
        assert row.detail["renamed_items"] == 1  # booking tại quầy ở đầu test
        assert changes["email"] == [None, f"L***@{email.split('@')[1]}"]
        assert email not in str(row.detail)

        # Không đổi gì -> không ghi, không tăng version
        r = await c.put(ME, json=body_of(out))
        assert r.status_code == 200 and r.json()["version"] == out["version"]
        # Chuỗi rỗng = null
        r = await c.put(ME, json=body_of(out, nickname="", email="  "))
        assert (r.json()["nickname"], r.json()["email"]) == (None, None)


async def test_update_reports_every_field_error_at_once(admin):
    async with linked_member(admin) as (c, *_):
        me = (await c.get(ME)).json()
        r = await c.put(
            ME,
            json=body_of(
                me, full_name="   ", nickname="x" * 21, email="khong-phai-email", tier="Vàng"
            ),
        )
        assert r.status_code == 422
        detail = r.json()["detail"]
        fields = {f["field"]: f["code"] for f in detail["fields"]}
        assert fields == {
            "full_name": "E-HV-1",
            "nickname": "E-HV-1",
            "email": "E-HV-10",
            "tier": "E-HV-1",
        }
        assert detail["code"] == "E-HV-1"
        assert (await c.get(ME)).json() == me  # không lưu ô nào
        r = await c.put(ME, json=body_of(me, full_name="x" * 101))
        assert r.json()["detail"]["fields"][0]["field"] == "full_name"


async def test_email_unique_case_insensitive(admin):
    email = f"trung.{uuid.uuid4().hex[:6]}@gmail.com"
    async with linked_member(admin) as (a, *_), linked_member(admin) as (b, *_):
        me_a = (await a.get(ME)).json()
        assert (await a.put(ME, json=body_of(me_a, email=email))).status_code == 200
        me_b = (await b.get(ME)).json()
        r = await b.put(ME, json=body_of(me_b, email=email.upper()))
        assert r.status_code == 422
        assert r.json()["detail"]["fields"] == [
            {"field": "email", "code": "E-HV-11", "message": "Email đã được sử dụng."}
        ]
        # Chính mình: lưu lại email của mình (khác hoa thường) không bị chặn
        me_a = (await a.get(ME)).json()
        assert (await a.put(ME, json=body_of(me_a, email=email.upper()))).status_code == 200


async def test_stale_version_is_rejected(admin):
    async with linked_member(admin) as (c, customer_id, *_):
        me = (await c.get(ME)).json()
        async with SessionLocal() as s:  # quầy vừa sửa
            await s.execute(
                update(Customer)
                .where(Customer.id == customer_id)
                .values(version=Customer.version + 1)
            )
            await s.commit()
        r = await c.put(ME, json=body_of(me, nickname="Tab cũ"))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "E-HV-12"
        assert (await c.get(ME)).json()["nickname"] is None


async def test_no_idor_and_no_extra_fields(admin):
    async with linked_member(admin, "Người A") as (a, id_a, code_a, _):
        async with linked_member(admin, "Người B") as (b, id_b, code_b, _):
            assert (await a.get(ME)).json()["member_code"] == code_a
            assert (await b.get(ME)).json()["member_code"] == code_b
            me_a = (await a.get(ME)).json()
            for extra in ({"customer_id": id_b}, {"member_code": code_b}, {"phone": "0900000000"}):
                r = await a.put(ME, json={**body_of(me_a), **extra})
                assert r.status_code == 422
            assert (await b.get(ME)).json()["full_name"] == "Người B"


async def test_writes_need_origin(admin):
    async with linked_member(admin) as (c, *_):
        me = (await c.get(ME)).json()
        c.headers.pop("Origin")
        r = await c.put(ME, json=body_of(me, nickname="X"))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "E-SEC-1"
        r = await upload(c, image_bytes())
        assert r.status_code == 403


# ------------------------------------------------------------------ ảnh đại diện (AC18–AC19, SEC2)


async def test_avatar_is_reencoded_without_metadata(anon, admin):
    async with linked_member(admin) as (c, customer_id, code, _):
        version = (await c.get(ME)).json()["version"]
        exif = Image.Exif()
        exif[0x010F] = "MayAnhBiMat"  # Make
        exif[0x0112] = 6  # Orientation: xoay 90°
        src = image_bytes("JPEG", size=(1200, 900), exif=exif.tobytes())
        # Sau khi xoay theo EXIF ảnh là 900×1200 -> khung 900 ở y=300 hợp lệ
        r = await upload(c, src, crop=(0, 300, 900), name="anh.jpg", ctype="image/jpeg")
        assert r.status_code == 200, r.text
        url = r.json()["avatar_url"]
        assert url.startswith(f"{API}/member-area/avatars/{customer_id}?v=")
        me = (await c.get(ME)).json()
        assert me["avatar_url"] == url and me["version"] == version  # ảnh không đổi version

        r = await anon.get(url)
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/webp"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert "immutable" in r.headers["cache-control"]
        out = Image.open(io.BytesIO(r.content))
        assert out.format == "WEBP" and out.size == (512, 512)
        assert not out.getexif() and b"MayAnhBiMat" not in r.content
        r304 = await anon.get(url, headers={"If-None-Match": r.headers["etag"]})
        assert r304.status_code == 304

        async with SessionLocal() as s:
            n = await s.scalar(
                select(func.count()).where(
                    AuditLog.action == "member.avatar_update", AuditLog.entity_code == code
                )
            )
        assert n == 1

        assert (await c.delete(AVATAR)).status_code == 204
        assert (await c.get(ME)).json()["avatar_url"] is None
        assert (await anon.get(url)).status_code == 404
        assert (await c.delete(AVATAR)).status_code == 204  # chưa có ảnh -> vẫn 204


def _bomb_png() -> bytes:
    """PNG 7000×7000 (49 MP) nén rất nhỏ."""
    img = Image.new("1", (7000, 7000))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


@pytest.mark.parametrize(
    ("data", "crop", "name", "ctype"),
    [
        pytest.param(
            b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
            (0, 0, 1),
            "a.png",
            "image/png",
            id="svg-as-png",
        ),
        pytest.param(
            b"<html><script>alert(1)</script></html>", (0, 0, 1), "a.jpg", "image/jpeg", id="html"
        ),
        pytest.param(
            b"\x89PNG\r\n\x1a\n" + b"<script>alert(1)</script>" * 20,
            (0, 0, 1),
            "a.png",
            "image/png",
            id="png-header-polyglot",
        ),
        pytest.param(b"GIF89a" + b"\x00" * 100, (0, 0, 1), "a.gif", "image/gif", id="gif"),
        pytest.param(b"", (0, 0, 1), "a.png", "image/png", id="empty"),
        pytest.param(_bomb_png(), (0, 0, 100), "bomb.png", "image/png", id="decompression-bomb"),
        pytest.param(image_bytes(), (700, 0, 200), "a.png", "image/png", id="crop-outside"),
    ],
)
async def test_bad_files_are_rejected(data, crop, name, ctype, admin):
    async with linked_member(admin) as (c, *_):
        r = await upload(c, data, crop=crop, name=name, ctype=ctype)
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        assert isinstance(detail, dict) and detail["code"] == "E-HV-13"
        assert (await c.get(ME)).json()["avatar_url"] is None


async def test_too_large_file_rejected(monkeypatch, admin):
    monkeypatch.setattr(settings, "AVATAR_MAX_BYTES", 10_000)
    async with linked_member(admin) as (c, *_):
        noisy = Image.effect_noise((400, 400), 100).convert("RGB")
        buf = io.BytesIO()
        noisy.save(buf, "PNG")
        assert len(buf.getvalue()) > 10_000
        r = await upload(c, buf.getvalue(), crop=(0, 0, 400))
        assert r.status_code in (413, 422)
        if r.status_code == 422:
            assert r.json()["detail"]["code"] == "E-HV-13"


async def test_tall_thin_image_and_webp_alpha(admin):
    async with linked_member(admin) as (c, *_):
        thin = image_bytes("PNG", size=(1, 100_000))
        r = await upload(c, thin, crop=(0, 50_000, 1))
        assert r.status_code == 200, r.text
        rgba = Image.new("RGBA", (300, 300), (255, 0, 0, 128))
        buf = io.BytesIO()
        rgba.save(buf, "WEBP")
        r = await upload(c, buf.getvalue(), crop=(0, 0, 300), name="a.webp", ctype="image/webp")
        assert r.status_code == 200, r.text


async def test_avatar_endpoints_need_member(customer, anon):
    r = await upload(customer, image_bytes())
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-HV-8"
    assert (await upload(anon, image_bytes())).status_code == 401
    assert (await anon.get(f"{API}/member-area/avatars/999999999")).status_code == 404


# ------------------------------------------------------------------ vợt dùng chung (AC9)


async def test_member_reads_racket_catalog(customer, admin):
    async with linked_member(admin) as (c, *_):
        r = await c.get(RACKETS)
        assert r.status_code == 200 and isinstance(r.json(), list)
        assert (await c.get(RACKETS, params={"all": 1})).status_code == 200  # vợt ẩn: chỉ Admin
        assert (await c.post(RACKETS, json={"name": "X"})).status_code == 403  # chỉ Admin thêm
    assert (await customer.get(RACKETS)).status_code == 403


async def test_tier_null_until_chosen(admin):
    async with linked_member(admin, tier=None) as (c, *_):
        me = (await c.get(ME)).json()
        assert me["tier"] is None
        r = await c.put(ME, json=body_of(me, nickname="Chưa xếp"))
        assert r.status_code == 200 and r.json()["tier"] is None  # giữ null được
        r = await c.put(ME, json=body_of(r.json(), tier="Yếu"))
        assert r.status_code == 200 and r.json()["tier"] == "Yếu"
        r = await c.put(ME, json=body_of(r.json(), tier=None))
        assert r.status_code == 422
        assert r.json()["detail"]["fields"][0] == {
            "field": "tier",
            "code": "E-HV-1",
            "message": "Vui lòng chọn Trình độ.",
        }


async def test_racket_name_error_is_reported_with_fields(admin):
    async with linked_member(admin) as (c, *_):
        me = (await c.get(ME)).json()
        r = await c.put(ME, json=body_of(me, full_name="", racket="x" * 150))
        assert r.status_code == 422
        assert {f["field"] for f in r.json()["detail"]["fields"]} == {"full_name", "racket"}
