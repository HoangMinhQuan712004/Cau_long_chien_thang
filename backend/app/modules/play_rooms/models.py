"""Phòng chơi (T-017): mỗi khối booking (mã con) = một phòng, người đặt là Host.

Id hồ sơ khách (``customer_id``) là tham chiếu sang module Hội viên – không FK chéo module (như
``customer_ref`` của booking engine).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

FORMATS = ("2v2", "1v1")


class PlayRoom(Base):
    __tablename__ = "play_room"
    __table_args__ = (
        UniqueConstraint("booking_code"),
        CheckConstraint("status IN ('open', 'closed')", name="status"),
        CheckConstraint("format IN ('2v2', '1v1')", name="format"),
        CheckConstraint("start_at < end_at", name="range"),
        Index("ix_play_room_status_start_at", "status", "start_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    booking_code: Mapped[str] = mapped_column(String(30))
    resource_code: Mapped[str] = mapped_column(String(10))
    resource_name: Mapped[str] = mapped_column(String(50))
    resource_type_name: Mapped[str] = mapped_column(String(50))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    host_customer_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(10), server_default=text("'open'"))
    format: Mapped[str] = mapped_column(String(5), server_default=text("'2v2'"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlayRoomMember(Base):
    __tablename__ = "play_room_member"
    __table_args__ = (
        UniqueConstraint("room_id", "customer_id"),
        CheckConstraint("queue_state IN ('waiting', 'playing')", name="queue_state"),
        Index("ix_play_room_member_customer_id", "customer_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("play_room.id", ondelete="CASCADE"))
    customer_id: Mapped[int] = mapped_column(Integer)
    queue_state: Mapped[str] = mapped_column(String(10), server_default=text("'waiting'"))
    # Vào Hàng chờ lúc nào (mới vào / vừa đánh xong) – bốc ưu tiên người chờ lâu (AC13, AC15)
    waiting_since: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlayRoomRequest(Base):
    """Xin vào (``join``, người xin = ``customer_id``) hoặc lời mời (``invite``, người được mời)."""

    __tablename__ = "play_room_request"
    __table_args__ = (
        CheckConstraint("kind IN ('join', 'invite')", name="kind"),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'cancelled', 'expired')", name="status"
        ),
        Index(
            "uq_play_room_request_pending",
            "room_id",
            "customer_id",
            "kind",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_play_room_request_customer_status", "customer_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("play_room.id", ondelete="CASCADE"))
    customer_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), server_default=text("'pending'"))
    invited_by: Mapped[int | None] = mapped_column(Integer)  # Host gửi lời mời
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlayMatch(Base):
    """Trận trong phòng: ``drawn`` (vừa bốc) -> ``playing`` -> ``finished`` | ``abandoned``."""

    __tablename__ = "play_match"
    __table_args__ = (
        UniqueConstraint("room_id", "no"),
        CheckConstraint("status IN ('drawn', 'playing', 'finished', 'abandoned')", name="status"),
        CheckConstraint("format IN ('2v2', '1v1')", name="format"),
        CheckConstraint(
            "status <> 'finished' OR (score_a IS NOT NULL AND score_b IS NOT NULL "
            "AND score_a <> score_b AND winner IS NOT NULL)",
            name="finished_score",
        ),
        CheckConstraint("score_a BETWEEN 0 AND 99 AND score_b BETWEEN 0 AND 99", name="score"),
        CheckConstraint("winner IN ('a', 'b')", name="winner"),
        # Mỗi phòng tối đa một trận đang bốc / đang chơi
        Index(
            "uq_play_match_active",
            "room_id",
            unique=True,
            postgresql_where=text("status IN ('drawn', 'playing')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("play_room.id", ondelete="CASCADE"))
    no: Mapped[int] = mapped_column(SmallInteger)
    format: Mapped[str] = mapped_column(String(5))
    team_a: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    team_b: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    # {"<customer_id>": "tên hiển thị lúc bốc"} – Lịch sử / Xếp hạng giữ tên cả khi đã rời
    names: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(10), server_default=text("'drawn'"))
    drawn_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score_a: Mapped[int | None] = mapped_column(SmallInteger)
    score_b: Mapped[int | None] = mapped_column(SmallInteger)
    winner: Mapped[str | None] = mapped_column(String(1))
