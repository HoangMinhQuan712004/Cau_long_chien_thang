"""Luồng trực tiếp của máy đo: ``shot.record`` ghi ngay, ``shot.clip`` gắn video sau, tin trực tiếp
lên Redis cho popup chúc mừng, websocket của hội viên, và route phát video qua domain web."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.core.db import SessionLocal
from app.main import app
from app.modules.auth import api as auth
from app.modules.device_link import ingest, messages
from app.modules.members.models import Customer
from app.modules.records import api as records
from app.modules.records import clips, live
from app.modules.records.models import SpeedRecord
from tests import test_device_link as dl
from tests import test_play_rooms as base

people = base.people

TAG = uuid.uuid4().hex[:6]
CLIP_URL = "https://chienthang.example.vn/api/v1/clips/badminton-clips/S1/pm-7/a.mp4"


def ref() -> str:
    return f"{TAG}{uuid.uuid4().hex}-9"


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    async with SessionLocal() as s:
        await s.execute(delete(SpeedRecord).where(SpeedRecord.source_ref.like(f"st:{TAG}%")))
        await s.commit()


def clip_raw(**over) -> bytes:
    body = {
        "v": 1,
        "type": "shot.clip",
        "court": "S1",
        "match_id": "pm-7",
        "shot_id": "x",
        "clip": {"bucket": "badminton-clips", "object": "S1/pm-7/a.mp4", "url": CLIP_URL},
        "segment": None,
    }
    return json.dumps({**body, **over}).encode()


def record_raw(shot: str, player: int, **over) -> bytes:
    at = datetime.now(UTC) - timedelta(seconds=5)
    return dl.raw(
        shot_id=shot,
        player_id=str(player),
        impact_utc=messages.stamp(at),
        clip=None,
        clip_pending=True,
        **over,
    )


class Seen:
    def __init__(self) -> None:
        self.ids: list[int] = []

    async def __call__(self, record_id: int) -> None:
        self.ids.append(record_id)


async def row(shot: str) -> SpeedRecord | None:
    async with SessionLocal() as s:
        return await s.scalar(select(SpeedRecord).where(SpeedRecord.source_ref == f"st:{shot}"))


# ------------------------------------------------------------------ tin shot.clip


def test_clip_message_parses_and_the_type_is_sniffed():
    got = messages.parse_clip(clip_raw(shot_id="9f3c1a-17"))
    assert (got.shot_ref, got.clip_url, got.clip_error, got.test) == (
        "9f3c1a-17",
        CLIP_URL,
        None,
        False,
    )
    failed = messages.parse_clip(clip_raw(clip=None, clip_error="ffmpeg_failed", test=True))
    assert (failed.clip_url, failed.clip_error, failed.test) == (None, "ffmpeg_failed", True)
    assert messages.record_type(clip_raw()) == "shot.clip"
    assert messages.record_type(dl.raw()) == "shot.record"
    assert messages.record_type(b"{nope SECRET") is None
    with pytest.raises(messages.BadMessage) as e:
        messages.parse_clip(clip_raw(shot_id="", clip="SECRET"))
    assert "SECRET" not in str(e.value)
    with pytest.raises(messages.BadMessage):
        messages.parse_clip(dl.raw())


# ------------------------------------------------------------------ ghi ngay, video sau


async def test_record_comes_first_and_its_clip_is_attached_later(people):
    hv = await people("Đập Nhanh")
    shot, saved, attached = ref(), Seen(), Seen()
    async with SessionLocal() as s:
        outcome = await ingest.record(
            s, "S1", record_raw(shot, hv.customer_id), datetime.now(UTC), saved
        )
    assert outcome == ingest.RECORDED
    first = await row(shot)
    assert first.video_url is None and saved.ids == [first.id]
    async with SessionLocal() as s:
        outcome = await ingest.clip(s, "S1", clip_raw(shot_id=shot), datetime.now(UTC), attached)
    assert outcome == ingest.ATTACHED and attached.ids == [first.id]
    later = await row(shot)
    assert later.video_url == CLIP_URL and later.video_set_at is not None
    # QoS 1 giao lại: không gắn lần hai, không phát lại tin
    async with SessionLocal() as s:
        again = await ingest.clip(s, "S1", clip_raw(shot_id=shot), datetime.now(UTC), attached)
    assert again == "has_video" and attached.ids == [first.id]


async def test_clips_that_cannot_be_attached_change_nothing(people):
    hv = await people("Chưa Video")
    shot, seen = ref(), Seen()
    async with SessionLocal() as s:
        await ingest.record(s, "S1", record_raw(shot, hv.customer_id), datetime.now(UTC))

    async def take(raw: bytes) -> str:
        async with SessionLocal() as s:
            return await ingest.clip(s, "S1", raw, datetime.now(UTC), seen)

    assert await take(clip_raw(shot_id=ref())) == "no_record"
    assert await take(clip_raw(shot_id=shot, clip=None, clip_error="upload_failed")) == "no_clip"
    plain = {"bucket": "badminton-clips", "object": "a.mp4", "url": "http://10.0.0.5:9000/a.mp4"}
    assert await take(clip_raw(shot_id=shot, clip=plain)) == "bad_video"
    assert await take(clip_raw(shot_id=shot, test=True)) == "test"
    assert await take(b"{not json") == "bad_message"
    assert (await row(shot)).video_url is None and seen.ids == []


# ------------------------------------------------------------------ thẻ trực tiếp, ẩn danh


async def test_live_card_is_anonymous_to_others_unless_the_player_shows_their_name(people):
    hv, other = await people("Người Đập"), await people("Người Xem")
    shot = ref()
    async with SessionLocal() as s:
        await ingest.record(s, "S1", record_raw(shot, hv.customer_id), datetime.now(UTC))
    rid = (await row(shot)).id
    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.id == hv.customer_id).values(show_on_records=False)
        )
        await s.commit()
        mine = await records.live_card(s, rid, hv.customer_id)
        theirs = await records.live_card(s, rid, other.customer_id)
    assert (mine.display_name, mine.is_me, mine.speed_kmh, mine.video) == (
        "Người Đập",
        True,
        312,
        None,
    )
    assert (theirs.display_name, theirs.is_me, theirs.avatar_url) == (
        "Hội viên ẩn danh",
        False,
        None,
    )
    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.id == hv.customer_id).values(show_on_records=True)
        )
        await s.commit()
        await ingest.clip(s, "S1", clip_raw(shot_id=shot), datetime.now(UTC))
    async with SessionLocal() as s:
        shown = await records.live_card(s, rid, other.customer_id)
        assert await records.live_card(s, 2_000_000_000, other.customer_id) is None
    assert shown.display_name == "Người Đập" and shown.video.kind == "file"
    body = json.dumps(shown.model_dump(mode="json"))
    assert str(hv.customer_id) not in body.replace(str(rid), "")


async def test_access_token_names_the_member(people):
    hv = await people("Có Phiên")
    token = hv.client.cookies.get(auth.ACCESS_COOKIE)
    async with SessionLocal() as s:
        member = await auth.member_of_token(s, token)
        assert member is not None and member.customer_id == hv.customer_id
        assert await auth.member_of_token(s, "not-a-token") is None


# ------------------------------------------------------------------ kênh Redis


class FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = fail

    async def publish(self, channel: str, data: str) -> int:
        if self.fail:
            raise ConnectionError("redis://user:SECRET@host")
        self.sent.append((channel, data))
        return 1


async def test_live_messages_carry_only_the_event_and_the_record_id(caplog):
    redis = FakeRedis()
    await records.publish_live(redis, "record.new", 42)
    assert redis.sent == [(live.CHANNEL, json.dumps({"event": "record.new", "record_id": 42}))]
    await records.publish_live(FakeRedis(fail=True), "record.video", 42)  # không ném lỗi
    assert "SECRET" not in caplog.text
    assert live._parse(redis.sent[0][1]) == ("record.new", 42)
    assert live._parse(b'{"event": "other", "record_id": 1}') is None
    assert live._parse(b"garbage") is None


# ------------------------------------------------------------------ websocket


def test_websocket_needs_the_site_origin_and_a_member_session():
    origin = settings.ALLOWED_ORIGINS[0]
    with TestClient(app) as client:
        path = f"{settings.API_PREFIX}/member-area/records/live"
        with pytest.raises(WebSocketDisconnect) as e:
            with client.websocket_connect(path, headers={"Origin": "https://evil.example"}):
                pass
        assert e.value.code == live.CLOSE_ORIGIN
        with client.websocket_connect(path, headers={"Origin": origin}) as ws:
            with pytest.raises(WebSocketDisconnect) as e:
                ws.receive_text()
        assert e.value.code == live.CLOSE_UNAUTHORIZED


# ------------------------------------------------------------------ phát video qua domain web


@pytest.fixture
def minio(monkeypatch):
    """MinIO giả sau ``CLIPS_ORIGIN``; ghi lại request nó nhận."""
    seen: list[httpx.Request] = []
    data = bytes(range(256)) * 4

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if not request.url.path.endswith("/ok.mp4"):
            return httpx.Response(404, text="<Error>NoSuchKey</Error>")
        rng = request.headers.get("range")
        if rng == "bytes=0-9":
            return httpx.Response(
                206,
                content=data[:10],
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes 0-9/{len(data)}",
                    "Accept-Ranges": "bytes",
                    "X-Amz-Request-Id": "internal",
                },
            )
        return httpx.Response(200, content=data, headers={"Content-Type": "video/mp4"})

    real = httpx.AsyncClient

    def client(*args, **kwargs):
        return real(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(clips.httpx, "AsyncClient", client)
    monkeypatch.setattr(settings, "CLIPS_ORIGIN", "http://10.0.0.5:9000")
    monkeypatch.setattr(settings, "CLIPS_BUCKET", "badminton-clips")
    return seen


async def get(path: str, **headers) -> httpx.Response:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.get(f"{settings.API_PREFIX}/clips/{path}", headers=headers)


async def test_clip_is_streamed_from_minio_with_ranges(minio):
    whole = await get("badminton-clips/S1/pm-7/ok.mp4")
    assert whole.status_code == 200 and len(whole.content) == 1024
    assert whole.headers["content-type"] == "video/mp4"
    part = await get("badminton-clips/S1/pm-7/ok.mp4", Range="bytes=0-9")
    assert part.status_code == 206 and part.content == bytes(range(10))
    assert part.headers["content-range"] == "bytes 0-9/1024"
    assert "x-amz-request-id" not in part.headers
    assert str(minio[-1].url) == "http://10.0.0.5:9000/badminton-clips/S1/pm-7/ok.mp4"


@pytest.mark.parametrize(
    "path",
    [
        "other-bucket/S1/ok.mp4",
        "badminton-clips/../secret/ok.mp4",
        "badminton-clips/S1/ok.txt",
        "badminton-clips/S1/missing.mp4",
    ],
)
async def test_only_videos_of_the_clips_bucket_are_served(minio, path):
    r = await get(path)
    assert r.status_code == 404 and "NoSuchKey" not in r.text


async def test_clips_are_off_without_an_origin(minio, monkeypatch):
    monkeypatch.setattr(settings, "CLIPS_ORIGIN", "")
    assert (await get("badminton-clips/S1/ok.mp4")).status_code == 404
    assert minio == []
