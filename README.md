# Sân Cầu Lông – Quản lý & đặt sân

Modular monolith: **FastAPI** (backend) + **Next.js 16** (frontend), PostgreSQL, Redis.

```
project_caulong/
├── backend/                 FastAPI, chia module theo domain
│   ├── app/core/            config, db, security, event bus nội bộ
│   ├── app/modules/
│   │   ├── auth/            user, role (admin/staff/customer), JWT cookie
│   │   ├── booking_engine/  sân, giờ, bảng giá, lịch, booking, sự kiện/vé, thu tiền (schema `booking`)
│   │   ├── front_desk/      đặt sân tại quầy: ghép hội viên + booking_engine
│   │   ├── members/         hội viên và hồ sơ tạm (tối thiểu)
│   │   ├── web_booking/     API public cho khách: lịch, lượt thanh toán (checkout), tra cứu (T-008)
│   │   ├── payments/        webhook SePay, bảng `payments.bank_transaction`, Tiền về cần xử lý (T-008)
│   │   ├── notifications/   lắng nghe event (email/Zalo: TODO)
│   │   └── content/         bài viết phục vụ SEO
│   ├── app/workers/         ARQ: outbox, nhả giữ chỗ quá hạn, dọn nhật ký/idempotency
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

## Môi trường

Ba nơi chạy code. Nhánh `dev` là mặc định của repo; `main` chỉ nhận code khi chủ dự án duyệt phát hành.

| | Local | Dev | Production |
|---|---|---|---|
| Địa chỉ | `http://localhost:3000` (web), `:8000/docs` (API) | https://chienthang-dev.superbai.vip | https://chienthang.superbai.vip |
| Nhánh | nhánh việc của bạn | `dev` – push là tự deploy | `main` – merge là tự deploy |
| Thư mục trên server | – | `/opt/caulong-dev` (compose project `caulong-dev`) | `/opt/caulong` (project `caulong`) |
| Image tag | – | `dev-<commit>` và `dev` | `<commit>` và `latest` |
| Dữ liệu | DB Docker cục bộ | Dữ liệu thử, DB tách hẳn production | Dữ liệu thật |
| Chỉ mục Google | – | `X-Robots-Tag: noindex, nofollow` | Có |

Quy tắc dùng:

- **Dev chỉ chứa dữ liệu thử.** Link không có mật khẩu, đừng nhập thông tin khách thật.
- Hai môi trường dùng chung một VPS nhưng khác thư mục, container, volume DB, `.env` và image tag. Deploy dev không chạm production.
- Quy trình: nhánh việc → PR vào `dev` → CI xanh → merge → CD deploy link dev → kiểm thử → PR `dev → main` khi chủ dự án đồng ý.
- Hotfix production: nhánh từ `main`, PR vào `main`, sau đó merge ngược `main` vào `dev`.

## Chạy dev

Yêu cầu: **Python 3.15**, **Node.js 26** (LTS), Docker. CI và image production dùng đúng các bản này.

### Cách nhanh: một lệnh ở thư mục gốc

Chuẩn bị **một lần** (script báo lỗi nếu thiếu):

```powershell
cd backend
copy .env.example .env                         # sửa SECRET_KEY nếu cần
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
cd ..\frontend
copy .env.example .env.local
npm install
cd ..
```

Chạy hằng ngày, từ thư mục gốc repo:

```powershell
npm run dev
```

Lệnh này bật DB + Redis (`docker compose up -d --wait db redis`), chạy `alembic upgrade head`, rồi chạy song song
`uvicorn --reload` (API) và `next dev` (web). Log có tiền tố `[be]` / `[fe]`; **Ctrl+C tắt cả hai**. Mặc định:

| | Địa chỉ |
|---|---|
| API | http://localhost:8010 (tài liệu: `/docs`) |
| Web | http://localhost:3000 |

| Lệnh | Việc |
|---|---|
| `npm run dev` | DB + Redis → migrate → API + web |
| `npm run dev:be` | DB + Redis → migrate → chỉ API |
| `npm run dev:fe` | Chỉ web (trỏ về API theo `API_PORT`) |
| `npm run seed` | DB + Redis → migrate → dữ liệu mẫu (`python -m app.scripts.seed`) |
| `npm run db` | Chỉ bật DB + Redis |

Đổi cổng bằng biến môi trường `API_PORT` / `WEB_PORT`, hoặc ghi vào file `dev.env` ở thư mục gốc (đã `.gitignore`, mỗi dòng `KEY=value`):

```powershell
# tạm thời cho một lần chạy
$env:API_PORT = "8101"; $env:WEB_PORT = "3101"; npm run dev
```

Lưu ý:

- Cổng đang bị chiếm → script dừng và nói tiến trình nào đang giữ cổng; đổi cổng hoặc tắt tiến trình đó.
- Next chỉ cho **một** `next dev` cho mỗi thư mục `frontend/`. Đang có `next dev` chạy sẵn thì tắt nó trước.
- Request ghi (POST/PUT/PATCH/DELETE) kèm cookie cần `Origin` nằm trong `ALLOWED_ORIGINS` của `backend/.env`.
  Mặc định chỉ có `http://localhost:3000`; nếu đổi `WEB_PORT` thì thêm, ví dụ `ALLOWED_ORIGINS=["http://localhost:3101"]`
  (script in cảnh báo khi thiếu). Chi tiết: [docs/booking-engine-api.md](docs/booking-engine-api.md).
- Script **không** chạy worker (outbox, nhả giữ chỗ quá hạn). Cần worker thì mở terminal khác: `cd backend; .venv\Scripts\arq app.workers.worker.WorkerSettings`.

### Từng bước (thủ công)

```bash
# 1. DB + Redis  (đổi cổng trong .env ở thư mục gốc nếu bị trùng, xem .env.example)
docker compose up -d db redis

# 2. Backend
cd backend
cp .env.example .env            # sửa SECRET_KEY, DATABASE_URL nếu đổi cổng
python -m venv .venv && .venv/Scripts/activate   # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
python -m app.scripts.seed       # admin; khi ENV khác production: 6 sân, bảng giá, Lễ/Tết, hội viên mẫu
uvicorn app.main:app --reload    # http://localhost:8000/docs
arq app.workers.worker.WorkerSettings   # terminal khác: worker (outbox, nhả giữ chỗ quá hạn)

# 3. Frontend
cd frontend
cp .env.example .env.local
npm install
npm run dev                      # http://localhost:3000
```

Tài khoản chủ sân mặc định: `admin@example.com` / `admin12345` (đổi trong `backend/.env`).

Chạy toàn bộ bằng Docker: `docker compose --profile app up --build`.

API nền tảng booking engine (Idempotency-Key, mã lỗi, bảng quyền, biến môi trường bảo mật): [docs/booking-engine-api.md](docs/booking-engine-api.md).

## Đặt online và SePay (T-008)

> Backend xong ở nhánh `be/T-008-web-khach`; chưa vào `dev` cho tới khi RELEASE đẩy. Chi tiết API, mã lỗi, webhook: [docs/booking-engine-api.md](docs/booking-engine-api.md) mục 10.

Khách đặt sân trên web, chuyển khoản QR qua **SePay**; SePay báo tiền về bằng webhook, server tạo booking. Giữ chỗ **5 phút** (+ 60 giây ân hạn nhận tiền báo trễ).

### Biến môi trường (`backend/.env`; trên server: `.env` của từng môi trường)

| Biến | Ví dụ / mặc định | Ghi chú |
|---|---|---|
| `SEPAY_BANK_CODE` | `Vietcombank` | Mã ngân hàng dùng trong link QR `qr.sepay.vn` |
| `SEPAY_BANK_NAME` | `Vietcombank` | Tên hiển thị cho khách |
| `SEPAY_ACCOUNT_NUMBER` | – | Số tài khoản nhận tiền |
| `SEPAY_ACCOUNT_NAME` | – | Tên chủ tài khoản hiển thị cho khách |
| `SEPAY_WEBHOOK_SECRET` | – | **Secret.** Khóa ký webhook; chỉ để trong `.env`, không ghi vào repo |
| `SEPAY_TIMESTAMP_TOLERANCE_SECONDS` | `0` | `0` = không chặn theo tuổi timestamp (ADR-001) |
| `ONLINE_HOLD_MINUTES` | `5` | Thời gian giữ chỗ |
| `ONLINE_HOLD_GRACE_SECONDS` | `60` | Ân hạn nhận tiền báo trễ |
| `PAYMENTS_SIMULATE` | `false` | Chỉ máy dev / link dev (`ENV=staging`). `ENV=production` mà bật thì API không khởi động |

Đủ 5 biến `SEPAY_*` đầu thì đặt online mới bật. Thiếu thì khách vẫn xem được lịch nhưng nút Tiếp tục khóa và hiện "gọi hotline", nên production chạy được trước khi có tài khoản SePay.
`ENV` chỉ nhận `development`, `staging` (link dev), `production`; `staging` và `production` bắt buộc `SECRET_KEY` ≥ 32 ký tự.

### Thử trên máy dev (không cần tài khoản SePay)

1. Trong `backend/.env` đặt giá trị **giả**, rồi chạy lại API (`npm run dev` hoặc `uvicorn`):

   ```
   SEPAY_BANK_CODE=Vietcombank
   SEPAY_BANK_NAME=Vietcombank
   SEPAY_ACCOUNT_NUMBER=0123456789
   SEPAY_ACCOUNT_NAME=SAN CAU LONG TEST
   SEPAY_WEBHOOK_SECRET=chuoi-bi-mat-chi-de-thu
   PAYMENTS_SIMULATE=true
   ```

2. Chạy migration một lần để có schema `payments`: `cd backend; .venv\Scripts\alembic upgrade head`.
3. Mở `http://localhost:3000/dat-san`, chọn ô, nhập họ tên + SĐT, bấm xác nhận. Trang thanh toán hiện **Nội dung CK** dạng `BK20261020023` (chính là `pay_ref`) và số tiền.
4. Giả lập tiền về bằng tài khoản Admin. Lệnh ghi cần cookie phiên, header `Origin` thuộc `ALLOWED_ORIGINS` (mặc định `http://localhost:3000`) và `Idempotency-Key` mới mỗi lần. Ví dụ PowerShell, đổi `pay_ref` và `amount` theo trang thanh toán:

   ```powershell
   $h = @{ Origin = "http://localhost:3000" }
   $s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
   Invoke-RestMethod -Method Post -Uri http://localhost:3000/api/v1/auth/login -WebSession $s -Headers $h `
     -ContentType "application/json" -Body '{"email":"admin@example.com","password":"admin12345"}'
   $h["Idempotency-Key"] = [guid]::NewGuid().ToString()
   Invoke-RestMethod -Method Post -Uri http://localhost:3000/api/v1/payments/dev/simulate -WebSession $s -Headers $h `
     -ContentType "application/json" -Body '{"pay_ref":"BK20261020023","amount":288000}'
   ```

   Kết quả là `BankTransactionOut` (`outcome`, `refund_amount`, `booking_codes`). Lần sau nhớ đổi `Idempotency-Key`. Đổi `localhost:3000` nếu bạn chạy `WEB_PORT` khác (và thêm origin đó vào `ALLOWED_ORIGINS`).
5. Trang thanh toán tự chuyển sang "Đặt sân thành công". Thử `amount` nhỏ hơn → `partial` (vẫn chờ); lớn hơn → `applied` kèm `refund_amount`.
6. Admin xem tiền cần hoàn / không khớp mã ở `GET /api/v1/payments/bank-transactions`; giao diện `/admin/tien-ve` do FRONTEND làm.

### Người dùng cấu hình SePay (một lần, trước khi bật production)

Việc của chủ dự án, không phải của code. Tên menu trên my.sepay.vn có thể khác theo thời điểm.

1. Tạo tài khoản SePay và liên kết tài khoản ngân hàng nhận tiền; ghi số tài khoản vào `SEPAY_ACCOUNT_NUMBER`.
2. **Mẫu mã thanh toán**: tiền tố `BK`, đuôi **11 ký tự số** (khớp `BK20261020023`). SePay tách mã này vào trường `code` của webhook; nếu SePay không tách được, server tự tìm `BK` + 11 số trong nội dung chuyển khoản.
3. **Webhook**: URL `https://chienthang.superbai.vip/api/v1/payments/sepay/webhook` (dev: `https://chienthang-dev.superbai.vip/api/v1/payments/sepay/webhook`), phương thức POST, bật **ký HMAC** và chép khóa ký vào `SEPAY_WEBHOOK_SECRET` trong `.env` của server tương ứng (việc của người dùng; không gửi qua board hay tin nhắn).
4. Báo RELEASE chạy lại stack để nạp biến mới. Kiểm bằng một giao dịch thật số tiền nhỏ: booking phải ra `paid` trong vài giây.
5. Secret nghi lộ → xoay khóa trên my.sepay.vn và cập nhật `.env` trên server.

Giao dịch không tự khớp (sai nội dung, tiền về sau khi hết hạn, trả thừa) không bị mất: nằm ở "Tiền về cần xử lý" để Admin hoàn tiền thủ công rồi bấm Đã xử lý.

## Lệnh thường dùng

| Việc | Lệnh |
|---|---|
| Test backend | `cd backend && pytest` (tự dùng DB `<tên db>_test`, cần tạo trước) |
| Lint backend | `ruff check . && ruff format .` |
| Tạo migration | `alembic revision --autogenerate -m "mô tả"` → **đọc lại file sinh ra** |
| Sinh type API cho FE | `cd frontend && npm run gen:api` (backend phải đang chạy) |
| Lint / build FE | `npm run lint` / `npm run build` |

## CI/CD (GitHub Actions)

**CI** – [.github/workflows/ci.yml](.github/workflows/ci.yml), chạy trên mọi PR và push lên `main` hoặc `dev`
(commit chỉ đổi `*.md`, `docs/**`, `.claude/**` thì bỏ qua → không chạy CI, không deploy):

| Job | Kiểm tra |
|---|---|
| Backend | ruff lint + format, `alembic upgrade head` trên DB mới, `alembic check` (model ↔ migration), downgrade → upgrade, pytest với Postgres thật |
| Frontend | ESLint, `next build` (gồm TypeScript) |
| API contract | Sinh lại `schema.d.ts` từ OpenAPI của backend, fail nếu lệch → nhắc chạy `npm run gen:api` |

**CD** – [.github/workflows/cd.yml](.github/workflows/cd.yml), chạy khi CI trên `dev` hoặc `main` xanh (hoặc chạy tay):

| | CI xanh trên `dev` | CI xanh trên `main` |
|---|---|---|
| GitHub Environment | `dev` | `production` |
| Image tag | `dev-<commit>` + `dev` | `<commit>` + `latest` |
| `NEXT_PUBLIC_SITE_URL` build vào web | `DEV_SITE_URL` (mặc định https://chienthang-dev.superbai.vip) | `SITE_URL` |
| Thư mục server / compose project | `/opt/caulong-dev` (cố định) / `caulong-dev` | `DEPLOY_PATH` (mặc định `/opt/caulong`) / `caulong` |
| Hàng đợi (`concurrency`) | `cd-dev` | `cd-production` |

1. Build & push image lên GHCR: `ghcr.io/<owner>/<repo>-api` và `-web`.
2. Deploy qua SSH (**tắt mặc định**, bật bằng `DEPLOY_ENABLED=true`): copy [deploy/docker-compose.prod.yml](deploy/docker-compose.prod.yml) lên server,
   `docker compose -p <project> pull && up -d`. Migration tự chạy khi container `api` khởi động.
3. Smoke test: gọi `<site>/robots.txt` tối đa 30 lần cách 5 giây; không lên thì CD đỏ.

Chạy tay (tab Actions → CD → Run workflow) có ô chọn môi trường `dev` / `production`; `production` chỉ chạy được khi chọn nhánh `main`.
Lưu ý: `workflow_run` luôn dùng file `cd.yml` ở default branch (`dev`).

### Bật deploy

1. Server (VPS) cài Docker; tạo thư mục, vd `/opt/caulong`, đặt file `.env` theo [deploy/.env.example](deploy/.env.example).
2. Đặt reverse proxy có HTTPS (Caddy/Nginx) trỏ domain → `127.0.0.1:3000`.
3. GitHub repo → Settings → Environments → tạo `production` (và `dev` nếu có server dev), mỗi Environment thêm:
   - **Secrets**: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` (private key), `DEPLOY_KNOWN_HOSTS` (`ssh-keyscan <host>`)
   - **Variables** (repo): `DEPLOY_ENABLED=true`, `SITE_URL=https://your-domain.vn`, `DEPLOY_PATH=/opt/caulong`;
     tùy chọn `DEV_SITE_URL` cho môi trường dev (thư mục dev luôn là `/opt/caulong-dev`, không đọc `DEPLOY_PATH`)
4. Lần deploy đầu, tạo tài khoản chủ sân: `docker compose exec api python -m app.scripts.seed`.

`SITE_URL` / `DEV_SITE_URL` được build vào image web (canonical, sitemap) – đổi domain thì chạy lại CD.
Server dev cần thư mục và `.env` riêng (`POSTGRES_PASSWORD`, `SECRET_KEY` khác production); đừng dùng chung với production.

## Quyết định thiết kế quan trọng

**Chống đặt trùng ở tầng DB.** `booking.allocation` có exclusion constraint
`EXCLUDE USING gist (tenant_id WITH =, resource_id WITH =, time_range WITH &&) WHERE (active)`;
mọi chỗ chiếm (giữ chỗ, booking, sự kiện) đều là một dòng `allocation`.
Hai request đồng thời đặt cùng giờ → chỉ một request thành công, request còn lại nhận 409 (`E-003`/`E-010`).
Range là `[start, end)` nên 18h–19h và 19h–20h không tính là trùng. Không kiểm trùng bằng code.

**Booking engine dùng lại được.** Đặt chỗ nằm ở module `booking_engine` (schema Postgres `booking`, có `tenant_id`),
không biết gì về cầu lông: sân, giờ mở, cao điểm, giá, giữ chỗ, sự kiện bán vé đều là cấu hình. Module khác chỉ gọi qua
`booking_engine.api` (có test kiểm ranh giới import); phần đặc thù dự án (khách là hội viên hay hồ sơ tạm) ở `front_desk`, `web_booking` và `members`.
Khi cần có thể tách thành service riêng. Chi tiết: [docs/booking-engine-api.md](docs/booking-engine-api.md).

**Thanh toán tách khỏi chỗ.** Booking có `payment_status`: Chưa thanh toán → Đã thanh toán hoặc Không thu được (hai trạng thái cuối,
không hủy/hoàn tiền). Tại quầy chơi trước, trả sau; hiện chỉ thu tiền mặt (chuyển khoản QR tại quầy là T-007).
Khách đặt online (T-008) trả trước: giữ chỗ 5 phút, booking chỉ được tạo khi SePay báo tiền về, xem mục "Đặt online và SePay".
Giá được server tính và chốt lúc đặt.

**Module giao tiếp qua service + event.** Module không query bảng của module khác; engine ghi sự kiện (vd. `booking.created`)
vào bảng outbox trong cùng transaction, worker phát cho `notifications`.
Khi cần tách service chỉ cần thay `app/core/events.py` bằng message broker.

**Bảo mật nền tảng (ADR-004).** Chống CSRF bằng kiểm `Origin`, rate limit bằng Redis, `Idempotency-Key` cho mọi lệnh ghi,
nhật ký thao tác chỉ thêm (không sửa), quyền khai báo tập trung ở `app/core/permissions.py`, SĐT luôn che ở API.

**Auth.** JWT trong cookie httpOnly (access 30 phút, refresh 14 ngày, path `/api/v1/auth`).
Trình duyệt gọi `/api/v1/*` cùng domain, Next rewrite sang FastAPI → không cần CORS.
Client tự gọi `/auth/refresh` khi gặp 401; trang đăng nhập tự khôi phục phiên nếu refresh còn hạn.

**SEO.** Trang public prerender tĩnh, dữ liệu qua `'use cache'` + `cacheLife` (tự làm mới).
Mỗi trang tự khai báo `alternates.canonical`; JSON-LD `SportsActivityLocation` (trang chủ),
`Article` (bài viết); `sitemap.xml`, `robots.txt` sinh động. Trang cá nhân/admin `noindex`
và đọc cookie bên trong `<Suspense>` (yêu cầu của Cache Components).

**Giờ giấc.** Mọi thời điểm lưu `timestamptz`; nghiệp vụ (giờ mở cửa, loại ngày, cao điểm)
tính theo `TIMEZONE=Asia/Ho_Chi_Minh`.

## Việc tiếp theo gợi ý

Thứ tự và phạm vi do ARCHITECT giữ trong `board/tasks/` (T-007 thu tiền chuyển khoản QR tại quầy, dùng lại module `payments` của T-008).

- Màn Hội viên đầy đủ, Báo cáo.
- Gọi `revalidateTag("posts")` (qua route handler có secret) khi admin đăng bài để sitemap/tin tức cập nhật ngay.
- Gửi thông báo email / Zalo ZNS từ `notifications/handlers.py` qua worker.
- Upload ảnh lên S3/R2, rate limit đăng nhập (Redis), Sentry.
