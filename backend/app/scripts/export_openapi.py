"""In OpenAPI schema ra stdout (không cần chạy server / DB).

Chạy: python -m app.scripts.export_openapi > openapi.json
CI dùng file này để kiểm tra frontend/src/lib/api/schema.d.ts không bị lệch với backend.
"""

import json
import sys

from app.main import app

json.dump(app.openapi(), sys.stdout, ensure_ascii=False, indent=2)
sys.stdout.write("\n")
