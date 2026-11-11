# ruff: noqa: E501
"""QA T-069 (API, AC1–AC7): "Theo dõi sân" – ``GET /play-rooms/admin/day`` và ``/admin/rooms/{id}``.

Góc nhìn độc lập với ``test_play_room_monitor.py`` của BACKEND: tỉ số đi qua LUỒNG THẬT của hội viên (bốc → bắt đầu → ghi kết quả bằng API,
không ghi thẳng DB) rồi mới đối chiếu màn Admin; ETag / 304 theo đúng cách trình duyệt tải lại 10 giây; không có SĐT ở BẤT KỲ chỗ nào của phản hồi
(quét cả khóa lẫn chuỗi 10 chữ số); chỉ đọc (mọi phương thức ghi → 405, không đổi dữ liệu); biên ngày ±365 / ±366 / ±367; id phòng lạ / không phải số;
quyền cấp và thu hồi có hiệu lực ngay; hội viên (kể cả chủ phòng) vẫn không dùng được API Admin và vẫn bị T-054 chặn khi ở ngoài phòng đã kết thúc.
"""

import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.permissions import Perm
from app.modules.auth.models import RolePermission
from app.modules.members.models import Customer
from app.modules.play_rooms.models import PlayRoom
from tests import test_play_rooms as base
from tests.conftest import API, idem
from tests.test_play_room_matches import setup_room, v
from tests.test_play_rooms import ROOMS, fill, post, room_for

MON = f"{API}/play-rooms/admin"
PERM = Perm.PLAY_ROOMS_MONITOR.value
people = base.people  # fixture dùng chung
PHONE_LIKE = re.compile(r"(?<!\d)0\d{9,10}(?!\d)")


def court_of(d: dict, code: str) -> dict:
    [court] = [c for c in d["courts"] if c["resource_code"] == code]
    return court


async def day(client, **params):
    r = await client.get(f"{MON}/day", params=params)
    assert r.status_code == 200, r.text
    return r


def assert_no_phone(payload, *phones: str) -> None:
    """Không có khóa chứa "phone" và không có chuỗi giống SĐT ở bất kỳ đâu trong phản hồi."""
    text = json.dumps(payload, ensure_ascii=False)
    assert "phone" not in text.lower(), "có khóa / chữ phone"
    assert not PHONE_LIKE.search(text), PHONE_LIKE.search(text)
    for p in phones:
        assert p not in text


# ---------------------------------------------------------------- AC1, AC2: luồng thật


async def test_ac1_ac2_real_match_flow_shows_up_on_the_admin_screen_with_etag(staff, admin, people):
    host, room = await setup_room(staff, admin, people)  # Host + 3 thành viên giả = 4 người
    async with SessionLocal() as s:
        code = (await s.get(PlayRoom, room.id)).booking_code
    # Chưa có trận nào
    r = await day(admin)
    etag0 = r.headers["etag"]
    mon = next(rm for c in r.json()["courts"] for rm in c["rooms"] if rm["room_id"] == room.id)
    assert (mon["status"], mon["member_count"], mon["matches_finished"]) == ("playing", 4, 0)
    assert mon["current_match"] is None and mon["last_match"] is None
    assert mon["booking_code"] == code and mon["host"]["member_code"] == host.code
    assert (await admin.get(f"{MON}/day", headers={"If-None-Match": etag0})).status_code == 304

    # Bốc → đội hiện ra, tỉ số chưa có
    d = await post(host.client, f"/{room.id}/draw", {"version": await v(host.client, room.id)})
    assert d.status_code == 200, d.text
    r = await admin.get(f"{MON}/day", headers={"If-None-Match": etag0})
    assert r.status_code == 200, "bốc đội làm đổi nội dung → không còn 304"
    mon = next(rm for c in r.json()["courts"] for rm in c["rooms"] if rm["room_id"] == room.id)
    assert mon["current_match"]["status"] == "drawn" and mon["current_match"]["score_a"] is None
    assert len(mon["current_match"]["team_a"]) == len(mon["current_match"]["team_b"]) == 2
    etag1 = r.headers["etag"]
    assert etag1 != etag0

    # Bắt đầu → "playing", chưa có tỉ số
    st = await post(host.client, f"/{room.id}/start", {"version": await v(host.client, room.id)})
    assert st.status_code == 200, st.text
    r = await admin.get(f"{MON}/day", headers={"If-None-Match": etag1})
    mon = next(rm for c in r.json()["courts"] for rm in c["rooms"] if rm["room_id"] == room.id)
    assert mon["current_match"]["status"] == "playing" and mon["current_match"]["score_a"] is None
    etag2 = r.headers["etag"]

    # Hội viên ghi kết quả → trận mới nhất kèm tỉ số, "đang đánh" mất, số trận đã xong tăng
    ver = await v(host.client, room.id)
    res = await post(
        host.client, f"/{room.id}/matches/1/result", {"score_a": 21, "score_b": 15, "version": ver}
    )
    assert res.status_code == 200, res.text
    r = await admin.get(f"{MON}/day", headers={"If-None-Match": etag2})
    assert r.status_code == 200 and r.headers["etag"] != etag2
    mon = next(rm for c in r.json()["courts"] for rm in c["rooms"] if rm["room_id"] == room.id)
    assert mon["current_match"] is None and mon["matches_finished"] == 1
    last = mon["last_match"]
    assert (last["no"], last["status"], last["score_a"], last["score_b"], last["winner"]) == (
        1,
        "finished",
        21,
        15,
        "a",
    )
    assert (
        await admin.get(f"{MON}/day", headers={"If-None-Match": r.headers["etag"]})
    ).status_code == 304
    # Chi tiết khớp thẻ phòng; ghi chú: tên đội có 2 + 2 người
    detail = (await admin.get(f"{MON}/rooms/{room.id}")).json()
    assert detail["room"] == mon
    assert [m["no"] for m in detail["matches"]] == [1] and detail["matches"][0]["score_a"] == 21
    assert len(detail["members"]) == 4 and detail["members"][0]["role"] == "host"
    assert detail["ranking"], "có bảng xếp hạng sau trận đầu"
    assert_no_phone(detail, host.phone)
    assert_no_phone(r.json(), host.phone)


# ---------------------------------------------------------------- AC3: ngày đã qua, T-054 không áp cho Admin


async def test_ac3_past_day_is_visible_to_admin_but_not_to_outsiders_or_even_the_host_api(
    staff, admin, people
):
    host = await people("QA Chủ Hôm Qua")
    outsider = await people("QA Người Ngoài")
    made = await room_for(staff, admin, host.code)
    room = made["room"]
    start = room.start_at - timedelta(days=2)
    async with SessionLocal() as s:
        await s.execute(
            update(PlayRoom)
            .where(PlayRoom.id == room.id)
            .values(start_at=start, end_at=start + timedelta(hours=1))
        )
        await s.commit()
    past = start.astimezone(settings.tz).date().isoformat()
    mon = next(
        rm
        for c in (await day(admin, date=past)).json()["courts"]
        for rm in c["rooms"]
        if rm["room_id"] == room.id
    )
    assert mon["status"] == "ended"
    assert (await admin.get(f"{MON}/rooms/{room.id}")).status_code == 200
    # Hội viên ngoài phòng: T-054 vẫn chặn; và API Admin đóng với mọi hội viên (kể cả Host)
    assert (await outsider.client.get(f"{ROOMS}/{room.id}")).status_code == 404
    for member in (outsider, host):
        assert (await member.client.get(f"{MON}/day", params={"date": past})).status_code == 403
        assert (await member.client.get(f"{MON}/rooms/{room.id}")).status_code == 403
    # Hôm nay: sân đó không còn phòng nhưng vẫn là một hàng "Không có phòng"
    assert court_of((await day(admin)).json(), made["court"]["code"])["rooms"] == []


# ---------------------------------------------------------------- AC4: tên thật cho Admin, biệt danh cho hội viên, không SĐT


async def test_ac4_real_name_for_admin_nickname_for_members_and_phone_never(staff, admin, people):
    host = await people("Nguyễn QA Chủ Thật")
    guest = await people("Lê QA Khách Thật")
    async with SessionLocal() as s:
        await s.execute(
            update(Customer)
            .where(Customer.id == host.customer_id)
            .values(nickname="Xị Ẩn", show_on_records=False)
        )
        await s.commit()
    made = await room_for(staff, admin, host.code)
    room = made["room"]
    await fill(room.id, 2)
    mon_day = (await day(admin)).json()
    detail = (await admin.get(f"{MON}/rooms/{room.id}")).json()
    mon = next(rm for c in mon_day["courts"] for rm in c["rooms"] if rm["room_id"] == room.id)
    assert (mon["host"]["full_name"], mon["host"]["nickname"], mon["host"]["member_code"]) == (
        "Nguyễn QA Chủ Thật",
        "Xị Ẩn",
        host.code,
    )
    assert_no_phone(mon_day, host.phone, guest.phone)
    assert_no_phone(detail, host.phone, guest.phone)
    # Hội viên khác (đã vào phòng) vẫn chỉ thấy biệt danh, không thấy tên thật của Host
    member_view = await guest.client.get(f"{ROOMS}/{room.id}")
    assert member_view.status_code == 200, member_view.text
    assert "Nguyễn QA Chủ Thật" not in member_view.text and "Xị Ẩn" in member_view.text


# ---------------------------------------------------------------- AC5: chỉ đọc


async def test_ac5_read_only_every_write_method_is_rejected_and_nothing_changes(
    staff, admin, people
):
    host, room = await setup_room(staff, admin, people)
    before = (await admin.get(f"{MON}/rooms/{room.id}")).json()
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        for path in (f"{MON}/day", f"{MON}/rooms/{room.id}", f"{MON}/rooms/{room.id}/matches"):
            r = await admin.request(method, path, json={}, headers=idem())
            assert r.status_code in (404, 405), (method, path, r.status_code)
    after = (await admin.get(f"{MON}/rooms/{room.id}")).json()
    assert after == before


# ---------------------------------------------------------------- AC6: quyền, biên ngày, id lạ


async def test_ac6_grant_and_revoke_take_effect_immediately_and_members_never_pass(
    admin, staff, customer, anon, people
):
    host = await people("QA Hội Viên Chủ")
    assert (await anon.get(f"{MON}/day")).status_code == 401
    assert (await customer.get(f"{MON}/day")).status_code == 403
    assert (await host.client.get(f"{MON}/day")).status_code == 403
    r = await staff.get(f"{MON}/day")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-AUTH-2"
    me = (await staff.get(f"{API}/admin/auth/me")).json()
    assert PERM not in me["perms"]
    async with SessionLocal() as s:
        s.add(RolePermission(role="staff", perm=PERM))
        await s.commit()
    try:
        assert (await staff.get(f"{MON}/day")).status_code == 200, "bật quyền → xem được ngay"
        me = (await staff.get(f"{API}/admin/auth/me")).json()
        assert PERM in me["perms"]
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(RolePermission).where(RolePermission.perm == PERM))
            await s.commit()
    assert (await staff.get(f"{MON}/day")).status_code == 403, "thu hồi → mất ngay"
    assert (await admin.get(f"{MON}/day")).status_code == 200


async def test_date_edges_and_bad_room_ids(admin):
    today = datetime.now(settings.tz).date()
    for offset in (-366, -365, 365, 366, 0):
        r = await admin.get(
            f"{MON}/day", params={"date": (today + timedelta(days=offset)).isoformat()}
        )
        assert r.status_code == 200, offset
    for offset in (-367, 367, 1000, -1000):  # ±366 là biên cuối cùng được xem (BE: 366 ngày)
        r = await admin.get(
            f"{MON}/day", params={"date": (today + timedelta(days=offset)).isoformat()}
        )
        assert r.status_code == 422 and r.json()["detail"]["code"] == "E-001", offset
    for bad in (
        "2026-13-01",
        "2026-02-30",
        "hom-nay",
        "11/11/2026",
        "2026-11-1",
        "' OR 1=1 --",
        "9999-12-31",
        "0001-01-01",
    ):
        r = await admin.get(f"{MON}/day", params={"date": bad})
        assert r.status_code == 422, (bad, r.status_code, r.text[:120])
    for bad in ("abc", "-1", "1.5"):
        r = await admin.get(f"{MON}/rooms/{bad}")
        assert r.status_code in (404, 422), (bad, r.status_code)
    # Quan sát: ``date=`` rỗng được coi như không gửi (mặc định hôm nay), không phải lỗi
    assert (await admin.get(f"{MON}/day", params={"date": ""})).status_code == 200
    r = await admin.get(f"{MON}/rooms/999999999")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "E-NOT-FOUND"


# ---------------------------------------------------------------- AC7: hủy, sân ngừng, thứ tự sân


async def test_ac7_cancelled_booking_room_and_courts_in_order(staff, admin, people):
    from tests.test_front_desk_booking import cancel_paid

    host = await people("QA Chủ Hủy")
    made = await room_for(staff, admin, host.code)
    await cancel_paid(admin, {"code": made["code"], "version": 1})
    mon = next(
        rm
        for c in (await day(admin)).json()["courts"]
        for rm in c["rooms"]
        if rm["room_id"] == made["room"].id
    )
    assert mon["status"] == "cancelled", "booking đã hủy ưu tiên cao nhất"
    detail = await admin.get(f"{MON}/rooms/{made['room'].id}")
    assert detail.status_code == 200 and detail.json()["room"]["status"] == "cancelled"
    # Thứ tự sân ổn định giữa hai lần gọi, không trùng sân, và sân đã có phòng hôm nay nằm trong danh sách
    first = [c["resource_code"] for c in (await day(admin)).json()["courts"]]
    assert first == [c["resource_code"] for c in (await day(admin)).json()["courts"]]
    assert len(first) == len(set(first)) and made["court"]["code"] in first
    # Ngày kế tiếp: sân của phòng hôm nay không có phòng nào ngày mai (hàng nếu còn hiện thì rooms rỗng)
    nxt = (datetime.now(UTC).astimezone(settings.tz) + timedelta(days=1)).date().isoformat()
    other = (await day(admin, date=nxt)).json()
    assert other["date"] == nxt
    for court in other["courts"]:
        if court["resource_code"] == made["court"]["code"]:
            assert court["rooms"] == []


@pytest.mark.xfail(
    strict=True,
    raises=DBAPIError,
    reason="[OPEN] id phòng vượt int64 → lỗi DB (500) ở cả /member-area/rooms/{id} (T-017) lẫn /play-rooms/admin/rooms/{id}; nên 404/422",
)
async def test_huge_room_id_should_be_404_or_422_not_a_server_error(admin, people):
    huge = "99999999999999999999"
    member = await people("QA Id Lớn")
    for client, path in ((member.client, f"{ROOMS}/{huge}"), (admin, f"{MON}/rooms/{huge}")):
        assert (await client.get(path)).status_code in (404, 422)
