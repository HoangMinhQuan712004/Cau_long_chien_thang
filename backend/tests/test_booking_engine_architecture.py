"""C5 – ranh giới booking engine (ADR-003).

- ``booking_engine/**`` không import ``app.modules.*`` khác.
- Module khác chỉ import ``booking_engine.api`` / ``booking_engine.dto``
  (ngoại lệ: ``app.models`` đăng ký metadata, ``app.main`` gắn router; test được dùng ``testing``).
- Không bảng nào trong schema ``booking`` có FK ra ngoài schema.
"""

import ast
from pathlib import Path

import app.models  # noqa: F401  (nạp toàn bộ metadata)
from app.core.db import Base

APP = Path(__file__).resolve().parent.parent / "app"
ENGINE = APP / "modules" / "booking_engine"
ENGINE_PKG = "app.modules.booking_engine"
# "from app.modules.booking_engine import api" -> ghi nhận cả module gói lẫn tên con
PUBLIC = {ENGINE_PKG, f"{ENGINE_PKG}.api", f"{ENGINE_PKG}.dto"}
# Điểm nối kỹ thuật được phép chạm vào trong engine
WIRING = {
    APP / "models.py": {f"{ENGINE_PKG}.models"},  # import models cho Alembic metadata
    APP / "main.py": {f"{ENGINE_PKG}.router"},  # gắn router HTTP của engine
}


def _in_engine(name: str) -> bool:
    return name == ENGINE_PKG or name.startswith(f"{ENGINE_PKG}.")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


def test_engine_does_not_import_other_modules():
    offenders = []
    for path in ENGINE.rglob("*.py"):
        for name in _imports(path):
            if name.startswith("app.modules.") and not _in_engine(name):
                offenders.append(f"{path.relative_to(APP)}: {name}")
    assert offenders == []


def test_other_code_uses_only_engine_facade():
    offenders = []
    for path in APP.rglob("*.py"):
        if ENGINE in path.parents:
            continue
        allowed = WIRING.get(path, set())
        for name in _imports(path):
            facade_member = name.startswith((f"{ENGINE_PKG}.api.", f"{ENGINE_PKG}.dto."))
            if _in_engine(name) and not facade_member and name not in PUBLIC | allowed:
                offenders.append(f"{path.relative_to(APP)}: {name}")
    assert offenders == []


def test_engine_tables_have_no_foreign_keys_outside_schema():
    offenders = []
    tables = [t for t in Base.metadata.tables.values() if t.schema == "booking"]
    assert len(tables) >= 8
    for table in tables:
        if table.name != "tenant":
            assert "tenant_id" in table.c, f"{table.name} thiếu tenant_id"
            assert not table.c.tenant_id.nullable
        for fk in table.foreign_keys:
            if fk.column.table.schema != "booking":
                offenders.append(f"{table.name}.{fk.parent.name} -> {fk.target_fullname}")
    assert offenders == []
