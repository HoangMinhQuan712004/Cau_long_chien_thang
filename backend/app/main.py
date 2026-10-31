from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

import app.models  # noqa: F401  (đăng ký toàn bộ model)
import app.modules.member_inbox.handlers  # noqa: F401  (đăng ký event handler)
import app.modules.members.handlers  # noqa: F401  (đăng ký event handler)
import app.modules.notifications.handlers  # noqa: F401  (đăng ký event handler)
import app.modules.payments.handlers  # noqa: F401  (đăng ký event handler)
import app.modules.play_rooms.handlers  # noqa: F401  (đăng ký event handler)
from app.core.config import settings
from app.core.context import RequestContextMiddleware, setup_logging
from app.core.db import engine
from app.core.middleware import BodyLimitMiddleware, OriginCheckMiddleware
from app.core.ratelimit import RateLimitMiddleware
from app.modules.audit_log import router as audit_log
from app.modules.auth import account_router
from app.modules.auth import router as auth
from app.modules.booking_engine import router as booking_engine
from app.modules.content import router as content
from app.modules.front_desk import router as front_desk
from app.modules.member_area import home_router as member_home
from app.modules.member_area import router as member_area
from app.modules.member_inbox import router as member_inbox
from app.modules.members import me_router as member_me
from app.modules.members import racket_router
from app.modules.members import router as members
from app.modules.payments import router as payments
from app.modules.play_rooms import router as play_rooms
from app.modules.web_booking import router as web_booking

setup_logging()

app = FastAPI(
    title=settings.APP_NAME,
    # Server (staging/production): không công khai tài liệu API
    openapi_url=None if settings.is_deployed else f"{settings.API_PREFIX}/openapi.json",
    docs_url=None if settings.is_deployed else "/docs",
    redoc_url=None,
)

# Middleware thêm sau nằm NGOÀI:
# RequestContext -> RateLimit -> BodyLimit -> OriginCheck -> CORS -> app
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(OriginCheckMiddleware)
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestContextMiddleware)

for r in (
    auth.router,
    account_router.router,
    auth.admin_router,
    auth.staff_router,
    content.router,
    content.admin_router,
    booking_engine.router,
    members.router,
    member_area.router,
    member_home.router,
    play_rooms.router,
    member_inbox.router,
    racket_router.router,
    member_me.router,
    front_desk.router,
    web_booking.router,
    payments.router,
    audit_log.router,
):
    app.include_router(r, prefix=settings.API_PREFIX)


@app.get("/health", tags=["system"])
async def health():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok"}
