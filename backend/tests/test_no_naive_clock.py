"""Không dùng ngày/giờ theo đồng hồ máy: nghiệp vụ theo giờ VN (múi giờ tenant), còn máy CI và
container production chạy UTC. ``date.today()`` từ 00:00 đến 07:00 giờ VN vẫn là hôm qua.

Dùng ``datetime.now(settings.tz)`` (app) hoặc ``tests.conftest.vn_today()`` (test).
``datetime.now().astimezone()`` vẫn được: ra đúng thời điểm, có múi giờ.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAIVE = re.compile(
    r"\b(?:date|datetime)\.today\(\)"
    r"|\bdatetime\.now\(\)(?!\.astimezone\(\))"
    r"|\butcnow\(\)"
    r"|\btime\.localtime\("
)


def test_no_naive_local_clock_in_app_and_tests():
    hits = []
    for base in ("app", "tests"):
        for path in sorted((ROOT / base).rglob("*.py")):
            if path == Path(__file__).resolve():
                continue
            for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if NAIVE.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{no}: {line.strip()}")
    assert not hits, "Dùng giờ VN thay cho giờ máy:\n" + "\n".join(hits)
