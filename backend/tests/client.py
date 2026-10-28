"""Client HTTP gọi thẳng app (ASGI) cho test; import sau khi conftest đổi DB sang `_test`."""

from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app

API = settings.API_PREFIX


def make_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
