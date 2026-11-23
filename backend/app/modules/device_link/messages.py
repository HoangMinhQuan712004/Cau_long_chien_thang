"""Thông điệp MQTT với máy đo tốc độ ShuttleTrack (hợp đồng v1) – hàm thuần, không I/O.

Hợp đồng nằm ở ``docs/MATCH-FLOW.md`` của ShuttleTrack:

- ``{prefix}/court/{sân}/match`` (server -> máy đo, retained): ``match.start`` / ``match.stop``;
- ``{prefix}/court/{sân}/record`` (máy đo -> server): ``shot.record`` – cú đập phá mốc kỷ lục;
- ``{prefix}/court/{sân}/status`` (máy đo -> server, retained): trạng thái sân phía máy đo.

``{sân}`` = mã sân (``resource_code``). Id người chơi = id hồ sơ hội viên (chuỗi số), mã trận =
``pm-<id trận>``. Đội A / B của phòng chơi = đầu sân A / B của máy đo; vị trí ``left`` / ``right``
của đánh đôi theo thứ tự trong đội hình.
"""

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from app.modules.play_rooms import api as rooms

V = 1
MAX_PAYLOAD_BYTES = 16 * 1024
COURT = re.compile(r"[A-Za-z0-9_-]{1,64}")
MODES = {"2v2": "doubles", "1v1": "singles"}
SLOTS = ("left", "right")
REF_MAX = 96
STATES = ("idle", "starting", "running", "error")


class BadMessage(ValueError):
    """Thông điệp không dùng được; nội dung chỉ nêu tên ô, không chép lại payload."""


def topic(prefix: str, court: str, kind: str) -> str:
    return f"{prefix}/court/{court}/{kind}"


def topic_filter(prefix: str, kind: str) -> str:
    """Mọi sân. Không khớp ``{prefix}/court/_app/{client}/status`` (thêm một tầng)."""
    return f"{prefix}/court/+/{kind}"


def court_of(prefix: str, name: str, kind: str) -> str | None:
    """Mã sân của topic ``{prefix}/court/{sân}/{kind}``; topic khác -> None."""
    head = f"{prefix}/court/"
    if not name.startswith(head):
        return None
    parts = name[len(head) :].split("/")
    if len(parts) != 2 or parts[1] != kind or not COURT.fullmatch(parts[0]):
        return None
    return parts[0]


def stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def match_ref(match_id: int) -> str:
    return f"pm-{match_id}"


def players_of(match: rooms.CourtMatch) -> list[dict[str, str]]:
    """Người chơi của trận theo hợp đồng. Đội hình không khớp thể thức (không xảy ra với dữ liệu
    đúng) -> danh sách rỗng: máy đo bỏ qua trận không có ai được nêu tên."""
    doubles = MODES[match.format] == "doubles"
    size = 2 if doubles else 1
    if len(match.team_a) != size or len(match.team_b) != size:
        return []
    players = []
    for side, team in (("A", match.team_a), ("B", match.team_b)):
        for slot, customer_id in zip(SLOTS, team, strict=False):
            player = {"id": str(customer_id), "side": side}
            if doubles:
                player["slot"] = slot
            players.append(player)
    return players


def start_message(match: rooms.CourtMatch, sent_at: datetime) -> dict:
    return {
        "v": V,
        "type": "match.start",
        "match_id": match_ref(match.match_id),
        "mode": MODES[match.format],
        "players": players_of(match),
        "sent_at": stamp(sent_at),
    }


def stop_message(ref: str, sent_at: datetime) -> dict:
    return {"v": V, "type": "match.stop", "match_id": ref, "sent_at": stamp(sent_at)}


def _object(raw: bytes) -> dict:
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise BadMessage("payload: too_long")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise BadMessage("payload: invalid_json") from None
    if not isinstance(data, dict):
        raise BadMessage("payload: not_an_object")
    if data.get("v") != V:
        raise BadMessage("v: unsupported")
    return data


def _text(data: dict, key: str, max_len: int, *, optional: bool = False) -> str | None:
    value = data.get(key)
    if value is None and optional:
        return None
    if not isinstance(value, str) or not 0 < len(value) <= max_len:
        raise BadMessage(f"{key}: invalid")
    return value


def _moment(data: dict, key: str) -> datetime:
    value = data.get(key)
    try:
        at = datetime.fromisoformat(value) if isinstance(value, str) and len(value) <= 40 else None
    except ValueError:
        at = None
    if at is None or at.tzinfo is None:
        raise BadMessage(f"{key}: invalid")
    return at.astimezone(UTC)


@dataclass(frozen=True)
class ShotRecord:
    match_ref: str
    shot_ref: str
    impact_at: datetime
    speed_kmh: float
    player_id: str | None  # None: máy đo không biết ai đánh
    clip_url: str | None
    test: bool


def parse_record(raw: bytes) -> ShotRecord:
    data = _object(raw)
    if data.get("type") != "shot.record":
        raise BadMessage("type: invalid")
    speed = data.get("speed_kmh")
    if isinstance(speed, bool) or not isinstance(speed, int | float) or not math.isfinite(speed):
        raise BadMessage("speed_kmh: invalid")
    clip = data.get("clip")
    url = clip.get("url") if isinstance(clip, dict) else None
    return ShotRecord(
        match_ref=_text(data, "match_id", REF_MAX) or "",
        shot_ref=_text(data, "shot_id", REF_MAX) or "",
        impact_at=_moment(data, "impact_utc"),
        speed_kmh=float(speed),
        player_id=_text(data, "player_id", 64, optional=True),
        clip_url=url if isinstance(url, str) else None,
        test=data.get("test") is True,
    )


@dataclass(frozen=True)
class CourtStatus:
    online: bool
    state: str | None
    error: str | None
    match_ref: str | None
    test: bool


def parse_status(raw: bytes) -> CourtStatus:
    data = _object(raw)
    online = data.get("online")
    state = data.get("state")
    if not isinstance(online, bool) or (state is not None and state not in STATES):
        raise BadMessage("status: invalid")
    return CourtStatus(
        online=online,
        state=state,
        error=_text(data, "error", 40, optional=True),
        match_ref=_text(data, "match_id", REF_MAX, optional=True),
        test=data.get("test") is True,
    )
