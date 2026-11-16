"""Lệnh cũ của T-030 – nay chuyển sang lệnh dữ liệu mẫu chung (T-034).

    python -m app.modules.records.seed_demo [--clear]  ==  python -m app.scripts.seed_demo [--clear]

Từ chối khi ``ENV=production`` (exit 2), như lệnh mới.
"""

from app.scripts.seed_demo import main

if __name__ == "__main__":
    raise SystemExit(main())
