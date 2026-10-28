import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

import app.models  # noqa: F401  (đăng ký toàn bộ model)
import app.modules.notifications.handlers  # noqa: F401  (đăng ký event handler)
from app.core import queue
from app.core.config import settings
from app.core.db import engine
from app.modules.auth import otp_router as auth_otp
from app.modules.auth import router as auth
from app.modules.auth.deps import check_origin
from app.modules.bookings import router as bookings
from app.modules.content import router as content
from app.modules.courts import router as courts
from app.modules.payments import router as payments
from app.modules.staff import router as staff

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await queue.close()


app = FastAPI(
    title=settings.APP_NAME,
    # Chặn CSRF cho mọi route (kể cả module khác) – xem `check_origin`
    dependencies=[Depends(check_origin)],
    lifespan=lifespan,
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
    auth.router,
    auth_otp.router,
    auth.admin_auth_router,
    staff.router,
    courts.router,
    courts.admin_router,
    bookings.router,
    bookings.admin_router,
    payments.admin_router,
    content.router,
    content.admin_router,
):
    app.include_router(r, prefix=settings.API_PREFIX)


@app.get("/health", tags=["system"])
async def health():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok"}
