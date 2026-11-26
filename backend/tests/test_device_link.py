"""Nối máy đo tốc độ ShuttleTrack (module device_link): lệnh trận qua MQTT, cú đập phá mốc thành số
đo nguồn "Máy đo", mốc kỷ lục từng kỳ trong Redis. Broker và Redis là bản giả – không ra mạng."""

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.device_link import api as device_link
from app.modules.device_link import ingest, link, marks, messages, sync
from app.modules.device_link.models import DeviceCourt
from app.modules.play_rooms import api as rooms
from app.modules.play_rooms.models import PlayMatch, PlayRoom
from app.modules.records import api as records
from app.modules.records.models import SpeedRecord
from app.workers import worker
from tests import test_play_rooms as base

people = base.people  # fixture dùng chung (hội viên có tài khoản liên kết)

TAG = uuid.uuid4().hex[:6]
PREFIX = "badminton"


def court_code() -> str:
    return f"T{uuid.uuid4().hex[:7]}"


def shot_ref() -> str:
    return f"{TAG}{uuid.uuid4().hex}-7"


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    async with SessionLocal() as s:
        await s.execute(delete(PlayRoom).where(PlayRoom.booking_code.like(f"DL-{TAG}-%")))
        await s.execute(delete(DeviceCourt))
        await s.execute(delete(SpeedRecord).where(SpeedRecord.source_ref.like(f"st:{TAG}%")))
        await s.commit()


async def playing(court: str, fmt: str, team_a: list[int], team_b: list[int]) -> int:
    """Phòng mở trên ``court`` với một trận đang chơi; trả id trận."""
    now = datetime.now(UTC)
    async with SessionLocal() as s:
        room = PlayRoom(
            booking_code=f"DL-{TAG}-{uuid.uuid4().hex[:8]}",
            resource_code=court,
            resource_name="Sân thử",
            resource_type_name="Sân thường",
            start_at=now - timedelta(minutes=10),
            end_at=now + timedelta(minutes=50),
            host_customer_id=team_a[0],
            format=fmt,
        )
        s.add(room)
        await s.flush()
        match = PlayMatch(
            room_id=room.id,
            no=1,
            format=fmt,
            team_a=team_a,
            team_b=team_b,
            status="playing",
            started_at=now,
        )
        s.add(match)
        await s.commit()
        return match.id


class Broker:
    """Thay ``Link.publish``: ghi lại lệnh đã phát; ``up = False`` -> broker không xác nhận."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict, bool]] = []
        self.up = True

    async def publish(self, name: str, body: dict, retain: bool) -> bool:
        if self.up:
            self.sent.append((name, body, retain))
        return self.up

    def on(self, court: str) -> list[dict]:
        return [body for name, body, _ in self.sent if name == f"{PREFIX}/court/{court}/match"]


async def run_sync(broker: Broker) -> int:
    async with SessionLocal() as s:
        return await sync.sync_courts(s, broker.publish)


# ------------------------------------------------------------------ thông điệp (hàm thuần)

AT = datetime(2026, 11, 18, 9, 0, 0, tzinfo=UTC)


def court_match(fmt: str, team_a: tuple[int, ...], team_b: tuple[int, ...]) -> rooms.CourtMatch:
    return rooms.CourtMatch(7, "S1", fmt, team_a, team_b, AT)


def test_start_message_names_court_mode_players_and_positions():
    doubles = messages.start_message(court_match("2v2", (12, 31), (8, 44)), AT)
    assert doubles == {
        "v": 1,
        "type": "match.start",
        "match_id": "pm-7",
        "mode": "doubles",
        "players": [
            {"id": "12", "side": "A", "slot": "left"},
            {"id": "31", "side": "A", "slot": "right"},
            {"id": "8", "side": "B", "slot": "left"},
            {"id": "44", "side": "B", "slot": "right"},
        ],
        "sent_at": "2026-11-18T09:00:00.000Z",
    }
    singles = messages.start_message(court_match("1v1", (12,), (8,)), AT)
    assert singles["mode"] == "singles"
    assert singles["players"] == [{"id": "12", "side": "A"}, {"id": "8", "side": "B"}]
    assert messages.stop_message("pm-7", AT) == {
        "v": 1,
        "type": "match.stop",
        "match_id": "pm-7",
        "sent_at": "2026-11-18T09:00:00.000Z",
    }
    assert messages.topic(PREFIX, "S1", "match") == "badminton/court/S1/match"


def test_a_lineup_that_does_not_fit_the_format_names_nobody():
    # Máy đo bỏ qua trận không nêu tên ai (không bám, không ghi hình)
    assert messages.start_message(court_match("2v2", (12,), (8, 44)), AT)["players"] == []
    assert messages.start_message(court_match("1v1", (12, 31), (8,)), AT)["players"] == []


RECORD = {
    "v": 1,
    "type": "shot.record",
    "court": "court-1",
    "match_id": "pm-7",
    "shot_id": "9f3c1a-17",
    "impact_utc": "2026-11-18T09:12:31.402Z",
    "speed_kmh": 312.4,
    "speed_sigma_kmh": 9.1,
    "v0_kmh": 338.0,
    "quality": "good",
    "player_id": "12",
    "candidates": ["12"],
    "side": "A",
    "periods": ["day", "week"],
    "previous": {"day": 298.0, "week": 305.5},
    "clip": {
        "bucket": "badminton-clips",
        "object": "court-1/pm-7/9f3c1a-17.mp4",
        "url": "https://clips.example.vn/badminton-clips/court-1/pm-7/9f3c1a-17.mp4",
        "start_utc": "2026-11-18T09:12:21.000Z",
        "duration_s": 20.6,
    },
    "segment": {"bucket": "badminton-segments", "object": "court-1/pm-7/x.mp4", "offset_s": 31.4},
}


def raw(**over) -> bytes:
    return json.dumps({**RECORD, **over}).encode()


def test_record_message_parses():
    shot = messages.parse_record(raw())
    assert (shot.match_ref, shot.shot_ref, shot.player_id) == ("pm-7", "9f3c1a-17", "12")
    assert shot.speed_kmh == 312.4 and shot.test is False
    assert shot.impact_at == datetime(2026, 11, 18, 9, 12, 31, 402000, tzinfo=UTC)
    assert shot.clip_url == RECORD["clip"]["url"]
    doubles = messages.parse_record(raw(player_id=None, candidates=["12", "31"], clip=None))
    assert doubles.player_id is None and doubles.clip_url is None
    assert messages.parse_record(raw(test=True)).test is True


@pytest.mark.parametrize(
    "payload,field",
    [
        (b"{not json SECRET", "payload"),
        (b'["SECRET"]', "payload"),
        (b"x" * 20_000, "payload"),
        (raw(v=2), "v"),
        (raw(type="shot.other"), "type"),
        (raw(speed_kmh="fast-SECRET"), "speed_kmh"),
        (raw(speed_kmh=True), "speed_kmh"),
        (raw(impact_utc="2026-11-18 09:12 SECRET"), "impact_utc"),
        (raw(impact_utc="2026-11-18T09:12:31"), "impact_utc"),  # không múi giờ
        (raw(shot_id=""), "shot_id"),
        (raw(player_id=12), "player_id"),
    ],
)
def test_bad_record_names_the_field_and_never_echoes_the_payload(payload, field):
    with pytest.raises(messages.BadMessage) as err:
        messages.parse_record(payload)
    assert str(err.value).startswith(field) and "SECRET" not in str(err.value)


def test_topics_of_other_things_are_not_a_court():
    assert messages.court_of(PREFIX, "badminton/court/S1/record", "record") == "S1"
    assert messages.court_of(PREFIX, "badminton/court/S1/status", "record") is None
    assert messages.court_of(PREFIX, "badminton/court/_app/shuttletrack-x/status", "status") is None
    assert messages.court_of(PREFIX, "other/court/S1/record", "record") is None
    assert messages.court_of(PREFIX, "badminton/court/S 1/record", "record") is None
    assert messages.topic_filter(PREFIX, "record") == "badminton/court/+/record"


def test_mark_keys_follow_the_local_day_and_the_iso_week():
    tz = settings.tz
    keys = marks.mark_keys(datetime(2026, 11, 18, 23, 59, tzinfo=tz), "badminton:record")
    assert keys == {
        "day": "badminton:record:day:2026-11-18",
        "week": "badminton:record:week:2026-W47",
        "month": "badminton:record:month:2026-11",
        "year": "badminton:record:year:2026",
    }
    # 01/01/2027 là thứ Sáu: còn thuộc tuần ISO 53 của năm 2026
    new_year = marks.mark_keys(datetime(2027, 1, 1, 0, 0, tzinfo=tz), "p")
    assert new_year["week"] == "p:week:2026-W53" and new_year["year"] == "p:year:2027"
    # 17:30 UTC = 00:30 hôm sau giờ VN
    late = datetime(2026, 11, 18, 17, 30, tzinfo=UTC).astimezone(tz)
    assert marks.mark_keys(late, "p")["day"] == "p:day:2026-11-19"


# ------------------------------------------------------------------ lệnh trận


async def test_playing_match_is_started_once_and_stopped_when_it_ends():
    court, broker = court_code(), Broker()
    match_id = await playing(court, "2v2", [-11, -12], [-13, -14])
    assert await run_sync(broker) >= 1
    (start,) = broker.on(court)
    assert start["type"] == "match.start" and start["match_id"] == f"pm-{match_id}"
    assert start["mode"] == "doubles"
    assert [(p["id"], p["side"], p["slot"]) for p in start["players"]] == [
        ("-11", "A", "left"),
        ("-12", "A", "right"),
        ("-13", "B", "left"),
        ("-14", "B", "right"),
    ]
    assert all(retain for name, _, retain in broker.sent)

    await run_sync(broker)
    assert len(broker.on(court)) == 1  # đã phát rồi: không phát lại

    async with SessionLocal() as s:
        await s.execute(
            update(PlayMatch)
            .where(PlayMatch.id == match_id)
            .values(status="finished", score_a=21, score_b=15, winner="a")
        )
        await s.commit()
    await run_sync(broker)
    assert [b["type"] for b in broker.on(court)] == ["match.start", "match.stop"]
    assert broker.on(court)[-1]["match_id"] == f"pm-{match_id}"
    await run_sync(broker)
    assert len(broker.on(court)) == 2
    async with SessionLocal() as s:
        row = await s.get(DeviceCourt, court)
    assert (row.match_ref, row.match_state) == (f"pm-{match_id}", "stopped")


async def test_singles_match_and_a_closed_room():
    court, broker = court_code(), Broker()
    match_id = await playing(court, "1v1", [-21], [-22])
    await run_sync(broker)
    assert broker.on(court)[0]["mode"] == "singles"
    assert broker.on(court)[0]["players"] == [
        {"id": "-21", "side": "A"},
        {"id": "-22", "side": "B"},
    ]
    async with SessionLocal() as s:  # phòng đóng (hết giờ / booking hủy): trận bị bỏ
        room_id = await s.scalar(select(PlayMatch.room_id).where(PlayMatch.id == match_id))
        await s.execute(update(PlayRoom).where(PlayRoom.id == room_id).values(status="closed"))
        await s.execute(
            update(PlayMatch).where(PlayMatch.id == match_id).values(status="abandoned")
        )
        await s.commit()
    await run_sync(broker)
    assert [b["type"] for b in broker.on(court)] == ["match.start", "match.stop"]


async def test_unconfirmed_command_is_sent_again():
    court, broker = court_code(), Broker()
    await playing(court, "1v1", [-31], [-32])
    broker.up = False
    await run_sync(broker)
    async with SessionLocal() as s:
        assert await s.get(DeviceCourt, court) is None  # chưa xác nhận: chưa coi là đã phát
    broker.up = True
    await run_sync(broker)
    assert [b["type"] for b in broker.on(court)] == ["match.start"]


async def test_match_follows_the_booking_to_another_court():
    old, new, broker = court_code(), court_code(), Broker()
    match_id = await playing(old, "1v1", [-41], [-42])
    await run_sync(broker)
    async with SessionLocal() as s:
        room_id = await s.scalar(select(PlayMatch.room_id).where(PlayMatch.id == match_id))
        await s.execute(update(PlayRoom).where(PlayRoom.id == room_id).values(resource_code=new))
        await s.commit()
    await run_sync(broker)
    assert [b["type"] for b in broker.on(old)] == ["match.start", "match.stop"]
    assert [(b["type"], b["match_id"]) for b in broker.on(new)] == [
        ("match.start", f"pm-{match_id}")
    ]


async def test_two_rooms_on_one_court_send_the_later_match():
    court, broker = court_code(), Broker()
    await playing(court, "1v1", [-51], [-52])
    later = await playing(court, "1v1", [-53], [-54])
    async with SessionLocal() as s:
        await s.execute(
            update(PlayMatch)
            .where(PlayMatch.id == later)
            .values(started_at=datetime.now(UTC) + timedelta(seconds=5))
        )
        await s.commit()
    await run_sync(broker)
    assert [b["match_id"] for b in broker.on(court)] == [f"pm-{later}"]


# ------------------------------------------------------------------ cú đập phá mốc


async def take(court: str, payload: bytes) -> str:
    async with SessionLocal() as s:
        return await ingest.record(s, court, payload, datetime.now(UTC))


async def saved(ref: str) -> SpeedRecord | None:
    async with SessionLocal() as s:
        return await s.scalar(select(SpeedRecord).where(SpeedRecord.source_ref == f"st:{ref}"))


async def test_record_with_a_player_becomes_a_device_speed_record(people):
    hv = await people("Tay Đập")
    ref = shot_ref()
    at = datetime.now(UTC) - timedelta(seconds=20)
    payload = raw(shot_id=ref, player_id=str(hv.customer_id), impact_utc=messages.stamp(at))
    assert await take("S1", payload) == "recorded"
    row = await saved(ref)
    assert (row.customer_id, row.speed_kmh, row.court_code) == (hv.customer_id, 312, "S1")
    assert (row.source, row.status, row.device_id) == ("device", "approved", "shuttletrack")
    assert abs((row.measured_at - at).total_seconds()) < 0.01
    assert row.video_url == RECORD["clip"]["url"] and row.video_set_at is not None
    # QoS 1 có thể giao lại: không ghi lần hai
    assert await take("S1", payload) == "duplicate"
    async with SessionLocal() as s:
        rows = await s.scalars(select(SpeedRecord).where(SpeedRecord.source_ref == f"st:{ref}"))
        assert len(list(rows)) == 1
    # Hội viên thấy số đo ở Bảng xếp hạng (nguồn Máy đo, đã duyệt)
    r = await hv.client.get(f"{base.MA}/speed-ranking", params={"period": "year"})
    assert r.status_code == 200 and r.json()["me"]["speed_kmh"] >= 312


async def test_record_without_a_player_id_is_not_kept(people):
    hv = await people("Đánh Đôi")
    ref = shot_ref()
    payload = raw(shot_id=ref, player_id=None, candidates=[str(hv.customer_id), "999"])
    assert await take("S1", payload) == "no_player"
    assert await saved(ref) is None


async def test_test_matches_bad_messages_and_strangers_are_ignored(people):
    hv = await people("Người Thử")
    me = str(hv.customer_id)
    ref = shot_ref()
    assert await take("S1", raw(shot_id=ref, player_id=me, test=True)) == "test"
    assert await take("S1", b"{not json") == "bad_message"
    assert await take("S1", raw(shot_id=ref, player_id="p12")) == "unknown_member"
    assert await take("S1", raw(shot_id=ref, player_id="999999999")) == "unknown_member"
    assert await take("S1", raw(shot_id=ref, player_id=me, speed_kmh=31.0)) == "speed_range"
    assert await take("S1", raw(shot_id=ref, player_id=me, speed_kmh=640.2)) == "speed_range"
    assert await saved(ref) is None


async def test_clip_link_is_kept_only_when_members_can_play_it(people):
    hv = await people("Có Video")
    me = str(hv.customer_id)
    plain, none, long_court = shot_ref(), shot_ref(), shot_ref()
    clip = {**RECORD["clip"], "url": "http://103.20.97.195:9000/badminton-clips/x.mp4"}
    assert await take("S1", raw(shot_id=plain, player_id=me, clip=clip)) == "recorded"
    assert (await saved(plain)).video_url is None  # http: trình duyệt của trang https không phát
    assert await take("S1", raw(shot_id=none, player_id=me, clip=None)) == "recorded"
    assert (await saved(none)).video_url is None
    assert await take("court-number-1", raw(shot_id=long_court, player_id=me)) == "recorded"
    assert (await saved(long_court)).court_code is None  # mã sân dài hơn cột: bỏ sân, giữ số đo


async def test_court_status_is_stored_beside_the_sent_command():
    court, broker = court_code(), Broker()
    match_id = await playing(court, "1v1", [-61], [-62])
    await run_sync(broker)
    body = {"v": 1, "court": court, "online": True, "state": "error", "match_id": f"pm-{match_id}"}
    failed = json.dumps({**body, "error": "no_stream"}).encode()
    async with SessionLocal() as s:
        now = datetime.now(UTC)
        assert await ingest.status(s, court, failed, now)
        assert not await ingest.status(s, court, json.dumps({**body, "test": True}).encode(), now)
        assert not await ingest.status(s, court, b"[]", now)
    async with SessionLocal() as s:
        row = await s.get(DeviceCourt, court)
    assert (row.match_ref, row.match_state) == (f"pm-{match_id}", "started")
    assert (row.app_online, row.app_state, row.app_error) == (True, "error", "no_stream")
    assert row.app_match_ref == f"pm-{match_id}" and row.app_seen_at is not None


# ------------------------------------------------------------------ mốc kỷ lục trong Redis


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expires: dict[str, int] = {}

    async def set(self, key, value, nx=False, exat=None):
        if nx and key in self.values:
            return None
        self.values[key] = value
        self.expires[key] = exat
        return True


async def test_marks_are_the_best_approved_speed_of_each_period(people):
    hv = await people("Kỷ Lục Gia")
    now = datetime.now(UTC)
    local = now.astimezone(settings.tz)
    keys = marks.mark_keys(local, settings.RECORD_MARK_PREFIX)
    payload = raw(
        shot_id=shot_ref(),
        player_id=str(hv.customer_id),
        speed_kmh=499.6,
        impact_utc=messages.stamp(now),
    )
    assert await take("S1", payload) == "recorded"
    redis = FakeRedis()
    async with SessionLocal() as s:
        bests = await marks.refresh(s, redis, now)
    assert bests == {"day": 500, "week": 500, "month": 500, "year": 500}
    assert {redis.values[k] for k in keys.values()} == {"500"}
    # Khóa sống qua hết kỳ: hạn của khóa ngày ở sau nửa đêm nay (giờ VN)
    midnight = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), settings.tz)
    assert redis.expires[keys["day"]] > midnight.timestamp()
    assert redis.expires[keys["year"]] >= redis.expires[keys["month"]] >= redis.expires[keys["day"]]


def reset_raw(**over) -> bytes:
    body = {"v": 1, "type": "records.reset", "court": "S1", "at": messages.stamp(AT), **over}
    return json.dumps(body).encode()


async def reset(court: str, payload: bytes) -> str:
    async with SessionLocal() as s:
        return await ingest.reset(s, court, payload, datetime.now(UTC))


async def test_records_reset_is_ignored_unless_the_demo_switch_is_on(people, monkeypatch):
    hv = await people("Chưa Bật")
    ref = shot_ref()
    assert (
        await take(
            "S1",
            raw(
                shot_id=ref,
                player_id=str(hv.customer_id),
                impact_utc=messages.stamp(datetime.now(UTC)),
            ),
        )
        == "recorded"
    )
    monkeypatch.setattr(settings, "DEVICE_RECORD_RESET", False)
    assert await reset("S1", reset_raw()) == "disabled"
    assert (await saved(ref)).status == "approved"


async def test_records_reset_rejects_todays_device_records_of_that_court_only(people, monkeypatch):
    monkeypatch.setattr(settings, "DEVICE_RECORD_RESET", True)
    hv = await people("Đặt Lại")
    me = str(hv.customer_id)
    court, other = court_code(), court_code()
    now = datetime.now(UTC)
    today, older, elsewhere = shot_ref(), shot_ref(), shot_ref()
    assert (
        await take(
            court, raw(shot_id=today, player_id=me, speed_kmh=333.0, impact_utc=messages.stamp(now))
        )
        == "recorded"
    )
    assert (
        await take(
            court,
            raw(
                shot_id=older,
                player_id=me,
                speed_kmh=250.0,
                impact_utc=messages.stamp(now - timedelta(days=2)),
            ),
        )
        == "recorded"
    )
    assert (
        await take(
            other,
            raw(shot_id=elsewhere, player_id=me, speed_kmh=210.0, impact_utc=messages.stamp(now)),
        )
        == "recorded"
    )
    assert await reset(court, reset_raw(test=True)) == "test"
    assert await reset(court, b"{not json") == "bad_message"
    assert (await saved(today)).status == "approved"

    assert await reset(court, reset_raw(court=court)) == "reset"
    row = await saved(today)
    assert (row.status, row.reject_reason) == ("rejected", ingest.RESET_REASON)
    assert row.video_url == RECORD["clip"]["url"] and row.version == 2  # giữ video, không xóa
    assert (await saved(older)).status == "approved"  # ngày khác
    assert (await saved(elsewhere)).status == "approved"  # sân khác
    # Lần hai: không còn gì để đặt lại
    assert await reset(court, reset_raw(court=court)) == "reset"


async def test_a_reset_from_the_link_rewrites_the_marks_at_once(people, monkeypatch):
    monkeypatch.setattr(settings, "DEVICE_RECORD_RESET", True)
    hv = await people("Mốc Mới")
    court = court_code()
    now = datetime.now(UTC)
    ref = shot_ref()
    assert (
        await take(
            court,
            raw(
                shot_id=ref,
                player_id=str(hv.customer_id),
                speed_kmh=499.0,
                impact_utc=messages.stamp(now),
            ),
        )
        == "recorded"
    )
    redis = FakeRedis()
    async with SessionLocal() as s:
        assert (await marks.refresh(s, redis, now))["day"] == 499
    handled = []

    class FakeLink:
        def __init__(self, handle):
            handled.append(handle)

        def start(self):
            pass

    monkeypatch.setattr(device_link, "Link", FakeLink)
    monkeypatch.setattr(settings, "MQTT_HOST", "broker.test")
    device_link.start(redis)
    await handled[0](f"{PREFIX}/court/{court}/record", reset_raw(court=court))
    assert (await saved(ref)).status == "rejected"
    key = marks.mark_keys(now.astimezone(settings.tz), settings.RECORD_MARK_PREFIX)["day"]
    assert int(redis.values[key]) < 499


async def test_marks_of_a_period_nobody_played_in_are_zero():
    async with SessionLocal() as s:
        assert await records.period_bests(s, date(2031, 1, 6)) == dict.fromkeys(
            ("day", "week", "month", "year"), 0
        )


async def test_keys_of_the_coming_period_exist_before_it_starts():
    tz = settings.tz
    late = datetime(2031, 12, 31, 23, 55, tzinfo=tz)  # 5 phút trước năm mới (thứ Tư)
    redis = FakeRedis()
    async with SessionLocal() as s:
        await marks.refresh(s, redis, late)
    assert redis.values["badminton:record:day:2032-01-01"] == "0"
    assert redis.values["badminton:record:month:2032-01"] == "0"
    assert redis.values["badminton:record:year:2032"] == "0"
    assert "badminton:record:week:2032-W01" in redis.values  # tuần ISO đang chạy, không tạo thêm
    assert len(redis.values) == 7
    redis.values["badminton:record:day:2032-01-01"] = "320"
    async with SessionLocal() as s:
        await marks.refresh(s, redis, late)
    assert redis.values["badminton:record:day:2032-01-01"] == "320"  # tạo sẵn không ghi đè


# ------------------------------------------------------------------ kết nối MQTT (client giả)


class FakeClient:
    def __init__(self) -> None:
        self.subscribed: list = []
        self.acked: list[tuple[int, int]] = []
        self.published: list[tuple[str, str, int, bool]] = []
        self.confirm = True

    def subscribe(self, topics):
        self.subscribed.append(topics)

    def ack(self, mid, qos):
        self.acked.append((mid, qos))

    def publish(self, name, payload, qos=0, retain=False):
        self.published.append((name, payload, qos, retain))
        return SimpleNamespace(
            rc=0, wait_for_publish=lambda timeout: None, is_published=lambda: self.confirm
        )


def message(name: str, payload: bytes, mid: int):
    return SimpleNamespace(topic=name, payload=payload, mid=mid, qos=1)


async def test_link_subscribes_publishes_and_acks_after_handling(monkeypatch):
    monkeypatch.setattr(link, "RETRY_DELAYS", (0.0,))
    seen: list[str] = []
    fail = {"left": 1}

    async def handler(name: str, payload: bytes) -> None:
        if name.endswith("/record") and fail["left"]:
            fail["left"] -= 1
            raise RuntimeError("db down")
        seen.append(name)

    client = FakeClient()
    conn = link.Link(handler, client=client)
    assert await conn.publish("t", {"a": 1}, True) is False and client.published == []
    conn._on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
    assert conn.connected
    assert client.subscribed == [[("badminton/court/+/record", 1), ("badminton/court/+/status", 1)]]
    assert await conn.publish("badminton/court/S1/match", {"v": 1}, True) is True
    assert client.published == [("badminton/court/S1/match", '{"v":1}', 1, True)]
    client.confirm = False
    assert await conn.publish("badminton/court/S1/match", {"v": 1}, True) is False

    conn._loop = asyncio.get_running_loop()
    task = asyncio.create_task(conn._consume())
    conn._on_message(client, None, message("badminton/court/S1/record", b"{}", 5))
    conn._on_message(client, None, message("badminton/court/S1/status", b"{}", 6))
    for _ in range(200):
        if len(client.acked) == 2:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    # Tin lỗi được thử lại rồi mới xác nhận; thứ tự giữ nguyên
    assert seen == ["badminton/court/S1/record", "badminton/court/S1/status"]
    assert client.acked == [(5, 1), (6, 1)]
    conn._on_connect(client, None, None, SimpleNamespace(is_failure=True), None)
    conn._on_disconnect(client, None, None, "lost", None)
    assert not conn.connected


async def test_link_is_off_without_a_broker_host(monkeypatch):
    monkeypatch.setattr(settings, "MQTT_HOST", "")
    assert not settings.device_link_enabled
    assert device_link.start(FakeRedis()) is None
    ctx = {"redis": FakeRedis()}
    await worker.startup(ctx)
    assert ctx["device_link"] is None and ctx["redis"].values == {}
    await worker.shutdown(ctx)
    assert await worker.sync_device_courts({}) == 0
    assert await worker.refresh_record_marks({"redis": FakeRedis()}) == {}
    names = {f.__name__ for f in worker.WorkerSettings.functions}
    assert {"sync_device_courts", "refresh_record_marks"} <= names
