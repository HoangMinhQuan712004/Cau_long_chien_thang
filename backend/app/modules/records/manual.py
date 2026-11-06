"""Số đo nhập tay (T-047): Admin nhập / sửa / xóa / duyệt; hội viên gửi cú đập chờ duyệt.

Hàm ghi **không commit** (router chạy trong ``Idempotency.run``); thông báo hội viên qua
``member_inbox`` – router phát event sau commit.

- Admin nhập -> ``source=admin``, ``status=approved`` ngay.
- Hội viên gửi -> ``source=member``, ``status=pending``, chỉ cho chính mình, 5 lượt / ngày.
- Số đo máy đo (``device``) không sửa / xóa được (403 E-REC-2).
"""

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.audit import AuditActor, audit, audit_change, audit_detail
from app.core.config import settings
from app.core.errors import AppError
from app.modules.booking_engine import api as engine
from app.modules.member_inbox import api as inbox
from app.modules.members import api as members
from app.modules.records import video
from app.modules.records.admin import locked, rows_of, touch
from app.modules.records.models import REJECT_REASON_MAX, SpeedRecord
from app.modules.records.schemas import (
    AdminSpeedRecordRow,
    MySpeedRecord,
    MySpeedRecordList,
    ResourceOption,
    SpeedRecordCreateIn,
    SpeedRecordPatchIn,
    SpeedSubmitIn,
)

MAX_AGE = timedelta(days=365)
CLOCK_SKEW = timedelta(minutes=1)  # đồng hồ máy người dùng chạy nhanh một chút vẫn nhận
SUBMITS_PER_DAY = 5
MINE_LIMIT = 50
VIDEO_PAGE = "/hoi-vien/video-ky-luc"

# Nhãn ô cho nhật ký (trước -> sau)
LABELS = {
    "speed_kmh": "Tốc độ (km/h)",
    "measured_at": "Thời điểm đo",
    "court_code": "Sân",
    "video_url": "Video",
}
STATUS_LABELS = {"approved": "Đã duyệt", "pending": "Chờ duyệt", "rejected": "Bị từ chối"}


# ------------------------------------------------------------------ kiểm dữ liệu chung


def _bad_time() -> AppError:
    return AppError("E-REC-5", "Thời điểm đo không được ở tương lai hoặc quá 365 ngày trước.", 422)


def _check_time(at: datetime) -> datetime:
    now = datetime.now(UTC)
    if at > now + CLOCK_SKEW or at < now - MAX_AGE:
        raise _bad_time()
    return at


async def _active_courts(session: AsyncSession) -> list[ResourceOption]:
    return [
        ResourceOption(code=r.code, name=r.name)
        for r in (await engine.list_resources(session)).items
        if r.is_active
    ]


async def _court(session: AsyncSession, code: str | None) -> str | None:
    """Mã sân (tùy chọn, không phân biệt hoa thường) phải là sân đang hoạt động -> mã đúng như
    danh mục sân; rỗng -> None."""
    key = (code or "").strip().upper()
    if not key:
        return None
    courts = {c.code.upper(): c.code for c in await _active_courts(session)}
    if key not in courts:
        raise AppError("E-REC-6", "Không tìm thấy sân hoặc sân đang ngừng hoạt động.", 422)
    return courts[key]


def _video(url: str | None) -> str | None:
    """Link video (tùy chọn) theo luật T-046 (E-REC-1); rỗng -> None."""
    return video.clean(url) if url and url.strip() else None


def _not_active_member(status: int) -> AppError:
    return AppError("E-REC-7", "Chỉ nhập số đo cho hội viên đang Hoạt động.", status)


async def _active_person(session: AsyncSession, customer_id: int) -> members.RoomPerson | None:
    p = (await members.room_people(session, {customer_id})).get(customer_id)
    return p if p is not None and p.is_active_member else None


def _not_editable() -> AppError:
    return AppError("E-REC-2", "Số đo từ máy đo không sửa hay xóa được.", 403)


def _not_pending() -> AppError:
    return AppError("E-REC-4", "Số đo này không còn ở trạng thái chờ duyệt.", 409)


def _values(r: SpeedRecord) -> dict[str, str | int | None]:
    return {
        "speed_kmh": r.speed_kmh,
        "measured_at": r.measured_at.isoformat(),
        "court_code": r.court_code,
        "video_url": r.video_url,
    }


async def _audit(
    session: AsyncSession,
    actor: AuditActor,
    action: str,
    r: SpeedRecord,
    changes: list,
    **extra: object,
) -> None:
    p = (await members.room_people(session, {r.customer_id})).get(r.customer_id)
    code = p.member_code if p else None
    audit(
        session,
        actor,
        action,
        "speed_record",
        str(r.id),
        audit_detail(
            code,
            p.display_name if p else None,
            changes,
            speed_kmh=r.speed_kmh,
            measured_at=r.measured_at.isoformat(),
            member_code=code,
            source=r.source,
            **extra,
        ),
    )


def _diff(before: dict, after: dict) -> list:
    return [
        audit_change(label, before[key], after[key])
        for key, label in LABELS.items()
        if before[key] != after[key]
    ]


# ------------------------------------------------------------------ Admin


async def create(
    session: AsyncSession, actor: AuditActor, data: SpeedRecordCreateIn
) -> AdminSpeedRecordRow:
    """Admin nhập số đo -> duyệt ngay. 422 E-REC-7 (Mã HV không có / không Hoạt động) · E-REC-5 ·
    E-REC-6 · E-REC-1."""
    customer_id = await members.member_id_by_code(session, data.member_code)
    if customer_id is None or await _active_person(session, customer_id) is None:
        raise _not_active_member(422)
    now = datetime.now(UTC)
    r = SpeedRecord(
        customer_id=customer_id,
        speed_kmh=data.speed_kmh,
        measured_at=_check_time(data.measured_at),
        court_code=await _court(session, data.resource_code),
        source_ref=f"admin:{uuid.uuid4()}",
        source="admin",
        status="approved",
        submitted_by=actor.id,
        reviewed_by=actor.id,
        reviewed_at=now,
        updated_at=now,
        version=1,
    )
    r.set_video(_video(data.video_url), now)
    session.add(r)
    await session.flush()
    await session.refresh(r, ["created_at"])
    empty = dict.fromkeys(LABELS)
    await _audit(session, actor, "record.create_manual", r, _diff(empty, _values(r)))
    return (await rows_of(session, [r]))[0]


async def update(
    session: AsyncSession, actor: AuditActor, record_id: int, data: SpeedRecordPatchIn
) -> AdminSpeedRecordRow:
    """Sửa km/h, thời điểm, sân, video (chỉ ô có gửi). 403 E-REC-2 (máy đo) · 409 E-REC-3 (lệch
    ``version``). Thời điểm chỉ kiểm khi đổi. Không đổi gì -> trả nguyên trạng, không ghi."""
    r = await locked(session, record_id)
    if r.source == "device":
        raise _not_editable()
    if r.version != data.version:
        raise AppError(
            "E-REC-3", "Số đo vừa được sửa ở nơi khác. Vui lòng tải lại rồi sửa tiếp.", 409
        )
    sent = data.model_fields_set
    before = _values(r)
    if "speed_kmh" in sent and data.speed_kmh is not None:
        r.speed_kmh = data.speed_kmh
    if "measured_at" in sent and data.measured_at is not None and data.measured_at != r.measured_at:
        r.measured_at = _check_time(data.measured_at)
    same_court = (data.resource_code or "").strip().upper() == (r.court_code or "").upper()
    if "resource_code" in sent and not same_court:  # sân cũ đã ngừng vẫn giữ được khi không đổi
        r.court_code = await _court(session, data.resource_code)
    if "video_url" in sent and (data.video_url or "").strip() != (r.video_url or ""):
        r.set_video(_video(data.video_url), datetime.now(UTC))
    changes = _diff(before, _values(r))
    if changes:
        touch(r)
        await session.flush()
        await _audit(session, actor, "record.update", r, changes)
    return (await rows_of(session, [r]))[0]


async def delete(session: AsyncSession, actor: AuditActor, record_id: int) -> None:
    """Xóa thật (số đo không phải giao dịch tiền); nhật ký giữ giá trị trước khi xóa.
    403 E-REC-2 (máy đo) · 404."""
    r = await locked(session, record_id)
    if r.source == "device":
        raise _not_editable()
    gone = dict.fromkeys(LABELS)
    await _audit(session, actor, "record.delete", r, _diff(_values(r), gone), status=r.status)
    await session.delete(r)
    await session.flush()


async def _review(session: AsyncSession, actor: AuditActor, record_id: int) -> SpeedRecord:
    r = await locked(session, record_id)
    if r.status != "pending":
        raise _not_pending()
    r.reviewed_by = actor.id
    r.reviewed_at = datetime.now(UTC)
    return r


async def approve(session: AsyncSession, actor: AuditActor, record_id: int) -> AdminSpeedRecordRow:
    """Chờ duyệt -> Đã duyệt (bắt đầu tính hạng / kỷ lục); báo hội viên. 409 E-REC-4."""
    r = await _review(session, actor, record_id)
    r.status = "approved"
    touch(r)
    await session.flush()
    await _audit(
        session,
        actor,
        "record.approve",
        r,
        [audit_change("Trạng thái", STATUS_LABELS["pending"], STATUS_LABELS["approved"])],
    )
    inbox.notify(
        session,
        r.customer_id,
        "record.approved",
        f"Cú đập {r.speed_kmh} km/h của bạn đã được duyệt.",
        VIDEO_PAGE,
        record_id=r.id,
    )
    return (await rows_of(session, [r]))[0]


def clean_reason(raw: str) -> str:
    reason = " ".join((raw or "").split())
    if not reason or len(reason) > REJECT_REASON_MAX:
        raise AppError("E-REC-8", f"Nhập lý do từ chối (tối đa {REJECT_REASON_MAX} ký tự).", 422)
    return reason


async def reject(
    session: AsyncSession, actor: AuditActor, record_id: int, raw_reason: str
) -> AdminSpeedRecordRow:
    """Chờ duyệt -> Bị từ chối + lý do (bắt buộc, ≤ 200 ký tự); báo hội viên kèm lý do.
    422 E-REC-8 · 409 E-REC-4."""
    reason = clean_reason(raw_reason)
    r = await _review(session, actor, record_id)
    r.status = "rejected"
    r.reject_reason = reason
    touch(r)
    await session.flush()
    await _audit(
        session,
        actor,
        "record.reject",
        r,
        [audit_change("Trạng thái", STATUS_LABELS["pending"], STATUS_LABELS["rejected"])],
        reason=reason,
    )
    inbox.notify(
        session,
        r.customer_id,
        "record.rejected",
        f"Cú đập {r.speed_kmh} km/h của bạn bị từ chối: {reason}",
        VIDEO_PAGE,
        record_id=r.id,
    )
    return (await rows_of(session, [r]))[0]


# ------------------------------------------------------------------ Hội viên


@dataclass(frozen=True)
class Submitter:
    user_id: int
    customer_id: int


def _member_actor(submitter: Submitter, person: members.RoomPerson | None) -> AuditActor:
    code = person.member_code if person and person.member_code else str(submitter.customer_id)
    return AuditActor(type="customer", id=submitter.user_id, label=f"Hội viên · {code}")


async def _mine(
    session: AsyncSession, records: list[SpeedRecord], courts: list[ResourceOption] | None = None
) -> list[MySpeedRecord]:
    if courts is None:
        courts = await _active_courts(session)
    names = {c.code: c.name for c in courts}
    if any(r.court_code and r.court_code not in names for r in records):
        names = {r.code: r.name for r in (await engine.list_resources(session)).items}
    return [
        MySpeedRecord(
            id=r.id,
            speed_kmh=r.speed_kmh,
            measured_at=r.measured_at,
            resource_code=r.court_code,
            resource_name=names.get(r.court_code) if r.court_code else None,
            status=r.status,  # type: ignore[arg-type]
            reject_reason=r.reject_reason,
            video=video.parse(r.video_url),
            submitted_at=r.created_at,
            can_withdraw=r.status == "pending",
        )
        for r in records
    ]


def day_bounds(now: datetime) -> tuple[datetime, datetime]:
    """[00:00, 24:00) của ngày giờ VN chứa ``now``."""
    start = datetime.combine(now.astimezone(settings.tz).date(), time(), settings.tz)
    return start, start + timedelta(days=1)


async def _check_daily_limit(session: AsyncSession, customer_id: int, now: datetime) -> None:
    """Tối đa 5 bản gửi / ngày giờ VN (mọi trạng thái; bản đã rút lại là đã xóa nên không đếm).

    Khóa advisory theo người gửi trong transaction: hai lượt gửi cùng lúc không cùng lọt qua.
    """
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtext(f"record.submit:{customer_id}")))
    )
    start, end = day_bounds(now)
    sent = await session.scalar(
        select(func.count())
        .select_from(SpeedRecord)
        .where(
            SpeedRecord.customer_id == customer_id,
            SpeedRecord.source == "member",
            SpeedRecord.created_at >= start,
            SpeedRecord.created_at < end,
        )
    )
    if (sent or 0) >= SUBMITS_PER_DAY:
        raise ratelimit.too_many(max(1, math.ceil((end - now).total_seconds())))


async def submit(session: AsyncSession, me: Submitter, data: SpeedSubmitIn) -> MySpeedRecord:
    """Hội viên gửi cú đập của **chính mình** -> chờ duyệt. 403 E-REC-7 (đang Ngừng) · 422
    E-REC-5 / E-REC-6 / E-REC-1 · 429 E-SEC-5 (đã gửi 5 bản trong ngày giờ VN; lượt lỗi không
    tính; ``Retry-After`` tới 00:00 hôm sau)."""
    person = await _active_person(session, me.customer_id)
    if person is None:
        raise AppError("E-REC-7", "Hội viên đang Ngừng không gửi được số đo.", 403)
    measured_at = _check_time(data.measured_at)
    court = await _court(session, data.resource_code)
    url = _video(data.video_url)
    now = datetime.now(UTC)
    await _check_daily_limit(session, me.customer_id, now)
    r = SpeedRecord(
        customer_id=me.customer_id,
        speed_kmh=data.speed_kmh,
        measured_at=measured_at,
        court_code=court,
        source_ref=f"member:{uuid.uuid4()}",
        source="member",
        status="pending",
        submitted_by=me.user_id,
        updated_at=now,
        version=1,
    )
    r.set_video(url, now)
    session.add(r)
    await session.flush()
    await session.refresh(r, ["created_at"])
    await _audit(
        session,
        _member_actor(me, person),
        "record.submit",
        r,
        _diff(dict.fromkeys(LABELS), _values(r)),
    )
    return (await _mine(session, [r]))[0]


async def list_mine(session: AsyncSession, customer_id: int) -> MySpeedRecordList:
    """Bản tôi đã gửi (mọi trạng thái), mới gửi trước – không có bản của người khác."""
    records = list(
        await session.scalars(
            select(SpeedRecord)
            .where(SpeedRecord.customer_id == customer_id, SpeedRecord.source == "member")
            .order_by(SpeedRecord.created_at.desc(), SpeedRecord.id.desc())
            .limit(MINE_LIMIT)
        )
    )
    courts = await _active_courts(session)
    return MySpeedRecordList(
        items=await _mine(session, records, courts),
        resources=courts,
        daily_limit=SUBMITS_PER_DAY,
    )


async def withdraw(session: AsyncSession, me: Submitter, record_id: int) -> None:
    """Rút lại bản **chờ duyệt** của mình (xóa thật). Không phải của mình / không có -> 404
    (không lộ bản của người khác); đã duyệt / bị từ chối -> 409 E-REC-4."""
    r = await session.scalar(
        select(SpeedRecord)
        .where(
            SpeedRecord.id == record_id,
            SpeedRecord.customer_id == me.customer_id,
            SpeedRecord.source == "member",
        )
        .with_for_update()
    )
    if r is None:
        raise AppError("E-NOT-FOUND", "Không tìm thấy số đo.", 404)
    if r.status != "pending":
        raise _not_pending()
    person = (await members.room_people(session, {me.customer_id})).get(me.customer_id)
    await _audit(
        session,
        _member_actor(me, person),
        "record.delete",
        r,
        _diff(_values(r), dict.fromkeys(LABELS)),
        status=r.status,
    )
    await session.delete(r)
    await session.flush()
