"""T-069: Theo dõi sân (Admin, chỉ đọc).

- Mỗi sân một hàng, phòng của ngày, trận đang đánh / trận gần nhất kèm tỉ số.
- Tên thật + biệt danh + mã HV kể cả hội viên ẩn danh, không SĐT.
- Xem được phòng đã kết thúc mà mình không ở trong (T-054 không áp) và phòng của booking đã hủy.
- Quyền ``play_rooms.monitor`` (NV mặc định không có, Admin cấp được); ETag / 304; ngày sai E-001.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.permissions import DEFAULT_ROLE_PERMS, Perm
from app.modules.auth.models import RolePermission
from app.modules.booking_engine.models import Resource
from app.modules.members.models import Customer
from app.modules.play_rooms.models import PlayMatch, PlayRoom, PlayRoomMember
from tests import test_play_rooms as base
from tests.conftest import API
from tests.test_front_desk_booking import cancel_paid
from tests.test_play_rooms import ROOMS, room_for

MON = f"{API}/play-rooms/admin"
people = base.people  # fixture dùng chung (hội viên có tài khoản liên kết)
PERM = Perm.PLAY_ROOMS_MONITOR.value


async def day(client, **params) -> dict:
    r = await client.get(f"{MON}/day", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def court_of(d: dict, code: str) -> dict:
    [court] = [c for c in d["courts"] if c["resource_code"] == code]
    return court


async def add_member(room_id: int, customer_id: int, state: str = "waiting") -> None:
    async with SessionLocal() as s:
        s.add(PlayRoomMember(room_id=room_id, customer_id=customer_id, queue_state=state))
        await s.commit()


async def add_match(room_id: int, no: int, a: list[int], b: list[int], **values) -> None:
    async with SessionLocal() as s:
        s.add(
            PlayMatch(
                room_id=room_id,
                no=no,
                format="2v2" if len(a) == 2 else "1v1",
                team_a=a,
                team_b=b,
                names={str(c): f"Khách {abs(c)}" for c in (*a, *b) if c < 0},
                **values,
            )
        )
        await s.commit()


async def test_day_shows_rooms_people_and_scores_without_phone(staff, admin, people):
    """AC1, AC4: phòng hôm nay, Host, số người, trận đang đánh + trận gần nhất kèm tỉ số; hội viên
    ẩn danh hiện tên thật + biệt danh + mã HV; không SĐT."""
    host = await people("Nguyễn Văn Chủ")
    guest = await people("Trần Thị Khách")
    async with SessionLocal() as s:  # Host ẩn danh trên Video & kỷ lục, có biệt danh
        await s.execute(
            update(Customer)
            .where(Customer.id == host.customer_id)
            .values(nickname="Chủ Xị", show_on_records=False)
        )
        await s.commit()
    made = await room_for(staff, admin, host.code)
    room = made["room"]
    await add_member(room.id, guest.customer_id, "playing")
    now = datetime.now(UTC)
    await add_match(
        room.id,
        1,
        [host.customer_id, guest.customer_id],
        [-1, -2],
        status="finished",
        score_a=21,
        score_b=17,
        winner="a",
        started_at=now - timedelta(minutes=20),
        ended_at=now - timedelta(minutes=5),
    )
    await add_match(room.id, 2, [guest.customer_id], [-3], status="playing", started_at=now)

    r = await admin.get(f"{MON}/day")
    assert r.status_code == 200 and r.headers["etag"]
    d = r.json()
    assert d["date"] == now.astimezone(settings.tz).date().isoformat()
    court = court_of(d, made["court"]["code"])
    assert court["is_active"] is True and court["resource_name"] == made["court"]["name"]
    [mon] = court["rooms"]
    assert (mon["room_id"], mon["booking_code"], mon["status"]) == (
        room.id,
        made["code"],
        "playing",
    )
    assert mon["member_count"] == 2 and mon["matches_finished"] == 1
    assert mon["host"] == {
        "customer_id": host.customer_id,
        "full_name": "Nguyễn Văn Chủ",
        "nickname": "Chủ Xị",
        "member_code": host.code,
        "tier": mon["host"]["tier"],
        "avatar_url": None,
    }
    last = mon["last_match"]
    assert (last["no"], last["status"], last["score_a"], last["score_b"], last["winner"]) == (
        1,
        "finished",
        21,
        17,
        "a",
    )
    assert [p["full_name"] for p in last["team_b"]] == ["Khách 1", "Khách 2"]  # tên chụp lúc bốc
    current = mon["current_match"]
    assert (current["no"], current["status"], current["score_a"]) == (2, "playing", None)
    assert [p["full_name"] for p in current["team_a"]] == ["Trần Thị Khách"]
    assert host.phone not in r.text and guest.phone not in r.text

    # Trang hội viên: vẫn biệt danh như cũ (màn hội viên không đổi)
    member_view = (await guest.client.get(f"{ROOMS}/{room.id}")).json()
    assert {m["display_name"] for m in member_view["members"]} == {"Chủ Xị", "Trần Thị Khách"}
    assert "Nguyễn Văn Chủ" not in str(member_view)

    # Chi tiết: thành viên (Host đầu), mọi trận, xếp hạng – tên thật
    r = await admin.get(f"{MON}/rooms/{room.id}")
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["room"] == mon
    assert [(m["full_name"], m["role"], m["queue_state"]) for m in detail["members"]] == [
        ("Nguyễn Văn Chủ", "host", "waiting"),
        ("Trần Thị Khách", "member", "playing"),
    ]
    assert [m["no"] for m in detail["matches"]] == [2, 1]
    assert [(x["full_name"], x["rank"], x["wins"], x["played"]) for x in detail["ranking"]] == [
        ("Nguyễn Văn Chủ", 1, 1, 1),
        ("Trần Thị Khách", 1, 1, 1),
        ("Khách 1", 3, 0, 1),
        ("Khách 2", 3, 0, 1),
    ]
    assert host.phone not in r.text

    # ETag: không đổi -> 304; ghi kết quả trận -> nội dung mới (AC2)
    etag = (await admin.get(f"{MON}/day")).headers["etag"]
    assert (await admin.get(f"{MON}/day", headers={"If-None-Match": etag})).status_code == 304
    async with SessionLocal() as s:
        await s.execute(
            update(PlayMatch)
            .where(PlayMatch.room_id == room.id, PlayMatch.no == 2)
            .values(status="finished", score_a=21, score_b=9, winner="a", ended_at=now)
        )
        await s.commit()
    r = await admin.get(f"{MON}/day", headers={"If-None-Match": etag})
    assert r.status_code == 200
    mon = court_of(r.json(), made["court"]["code"])["rooms"][0]
    assert mon["current_match"] is None and mon["matches_finished"] == 2
    assert (mon["last_match"]["no"], mon["last_match"]["score_b"]) == (2, 9)


async def test_past_day_ended_and_cancelled_rooms_ignore_t054(staff, admin, people):
    """AC3, AC7: phòng đã kết thúc hôm qua (Admin không ở trong) vẫn xem được, hội viên ngoài phòng
    vẫn 404 như T-054; phòng của booking đã hủy -> ``cancelled``."""
    host = await people("Chủ Hôm Qua")
    outsider = await people("Người Ngoài")
    made = await room_for(staff, admin, host.code)
    room = made["room"]
    yesterday_start = room.start_at - timedelta(days=1)
    async with SessionLocal() as s:
        await s.execute(
            update(PlayRoom)
            .where(PlayRoom.id == room.id)
            .values(start_at=yesterday_start, end_at=yesterday_start + timedelta(hours=1))
        )
        await s.commit()
    await add_match(
        room.id,
        1,
        [host.customer_id],
        [-9],
        status="finished",
        score_a=11,
        score_b=21,
        winner="b",
        ended_at=yesterday_start + timedelta(minutes=30),
    )
    yesterday = yesterday_start.astimezone(settings.tz).date()
    [mon] = court_of(await day(admin, date=yesterday.isoformat()), made["court"]["code"])["rooms"]
    assert (mon["status"], mon["matches_finished"], mon["last_match"]["winner"]) == (
        "ended",
        1,
        "b",
    )
    assert (await admin.get(f"{MON}/rooms/{room.id}")).status_code == 200
    assert (await outsider.client.get(f"{ROOMS}/{room.id}")).status_code == 404  # T-054 giữ

    # Hôm nay: sân này không còn phòng -> hàng vẫn hiện, "Không có phòng"
    assert court_of(await day(admin), made["court"]["code"])["rooms"] == []

    # Booking đã hủy -> nhãn "Booking đã hủy", vẫn mở chi tiết được
    other = await room_for(staff, admin, host.code)
    await cancel_paid(admin, {"code": other["code"], "version": 1})
    [mon] = court_of(await day(admin), other["court"]["code"])["rooms"]
    assert mon["status"] == "cancelled"
    r = await admin.get(f"{MON}/rooms/{other['room'].id}")
    assert r.status_code == 200 and r.json()["room"]["status"] == "cancelled"
    r = await admin.get(f"{MON}/rooms/999999999")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "E-NOT-FOUND"


async def test_inactive_court_hidden_unless_it_has_rooms(staff, admin, people):
    """AC7: sân ngừng hoạt động ẩn khi không có phòng trong ngày, hiện khi có."""
    host = await people("Chủ Sân Ngừng")
    made = await room_for(staff, admin, host.code)
    code = made["court"]["code"]
    r = await admin.patch(
        f"{API}/booking/resources/{code}",
        json={"is_active": False, "version": made["court"]["version"]},
        headers={"Idempotency-Key": "t069-" + code},
    )
    if r.status_code != 200:  # sân còn booking: ngừng thẳng trong DB (chỉ cần cờ)
        async with SessionLocal() as s:
            await s.execute(update(Resource).where(Resource.code == code).values(is_active=False))
            await s.commit()
    court = court_of(await day(admin), code)
    assert court["is_active"] is False and len(court["rooms"]) == 1
    tomorrow = (datetime.now(settings.tz) + timedelta(days=1)).date()
    assert code not in {
        c["resource_code"] for c in (await day(admin, date=str(tomorrow)))["courts"]
    }


async def test_permission_staff_needs_grant_and_bad_dates(admin, staff, customer, anon):
    """AC6: NV mặc định 403, Admin bật quyền -> xem được ngay; khách 403; ngày sai -> E-001."""
    assert Perm.PLAY_ROOMS_MONITOR not in DEFAULT_ROLE_PERMS["staff"]
    assert (await anon.get(f"{MON}/day")).status_code == 401
    assert (await customer.get(f"{MON}/day")).status_code == 403
    r = await staff.get(f"{MON}/day")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-AUTH-2"
    assert (await staff.get(f"{MON}/rooms/1")).status_code == 403
    roles = (await admin.get(f"{API}/admin/roles")).json()
    assert PERM in [p["key"] for g in roles["groups"] for p in g["perms"]]
    async with SessionLocal() as s:
        s.add(RolePermission(role="staff", perm=PERM))
        await s.commit()
    try:
        assert (await staff.get(f"{MON}/day")).status_code == 200
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(RolePermission).where(RolePermission.perm == PERM))
            await s.commit()

    today = datetime.now(settings.tz).date()
    for bad in ("2026-13-01", "hom-nay", str(today + timedelta(days=400))):
        r = await admin.get(f"{MON}/day", params={"date": bad})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "E-001", bad
    assert (await day(admin, date=str(today - timedelta(days=300))))["courts"] is not None


async def test_menu_has_court_monitor_after_orders(admin):
    """Mục menu "Theo dõi sân" (``theoDoiSan``) mặc định ngay sau "Đơn đặt sân"."""
    r = await admin.get(f"{API}/admin/auth/me")
    assert r.status_code == 200, r.text
    order = r.json()["menu_order"]
    assert order.index("theoDoiSan") == order.index("donDatSan") + 1
    assert PERM in r.json()["perms"]
