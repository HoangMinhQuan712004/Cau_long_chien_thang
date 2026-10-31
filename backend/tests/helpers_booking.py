"""Helper dùng chung cho test đặt sân quản trị (T-006)."""

import asyncio
import uuid
from datetime import date, datetime, time, timedelta

from app.core.config import settings
from tests.conftest import API, idem

BK = f"{API}/booking"
FD = f"{API}/front-desk"


def now() -> datetime:
    return datetime.now(settings.tz)


def today() -> date:
    return now().date()


def at(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(), settings.tz) + timedelta(hours=hour)


async def safe_hour() -> int:
    """Giờ của khung đang diễn ra (luôn đặt được).

    Trong phút cuối của giờ thì chờ sang giờ mới: test chạy vài giây giữa lúc lấy giờ và gửi
    request, qua mốc đổi giờ khung sẽ thành "đã qua" (E-004) -> test chập chờn.
    """
    n = now()
    if n.minute == 59:
        await asyncio.sleep(61 - n.second)
    return now().hour


async def new_court(admin, **overrides) -> dict:
    """Sân mới mở 00:00–24:00, không cao điểm – mỗi test một sân riêng để không đụng nhau."""
    body = {
        "name": f"Sân T6 {uuid.uuid4().hex[:8]}",
        "resource_type_code": "thuong",
        "open_time": "00:00",
        "close_time": "24:00",
        "peak_bands": [],
        **overrides,
    }
    r = await admin.post(f"{BK}/resources", json=body, headers=idem())
    assert r.status_code == 201, r.text
    return r.json()


def member(code: str = "HV0031") -> dict:
    return {"member_code": code}


def temp(name: str = "Khách tạm", phone: str | None = None, note: str | None = None) -> dict:
    body = {"full_name": name, "phone": phone or random_phone()}
    if note is not None:
        body["note"] = note
    return {"temp": body}


def random_phone() -> str:
    return "08" + str(uuid.uuid4().int)[:8]


class SingleBlock:
    """Response đặt quầy một khối (dạng cũ) cho test T-006: ``.json()`` trả **khối đầu tiên**
    (đã có ``order_code``) khi tạo thành công; lỗi trả nguyên văn. Response gốc: ``.raw``."""

    def __init__(self, raw):
        self.raw = raw
        self.status_code = raw.status_code
        self.headers = raw.headers
        self.text = raw.text

    def json(self):
        body = self.raw.json()
        if self.status_code == 201 and isinstance(body, dict) and "bookings" in body:
            return body["bookings"][0]
        return body


async def book(
    client,
    resource_code: str,
    start_hour: int,
    end_hour: int | None = None,
    customer: dict | None = None,
    day: date | None = None,
    headers: dict | None = None,
) -> SingleBlock:
    r = await client.post(
        f"{FD}/bookings",
        json={
            "resource_code": resource_code,
            "date": (day or today()).isoformat(),
            "start_hour": start_hour,
            "end_hour": end_hour if end_hour is not None else start_hour + 1,
            "customer": customer if customer is not None else member(),
        },
        headers=headers or idem(),
    )
    return SingleBlock(r)


async def book_order(
    client,
    blocks: list[tuple[str, int, int]],
    customer: dict | None = None,
    day: date | None = None,
    headers: dict | None = None,
):
    """Đặt quầy nhiều khối (T-019): ``blocks`` = [(mã sân, giờ bắt đầu, giờ kết thúc)]."""
    return await client.post(
        f"{FD}/bookings",
        json={
            "date": (day or today()).isoformat(),
            "blocks": [{"resource_code": c, "start_hour": a, "end_hour": b} for c, a, b in blocks],
            "customer": customer if customer is not None else member(),
        },
        headers=headers or idem(),
    )


async def calendar(client, day: date | None = None) -> dict:
    r = await client.get(f"{BK}/calendar", params={"date": (day or today()).isoformat()})
    assert r.status_code == 200, r.text
    return r.json()
