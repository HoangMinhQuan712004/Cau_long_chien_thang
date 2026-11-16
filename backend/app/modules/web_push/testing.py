"""Bản giả dịch vụ push cho test / CI (T-076 Q1) – không bao giờ gửi ra mạng.

fake = testing.install()            # conftest đã cài sẵn cho cả bộ test
fake.fail(endpoint, 410)            # ép lỗi theo endpoint: 404 · 410 · 500 · 301 · "timeout"
await testing.drain(ENQUEUED_JOBS)  # chạy các job push đang chờ (worker giả)
fake.sent                           # [Sent(user_id, subscription_id, title, body, url, ttl…)]
"""

from dataclasses import dataclass, field

from app.modules.web_push import jobs, sender
from app.modules.web_push.sender import Message, Result, Target

JOBS = {"push_test", "push_member_notification", "push_staff"}


@dataclass(frozen=True)
class Sent:
    user_id: int
    subscription_id: int
    endpoint: str
    title: str
    body: str
    url: str
    tag: str | None
    ttl: int


@dataclass
class FakePushService:
    sent: list[Sent] = field(default_factory=list)
    # endpoint -> mã HTTP trả về, hoặc "timeout" / "network"
    failures: dict[str, int | str] = field(default_factory=dict)
    attempts: list[str] = field(default_factory=list)  # mọi endpoint đã thử gửi (kể cả lỗi)

    def fail(self, endpoint: str, outcome: int | str | None) -> None:
        """Ép kết quả cho một endpoint; None -> gửi được lại."""
        if outcome is None:
            self.failures.pop(endpoint, None)
        else:
            self.failures[endpoint] = outcome

    def clear(self) -> None:
        self.sent.clear()
        self.attempts.clear()
        self.failures.clear()

    def to_user(self, user_id: int) -> list[Sent]:
        return [s for s in self.sent if s.user_id == user_id]

    async def send(self, target: Target, message: Message) -> Result:
        self.attempts.append(target.endpoint)
        outcome = self.failures.get(target.endpoint)
        if isinstance(outcome, str):
            return Result(None, outcome)
        if outcome is not None:
            return Result(outcome)
        self.sent.append(
            Sent(
                target.user_id,
                target.subscription_id,
                target.endpoint,
                message.title,
                message.body,
                message.url,
                message.tag,
                message.ttl,
            )
        )
        return Result(201)


def install() -> FakePushService:
    fake = FakePushService()
    sender.set_sender(fake)
    return fake


async def run(job: str, args: tuple) -> None:
    await getattr(jobs, job)({}, *args)


async def drain(enqueued: list[tuple[str, tuple]]) -> int:
    """Chạy (và lấy ra khỏi danh sách) các job push đã đẩy vào hàng đợi; trả số job đã chạy."""
    picked = [(job, args) for job, args in enqueued if job in JOBS]
    enqueued[:] = [(job, args) for job, args in enqueued if job not in JOBS]
    for job, args in picked:
        await run(job, args)
    return len(picked)
