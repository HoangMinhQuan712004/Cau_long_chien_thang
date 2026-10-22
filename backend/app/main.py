import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

import app.models  # noqa: F401  (đăng ký toàn bộ model)
import app.modules.notifications.handlers  # noqa: F401  (đăng ký event handler)
from app.core.config import settings
from app.core.db import engine
from app.modules.auth import router as auth
from app.modules.bookings import router as bookings
from app.modules.content import router as content
from app.modules.courts import router as courts
from app.modules.payments import router as payments

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title=settings.APP_NAME,
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
    auth.admin_router,
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
