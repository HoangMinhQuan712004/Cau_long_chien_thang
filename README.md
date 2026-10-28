# Sân Cầu Lông – Quản lý & đặt sân

Modular monolith: **FastAPI** (backend) + **Next.js 16** (frontend), PostgreSQL, Redis.

```
project_caulong/
├── backend/                 FastAPI, chia module theo domain
│   ├── app/core/            config, db, security, event bus nội bộ
│   ├── app/modules/
│   │   ├── auth/            đăng nhập chung, nhân viên, quên mật khẩu (OTP)
│   │   ├── courts/          sân, bảng giá theo khung giờ, PriceCalculator
│   │   ├── bookings/        đặt sân, chống trùng lịch, lịch trống
│   │   ├── payments/        ghi nhận thanh toán (cổng online: TODO)
│   │   ├── notifications/   lắng nghe event, OTP Zalo (gửi thật: TODO)
│   │   └── content/         bài viết phục vụ SEO
│   ├── app/workers/         ARQ: tự hủy đơn giữ chỗ quá hạn, gửi OTP
│   ├── alembic/             migration
│   └── tests/
├── frontend/                Next.js App Router (Cache Components)
│   └── src/
│       ├── app/(public)/    trang SEO: /, /dat-san, /bang-gia, /tin-tuc, tài khoản
│       ├── app/admin/       dashboard chủ sân / nhân viên (noindex)
│       ├── app/sitemap.ts, robots.ts
│       ├── lib/api/         client sinh từ OpenAPI (server.ts / client.ts)
│       └── proxy.ts         chặn sớm /admin, /tai-khoan khi chưa đăng nhập
└── docker-compose.yml
```

## Chạy dev

Yêu cầu: **Python 3.15**, **Node.js 26** (LTS), Docker. CI và image production dùng đúng các bản này.

Chỉ có 2 file env: `.env` ở thư mục gốc (cổng docker compose, `BACKEND_URL`, `NEXT_PUBLIC_SITE_URL` cho frontend)
và `backend/.env`. Mẫu: `.env.example` (gốc) và `backend/.env.example`.

```bash
# 0. .env ở thư mục gốc: cổng docker + biến frontend (đổi cổng nếu bị trùng)
cp .env.example .env

# 1. DB + Redis
docker compose up -d db redis

# 2. Backend
cd backend
cp .env.example .env            # backend/.env – sửa SECRET_KEY; DATABASE_URL/REDIS_URL theo cổng ở .env gốc
python -m venv .venv && .venv/Scripts/activate   # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
python -m app.scripts.seed       # admin + 4 sân + bảng giá mẫu
uvicorn app.main:app --reload    # http://localhost:8000/docs
arq app.workers.worker.WorkerSettings   # terminal khác: worker hủy đơn quá hạn + gửi OTP

# 3. Frontend
cd frontend                      # đọc .env ở thư mục gốc, không cần file env riêng
npm install
npm run dev                      # http://localhost:3000
```

Tài khoản dev (một màn đăng nhập `/dang-nhap` cho cả 3 loại, nhập SĐT hoặc tên đăng nhập):
- Admin do seed tạo: SĐT `FIRST_ADMIN_PHONE` / mật khẩu `FIRST_ADMIN_PASSWORD` trong `backend/.env`
  (mẫu `0912345678` / `Admin@12345`; DB tạo trước 28/10 dùng `admin12345`).
- Nhân viên: Admin tạo ở `/admin/nhan-vien`; tên đăng nhập tự sinh `<tên>.<mã>` (vd `an.nv007`).
- Mật khẩu mới: ≥ 8 ký tự, có chữ in hoa và chữ số hoặc ký tự đặc biệt (mật khẩu cũ vẫn đăng nhập được).
- Khách: tự đăng ký bằng SĐT.
- Quên mật khẩu (khách + Admin): chưa có khóa Zalo nên OTP in ra log của worker
  (`arq app.workers.worker.WorkerSettings`, cần `ENV=development` và cùng `REDIS_URL` với API).

Chạy toàn bộ bằng Docker: `docker compose --profile app up --build`.

## Lệnh thường dùng

| Việc | Lệnh |
|---|---|
| Test backend | `cd backend && pytest` (tự dùng DB `<tên db>_test`, cần tạo trước) |
| Lint backend | `ruff check . && ruff format .` |
| Tạo migration | `alembic revision --autogenerate -m "mô tả"` → **đọc lại file sinh ra** |
| Sinh type API cho FE | `cd frontend && npm run gen:api` (backend phải đang chạy) |
| Lint / build FE | `npm run lint` / `npm run build` |

## CI/CD (GitHub Actions)

**CI** – [.github/workflows/ci.yml](.github/workflows/ci.yml), chạy trên mọi PR và push lên `main`:

| Job | Kiểm tra |
|---|---|
| Backend | ruff lint + format, `alembic upgrade head` trên DB mới, `alembic check` (model ↔ migration), downgrade → upgrade, pytest với Postgres thật |
| Frontend | ESLint, `next build` (gồm TypeScript) |
| API contract | Sinh lại `schema.d.ts` từ OpenAPI của backend, fail nếu lệch → nhắc chạy `npm run gen:api` |

**CD** – [.github/workflows/cd.yml](.github/workflows/cd.yml), chỉ chạy khi CI trên `main` xanh (hoặc chạy tay):

1. Build & push image lên GHCR: `ghcr.io/<owner>/<repo>-api` và `-web`, tag = commit SHA + `latest`.
2. Deploy qua SSH (**tắt mặc định**): copy [deploy/docker-compose.prod.yml](deploy/docker-compose.prod.yml) lên server,
   `docker compose pull && up -d`. Migration tự chạy khi container `api` khởi động.

### Bật deploy

1. Server (VPS) cài Docker; tạo thư mục, vd `/opt/caulong`, đặt file `.env` theo [backend/.env.example](backend/.env.example), đổi bắt buộc:
   `ENV=production`, `POSTGRES_PASSWORD` (chỉ chữ/số; compose ghép vào `DATABASE_URL`), `SECRET_KEY` (≥ 32 ký tự ngẫu nhiên),
   `COOKIE_SECURE=true`, `CORS_ORIGINS=["https://<domain>"]`, `FIRST_ADMIN_PHONE`/`FIRST_ADMIN_PASSWORD` (không dùng giá trị mẫu),
   `GOOGLE_CLIENT_ID` (nếu bật Google; frontend cần cùng giá trị LÚC BUILD ⇒ đặt thêm GitHub Variable `GOOGLE_CLIENT_ID` cho CD).
2. Đặt reverse proxy có HTTPS (Caddy/Nginx) trỏ domain → `127.0.0.1:3000`. Proxy phải gửi IP thật của khách qua
   `X-Forwarded-For` (Caddy làm sẵn; Nginx: `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`) –
   backend dùng IP này để giới hạn đăng nhập sai / gửi mã / đăng ký. Backend chỉ tin header này khi request đến từ
   `TRUSTED_PROXIES`: compose prod đặt sẵn `127.0.0.1,::1,172.16.0.0/12,192.168.0.0/16` (container `web` gọi `api`
   qua mạng compose). Đổi subnet mạng docker thì đặt `TRUSTED_PROXIES` trong `.env` cho khớp – sai thì mọi thao tác
   ghi khi đã đăng nhập (đăng xuất, đổi dữ liệu…) báo 403 `origin_forbidden` và mọi khách bị tính chung một IP (giới hạn đăng nhập sai chặn tất cả).
   `CORS_ORIGINS` (`.env`) thêm domain thật nếu có trang khác gọi API: POST/PATCH/DELETE kèm cookie phiên từ origin
   lạ bị chặn 403 `origin_forbidden` (cùng domain qua Next rewrite luôn được).
3. GitHub repo → Settings → Environments → tạo `production`, thêm:
   - **Secrets**: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` (private key), `DEPLOY_KNOWN_HOSTS` (`ssh-keyscan <host>`)
   - **Variables** (repo): `DEPLOY_ENABLED=true`, `SITE_URL=https://your-domain.vn`, `DEPLOY_PATH=/opt/caulong`
4. Lần deploy đầu, tạo tài khoản chủ sân: `docker compose exec api python -m app.scripts.seed`.

`SITE_URL` được build vào image web (canonical, sitemap) – đổi domain thì chạy lại CD.

## Quyết định thiết kế quan trọng

**Chống đặt trùng ở tầng DB.** `booking_slots` có exclusion constraint
`EXCLUDE USING gist (court_id WITH =, time_range WITH &&) WHERE (is_active)`.
Hai request đồng thời đặt cùng giờ → chỉ một request thành công, request còn lại nhận 409.
Range là `[start, end)` nên 18h–19h và 19h–20h không tính là trùng.

**Luồng đơn.** Khách đặt online → `pending`, giữ chỗ `HOLD_MINUTES` phút → thanh toán →
`confirmed`. Worker chuyển đơn quá hạn sang `expired` và giải phóng slot.
Nhân viên đặt tại quầy có thể xác nhận ngay hoặc giữ chỗ không thời hạn.

**Module giao tiếp qua service + event.** Module không query bảng của module khác;
`bookings` gọi `courts.service`, phát event `booking.confirmed` cho `notifications`.
Khi cần tách service chỉ cần thay `app/core/events.py` bằng message broker.

**Auth.** JWT trong cookie httpOnly (access 30 phút, refresh 14 ngày, path `/api/v1/auth`).
Trình duyệt gọi `/api/v1/*` cùng domain, Next rewrite sang FastAPI → không cần CORS.
Chống CSRF: cookie `SameSite=Lax` + `check_origin` (request đổi trạng thái kèm cookie phiên phải có `Origin` cùng
host hoặc trong `CORS_ORIGINS`).
Client tự gọi `/auth/refresh` khi gặp 401; trang đăng nhập tự khôi phục phiên nếu refresh còn hạn.

**SEO.** Trang public prerender tĩnh, dữ liệu qua `'use cache'` + `cacheLife` (tự làm mới).
Mỗi trang tự khai báo `alternates.canonical`; JSON-LD `SportsActivityLocation` (trang chủ),
`Article` (bài viết); `sitemap.xml`, `robots.txt` sinh động. Trang cá nhân/admin `noindex`
và đọc cookie bên trong `<Suspense>` (yêu cầu của Cache Components).

**Giờ giấc.** Mọi thời điểm lưu `timestamptz`; nghiệp vụ (giờ mở cửa, bảng giá theo thứ)
tính theo `TIMEZONE=Asia/Ho_Chi_Minh`.

## Việc tiếp theo gợi ý

- Tích hợp cổng thanh toán (PayOS/VNPay/MoMo) trong `payments/service.py`: xác thực chữ ký webhook, idempotent theo `provider_ref`.
- Đặt lịch cố định hằng tuần (RecurringBooking).
- Form CRUD sân / bảng giá / bài viết trong `/admin`.
- Gọi `revalidateTag("posts")` (qua route handler có secret) khi admin đăng bài để sitemap/tin tức cập nhật ngay.
- Gửi Zalo ZNS thật (OTP: `TODO(zalo-zns)` trong `notifications/zalo.py`; thông báo đơn từ `notifications/handlers.py`) qua worker.
- Upload ảnh lên S3/R2, Sentry.
