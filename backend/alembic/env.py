import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Schema được quản lý: public (mặc định) + booking (booking engine, ADR-003)
MANAGED_SCHEMAS = {None, "public", "booking"}


# Bảng của luồng đặt sân cũ đã đổi tên (T-006 §8) – giữ dữ liệu, không còn model, Alembic bỏ qua
LEGACY_PREFIX = "legacy_"


def include_name(name, type_, parent_names) -> bool:
    if type_ == "schema":
        return name in MANAGED_SCHEMAS
    if type_ == "table":
        return not name.startswith(LEGACY_PREFIX)
    return True


COMMON_OPTS = {
    "target_metadata": target_metadata,
    "include_schemas": True,
    "include_name": include_name,
}


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        literal_binds=True,
        **COMMON_OPTS,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, **COMMON_OPTS)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
