# Sân cầu lông Chiến Thắng – bối cảnh dự án (mọi session đều đọc)

Website quản lý và đặt sân cầu lông cho **một chủ sân** (không phải marketplace).
Production: https://chienthang.superbai.vip · Repo: github.com/HoangMinhQuan712004/Cau_long_chien_thang

Dự án chạy theo mô hình **6 session Claude** làm việc song song. Vai của bạn nằm trong prompt
hệ thống (`.claude/agents/<vai>.md`). Quy trình phối hợp: [.claude/team/PROTOCOL.md](.claude/team/PROTOCOL.md) – **đọc trước khi làm bất cứ việc gì**.

## Nghiệp vụ (nguồn sự thật – không tự ý đổi, mọi thay đổi qua ARCHITECT)

| Khái niệm | Quy tắc |
|---|---|
| Vai người dùng | `admin` = chủ sân, `staff` = nhân viên quầy, `customer` = khách |
| Sân | Nhiều sân con (Sân 1..n) trong một cụm; sân `is_active=false` không đặt được |
| Giờ mở cửa | `OPEN_TIME`–`CLOSE_TIME` (mặc định 05:00–23:00), múi giờ `Asia/Ho_Chi_Minh` |
| Bước thời gian | `SLOT_MINUTES` = 30 phút; đặt tối thiểu `MIN_BOOKING_MINUTES` = 60; trước tối đa `MAX_ADVANCE_DAYS` = 30 ngày |
| Giá | `PriceRule` theo thứ trong tuần + khung giờ, VND/giờ; rule gắn sân cụ thể thắng rule chung, sau đó `priority` cao hơn thắng; tính theo từng bước 30 phút |
| Trạng thái đơn | `pending` (giữ chỗ) → `confirmed` → `completed`; hoặc `cancelled` / `expired` |
| Giữ chỗ | Đơn online `pending` hết hạn sau `HOLD_MINUTES` = 10 phút → worker chuyển `expired`, nhả slot. Đơn tại quầy chưa xác nhận không tự hết hạn |
| Hủy | Khách chỉ hủy được đơn `pending`; đơn `confirmed` do staff/admin hủy (liên quan hoàn tiền) |
| Thanh toán | Hiện chỉ ghi nhận tay (tiền mặt/chuyển khoản) → xác nhận đơn trong **cùng transaction**. Cổng online (PayOS/VNPay/MoMo) chưa làm |
| Chống trùng lịch | **Exclusion constraint Postgres** trên `booking_slots(court_id, time_range)` khi `is_active`; range `[start, end)` nên 18–19h và 19–20h không trùng. Không bao giờ bỏ/né constraint này |

## Kiến trúc

- **Backend** `backend/`: FastAPI modular monolith, Python 3.15, SQLAlchemy 2 async + asyncpg, Alembic, ARQ worker (Redis).
  Module trong `app/modules/<domain>/` (`models`, `schemas`, `service`, `router`). Module **không query bảng của module khác** –
  gọi qua `service`; phản ứng chéo qua event `app/core/events.py`.
- **Frontend** `frontend/`: Next.js 16.4 App Router với **Cache Components**, Node 26, Tailwind v4.
  Đây KHÔNG phải Next.js quen thuộc: đọc `frontend/AGENTS.md` và docs trong `frontend/node_modules/next/dist/docs/` trước khi viết code.
  Trang public = SEO (prerender + `'use cache'`); dữ liệu theo người dùng đọc cookie bên trong `<Suspense>`.
  API client có type sinh từ OpenAPI: `frontend/src/lib/api/schema.d.ts` (**không sửa tay** – `npm run gen:api`).
- **Auth**: JWT trong cookie httpOnly; trình duyệt gọi `/api/v1/*` cùng domain, Next rewrite sang FastAPI.
- **Hạ tầng**: Docker Compose; CI/CD GitHub Actions → GHCR → VPS 103.20.97.195 (`/opt/caulong`, Caddy HTTPS). Push `main` = deploy production.

## Lệnh hay dùng (chạy trong worktree của bạn)

| Việc | Lệnh |
|---|---|
| Lint backend | `cd backend; .venv\Scripts\ruff check .; .venv\Scripts\ruff format --check .` |
| Test backend | `cd backend; .venv\Scripts\python -m pytest -q` (cần DB: `docker compose up -d db` ở repo chính) |
| Migration mới | `.venv\Scripts\alembic revision --autogenerate -m "..."` → **đọc lại file**; `alembic check` phải sạch |
| Chạy API | `.venv\Scripts\uvicorn app.main:app --reload --port <port của vai>` |
| Sinh type API | `cd frontend; $env:API_SCHEMA_URL="http://localhost:<port API>/api/v1/openapi.json"; npm run gen:api` |
| Lint/build FE | `cd frontend; npm run lint; npm run build` |

## Quy tắc chung

- Ngôn ngữ trao đổi: tiếng Việt. Code, tên biến, commit message: tiếng Anh.
- Commit nhỏ, message rõ; cuối commit thêm dòng `Co-Authored-By` theo hướng dẫn của Claude Code.
- Không commit secret; không đọc/dán nội dung `.env`, khóa SSH, token vào board hay tin nhắn.
- Không push lên `main`, không SSH vào production – trừ RELEASE-INTEGRATION.
