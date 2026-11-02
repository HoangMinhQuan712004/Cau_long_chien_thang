# Sân Cầu Lông – Quản lý & đặt sân

Modular monolith: **FastAPI** (backend) + **Next.js 16** (frontend), PostgreSQL, Redis.

```
project_caulong/
├── backend/                 FastAPI, chia module theo domain
│   ├── app/core/            config, db, security, event bus nội bộ
│   ├── app/modules/
│   │   ├── auth/            user, role (admin/staff/member; `member` trước là `customer`), JWT cookie cho khách; từ T-013: phiên Admin/nhân viên phía server, OTP, Google, quản lý nhân viên
│   │   ├── booking_engine/  sân, giờ, bảng giá, lịch, booking, sự kiện/vé, thu tiền (schema `booking`)
│   │   ├── front_desk/      đặt sân tại quầy: ghép hội viên + booking_engine
│   │   ├── members/         hội viên, hồ sơ tạm, danh mục vợt, thẻ hội viên `/me/member` (PR #21)
│   │   ├── member_area/     khu hội viên: Hồ sơ của tôi + ảnh đại diện (T-016)
│   │   ├── web_booking/     API public cho khách: lịch, lượt thanh toán (checkout), tra cứu (T-008)
│   │   ├── payments/        webhook SePay, bảng `payments.bank_transaction` (T-008; không có màn xử lý tay)
│   │   ├── notifications/   lắng nghe event (email/Zalo: TODO)
│   │   └── content/         bài viết phục vụ SEO
│   ├── app/workers/         ARQ: outbox, nhả giữ chỗ quá hạn, dọn nhật ký/idempotency
│   ├── alembic/             migration
│   └── tests/
├── frontend/                Next.js App Router (Cache Components)
│   └── src/
│       ├── app/(public)/    trang khách: /, /dat-san, /thanh-toan/[token], /tra-cuu, /bang-gia, /tin-tuc, tài khoản (T-013: /dang-nhap, /dang-ky, /quen-mat-khau → /quen-mat-khau/xac-minh → /quen-mat-khau/dat-lai, /tai-khoan)
│       ├── app/admin/       chủ sân / nhân viên (noindex): dat-san (lịch quầy), san, san/bang-gia, lich-su-giao-dich, hoi-vien, cai-dat/thanh-toan (chỉ Admin; T-013 thêm nhan-vien)
│       ├── app/sitemap.ts, robots.ts
│       ├── components/      booking-engine/ (màn quản trị), web-booking/ (đặt online, thanh toán, tra cứu), admin/, ui/
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

Tài khoản chủ sân trên `dev` hiện tại: `admin@example.com` / `admin12345` (đổi trong `backend/.env`).
**Từ T-013** Admin đăng nhập bằng **số điện thoại**: `FIRST_ADMIN_PHONE` (mặc định `0912345678`) và mật khẩu `FIRST_ADMIN_PASSWORD` (mẫu trong `backend/.env.example`: `Admin@12345`) trong `backend/.env`; seed chỉ tạo Admin khi DB chưa có Admin. Xem mục "Đăng nhập, nhân viên và OTP".

Chạy toàn bộ bằng Docker: `docker compose --profile app up --build`.

API nền tảng booking engine (Idempotency-Key, mã lỗi, bảng quyền, biến môi trường bảo mật): [docs/booking-engine-api.md](docs/booking-engine-api.md).

## Đặt online và SePay (T-008)

> Đã có trong `dev` (PR #16). Chưa lên production. Chi tiết API, mã lỗi, webhook: [docs/booking-engine-api.md](docs/booking-engine-api.md) mục 10.

Khách đặt sân trên web, chuyển khoản QR qua **SePay**; SePay báo tiền về bằng webhook, server tạo booking. Giữ chỗ **5 phút** (+ 60 giây ân hạn nhận tiền báo trễ).

### Cấu hình nhận tiền: chủ sân tự cài trên trang quản trị (T-012)

Admin vào **`/admin/cai-dat/thanh-toan`** (menu "Cài đặt thanh toán", chỉ Admin) để nhập ngân hàng, số tài khoản, tên chủ tài khoản, khóa webhook SePay và bật/tắt **Nhận đặt online**. Không cần sửa server.

- **Mỗi lần Lưu phải nhập lại mật khẩu Admin.** Sai 5 lần trong 15 phút thì bị khóa lưu 15 phút (429). Việc này chống kẻ chiếm phiên đổi số tài khoản nhận tiền.
- Đổi **ngân hàng hoặc số tài khoản** khi còn lượt đặt online đang chờ thanh toán sẽ bị chặn (`E-PAY-3`): tắt Nhận đặt online, đợi các lượt hết hạn (tối đa 6 phút) rồi đổi. Khách đã quét QR cũ vì thế không bị chuyển nhầm tài khoản.
- Khóa webhook được **mã hóa** trong DB và không bao giờ hiện lại (chỉ thấy 4 ký tự cuối). Quên khóa thì dán khóa mới.
- Mọi lần lưu ghi nhật ký `payments.settings.update` (số tài khoản chỉ ghi 4 số cuối, khóa chỉ ghi "đã đổi"). Trang hiện ai đổi lần cuối và lúc nào, và lần cuối nhận thông báo từ SePay.
- Tên chủ tài khoản tự viết hoa, bỏ dấu (`Nguyễn Văn Đạt` → `NGUYEN VAN DAT`).
- **Nguồn cấu hình:** chưa có cài đặt nào lưu trên trang → server dùng các biến `SEPAY_*` trong `.env` (dự phòng, như T-008). **Từ lần Lưu đầu tiên, DB là nguồn duy nhất** và `SEPAY_*` bị bỏ qua hoàn toàn, kể cả khóa webhook: phải nhập lại khóa trên trang rồi mới bật được.

Đặt online chỉ bật khi công tắc bật **và** đủ ngân hàng + số tài khoản + tên chủ + khóa. Thiếu thì khách vẫn xem lịch nhưng nút Tiếp tục khóa và hiện "gọi hotline", nên production chạy được trước khi có tài khoản SePay.

### Biến môi trường (`backend/.env`; trên server: `.env` của từng môi trường)

| Biến | Ví dụ / mặc định | Ghi chú |
|---|---|---|
| `PAYMENTS_ENCRYPTION_KEY` | – | **Secret, bắt buộc ở `staging` và `production`** (thiếu → API không khởi động). Khóa Fernet 44 ký tự dùng mã hóa khóa webhook trong DB. Sinh: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Ở `development` thiếu thì dùng khóa tạm và log cảnh báo (khóa webhook đã lưu sẽ không đọc lại được sau khi khởi động lại) |
| `SEPAY_BANK_CODE` | `Vietcombank` | **Dự phòng** khi chưa lưu trên trang. Mã ngân hàng dùng trong link QR `qr.sepay.vn` |
| `SEPAY_BANK_NAME` | `Vietcombank` | Dự phòng. Tên hiển thị cho khách |
| `SEPAY_ACCOUNT_NUMBER` | – | Dự phòng. Số tài khoản nhận tiền |
| `SEPAY_ACCOUNT_NAME` | – | Dự phòng. Tên chủ tài khoản hiển thị cho khách |
| `SEPAY_WEBHOOK_SECRET` | – | Dự phòng. **Secret.** Khóa ký webhook; không ghi vào repo |
| `SEPAY_TIMESTAMP_TOLERANCE_SECONDS` | `0` | `0` = không chặn theo tuổi timestamp (ADR-001) |
| `ONLINE_HOLD_MINUTES` | `5` | Thời gian giữ chỗ |
| `ONLINE_HOLD_GRACE_SECONDS` | `60` | Ân hạn nhận tiền báo trễ |
| `PAYMENTS_SIMULATE` | `false` | Chỉ máy dev / link dev (`ENV=staging`). `ENV=production` mà bật thì API không khởi động |

> **Cảnh báo: đổi hoặc làm mất `PAYMENTS_ENCRYPTION_KEY` thì khóa webhook đã lưu không đọc lại được** (webhook SePay nhận 503 và đặt online tự tắt vì thiếu khóa, cho tới khi Admin nhập lại khóa trên trang). Giữ khóa này cố định cho mỗi môi trường, sao lưu cùng `.env`, dev và production dùng hai khóa khác nhau. Khóa do RELEASE sinh và ghi thẳng vào `.env` trên server, không đi qua board hay tin nhắn.

`ENV` chỉ nhận `development`, `staging` (link dev), `production`; `staging` và `production` bắt buộc `SECRET_KEY` ≥ 32 ký tự và `PAYMENTS_ENCRYPTION_KEY` hợp lệ.

### Thử trên máy dev (không cần tài khoản SePay)

1. Trong `backend/.env` đặt giá trị **giả**, rồi chạy lại API (`npm run dev` hoặc `uvicorn`). Cách này chỉ dùng khi DB chưa có cài đặt lưu từ trang `/admin/cai-dat/thanh-toan` (nếu đã lưu, `SEPAY_*` bị bỏ qua; khi đó sửa ngay trên trang). Máy dev thiếu `PAYMENTS_ENCRYPTION_KEY` vẫn chạy được (khóa tạm), nhưng cần cài thư viện mới một lần: `cd backend; .venv\Scripts\pip install -e ".[dev]"`:

   ```
   SEPAY_BANK_CODE=Vietcombank
   SEPAY_BANK_NAME=Vietcombank
   SEPAY_ACCOUNT_NUMBER=0123456789
   SEPAY_ACCOUNT_NAME=SAN CAU LONG TEST
   SEPAY_WEBHOOK_SECRET=chuoi-bi-mat-chi-de-thu
   PAYMENTS_SIMULATE=true
   ```

2. Chạy migration một lần để có schema `payments`: `cd backend; .venv\Scripts\alembic upgrade head`.
3. Mở `http://localhost:3000/dat-san`, chọn ô, nhập họ tên + SĐT, bấm xác nhận (từ T-013: nhập tên + SĐT, bấm **Gửi mã**, nhập mã thử rồi bấm **Xác nhận** trước, xem mục "Đăng nhập, nhân viên và OTP"). Trang thanh toán hiện **Nội dung CK** dạng `BK20261020023` (chính là `pay_ref`, tức **mã đơn** bỏ dấu gạch từ T-019) và số tiền.
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

   **Từ T-013** thay dòng đăng nhập bằng `.../api/v1/auth/sign-in` với body `{"login":"0912345678","password":"<FIRST_ADMIN_PASSWORD trong backend/.env, mẫu Admin@12345>"}` (`/auth/login` bị gỡ). Phiên Admin là cookie `admin_session`; `-WebSession` vẫn giữ cookie như trên.

   Kết quả là `BankTransactionOut` (`outcome`, `refund_amount`, `booking_codes`). Lần sau nhớ đổi `Idempotency-Key`. Đổi `localhost:3000` nếu bạn chạy `WEB_PORT` khác (và thêm origin đó vào `ALLOWED_ORIGINS`).
5. Trang thanh toán tự chuyển sang "Đặt sân thành công". Thử `amount` nhỏ hơn → `partial` (vẫn chờ); lớn hơn → `applied` kèm `refund_amount`.
6. Tiền không khớp mã, trả thừa hoặc cần hoàn chỉ được ghi vào bảng `payments.bank_transaction` (không còn màn "Tiền về" trong quản trị); đối soát trên SePay hoặc ngân hàng.

Các trang khách của T-008: `/dat-san` (lưới chọn giờ, `?ngay=YYYY-MM-DD`), `/thanh-toan/{token}` (QR + đếm ngược, tự chuyển khi tiền về; `noindex`, `no-store`, chặn trong `robots.txt`, không vào sitemap), `/tra-cuu` (mã đặt + SĐT; từ T-019 nhận mã đơn hoặc mã con và hiện cả đơn). Header: Đặt sân · Tra cứu booking · Hotline (Đăng nhập/Đăng ký đang ẩn; T-013 hiện lại). Số hotline vẫn là số mẫu trong `frontend/src/lib/site.ts` cho tới khi chủ dự án cung cấp số thật.

### Hướng dẫn chủ sân cài SePay (một lần, trước khi bật production)

Làm trên **my.sepay.vn** và trang **`/admin/cai-dat/thanh-toan`**, không cần sửa server. Tên menu trên SePay có thể đổi theo thời điểm; tài liệu: https://developer.sepay.vn. Trang quản trị cũng có hướng dẫn rút gọn này.

1. Đăng ký tại my.sepay.vn, chọn gói, **liên kết tài khoản ngân hàng** nhận tiền của sân.
2. **Cấu trúc mã thanh toán** (Công ty → Cấu hình chung): tiền tố `BK`, hậu tố **11 ký tự số** (khớp `BK20261020023`). SePay tách mã này vào trường `code` của webhook; nếu không tách được, server tự tìm `BK` + 11 số trong nội dung chuyển khoản.
3. **Webhooks → + Thêm webhook**: sự kiện **Có tiền vào**; URL = ô "URL webhook" trên trang Cài đặt thanh toán (production: `https://chienthang.superbai.vip/api/v1/payments/sepay/webhook`; link dev: `https://chienthang-dev.superbai.vip/api/v1/payments/sepay/webhook`); tài khoản = tài khoản vừa liên kết; lọc tiền tố `BK`; bảo mật **HMAC-SHA256** → tạo khóa và **chép ngay** (SePay chỉ hiện một lần).
4. Ở trang Cài đặt thanh toán: chọn ngân hàng, nhập số tài khoản và tên chủ, dán khóa vào ô "Khóa bí mật webhook", bấm **Lưu** (nhập lại mật khẩu Admin). Có thể để công tắc **Nhận đặt online** tắt ở bước này. Quét thử ảnh QR mẫu bằng app ngân hàng: hiện đúng tên chủ tài khoản là được, không cần chuyển tiền.
5. Trên SePay bấm **Gửi thử** → trang Cài đặt phải hiện "Lần cuối nhận thông báo từ SePay" vừa xong (chỉ cập nhật sau khi đã Lưu ở bước 4). Rồi bật **Nhận đặt online**, Lưu. Thử một lượt đặt thật với sân giá nhỏ nhất.

Thử không tốn tiền: bật **Test Mode** trên SePay → menu Giao dịch → **+ Mô phỏng giao dịch**. Webhook của Test Mode cấu hình riêng, trỏ vào **link dev**.

Khóa webhook là secret: chỉ dán vào trang Cài đặt, không gửi qua board hay tin nhắn. Nghi lộ khóa → tạo khóa mới trên SePay rồi dán lại trên trang (khóa cũ ngừng được chấp nhận ngay khi Lưu).

Giao dịch không tự khớp (sai nội dung, tiền về sau khi hết hạn, trả thừa) không bị mất: webhook ghi vào `payments.bank_transaction` (cột `outcome`). Không có màn xử lý tay; chủ sân đối soát và hoàn tiền trên SePay hoặc ngân hàng.

## Đăng nhập, nhân viên và OTP (T-013)

> T-013 **đã có trong `dev`** (PR #18, #19), chưa vào `main`/production. Tên trang, nút, câu chữ và API đã đối chiếu với code trước khi gộp; chưa chạy thử lại trên link dev. Chi tiết API và mã lỗi: [docs/booking-engine-api.md](docs/booking-engine-api.md) mục 11.

Mục này dùng để biết ai đăng nhập bằng gì, cấu hình biến môi trường mới, cứu Admin khi quên mật khẩu, và thử OTP khi chưa có Zalo.

### Ai đăng nhập bằng gì

| Vai | Đăng nhập bằng | Trang |
|---|---|---|
| Admin (chủ sân) | Số điện thoại + mật khẩu | `/dang-nhap` → `/admin` |
| Nhân viên | Tên đăng nhập + mật khẩu. **Mỗi nhân viên một tài khoản** (mã `NV001`…), đăng nhập ở máy nào cũng được | `/dang-nhap` → `/admin` |
| Khách | SĐT hoặc tên đăng nhập + mật khẩu, hoặc Google. Tự đăng ký tại `/dang-ky` (từ T-021: phải xác minh SĐT bằng OTP và đăng ký xong là hội viên) | `/dang-nhap` → `/tai-khoan` (hội viên: `/hoi-vien`) |

- Chỉ có **một** trang `/dang-nhap` với một ô "Số điện thoại hoặc tên đăng nhập".
- Sai mật khẩu 5 lần liên tiếp → khóa 15 phút. Phiên Admin/nhân viên tồn tại tối đa 12 giờ, rồi phải đăng nhập lại.
- Nhân viên có quyền như "Tài khoản tại máy" trước đây (đặt sân tại quầy, thu tiền, xem lịch). Không tạo/xóa sự kiện, không xem Lịch sử giao dịch, không vào Nhân viên và Cài đặt thanh toán.
- Đặt tại quầy **không** cần OTP. OTP chỉ dùng khi khách **đặt online**, khi **quên mật khẩu**, khi **xác minh SĐT** trong `/tai-khoan` và (từ T-021) khi **đăng ký tài khoản**.

### Chủ sân quản lý nhân viên

Vào `/admin/nhan-vien` (menu "Nhân viên", chỉ Admin):

1. **Thêm nhân viên:** bấm **Thêm nhân viên**, nhập họ tên và mật khẩu (hoặc bấm **Tạo mật khẩu ngẫu nhiên**), rồi **Tạo tài khoản**. Hệ thống tự cấp mã (`NV007`) và tên đăng nhập (`an.nv007`) và hiện "Đã tạo nhân viên NV007 · Tên đăng nhập: …". **Mật khẩu không hiện lại sau khi rời trang**: bấm **Sao chép tên đăng nhập** hoặc **Sao chép cả mật khẩu** và gửi cho nhân viên ngay.
2. **Đặt lại mật khẩu** (nút trên dòng nhân viên) khi nhân viên quên: mọi phiên đang mở của người đó bị đăng xuất.
3. **Khóa** khi nhân viên nghỉ việc (bấm **Khóa**, rồi bấm lần nữa "Bấm lần nữa để khóa" để xác nhận): không đăng nhập được nữa, phiên đang mở bị đăng xuất ngay. **Mở khóa** lại được. Có thêm nút **Sửa tên**.
4. **Đăng xuất từ xa** một phiên lạ: bấm **Phiên đang mở (n)** trên dòng nhân viên để xem các phiên (giờ đăng nhập, hạn, thiết bị), rồi bấm **Đăng xuất** ở phiên cần thu hồi.

Mã nhân viên không dùng lại, kể cả khi đã khóa.

### Biến môi trường mới

Khai báo ở `backend/.env` (máy dev) và `.env` trên server. Danh sách đầy đủ kèm mặc định: [docs/booking-engine-api.md](docs/booking-engine-api.md) mục 6.

| Biến | Dùng cho | Ghi chú |
|---|---|---|
| `FIRST_ADMIN_PHONE` | SĐT Admin đầu tiên (thay `FIRST_ADMIN_EMAIL`) | Link dev: `0912345678`. **Production: SĐT thật, phải có trong `.env` trước khi deploy** (thiếu → migration dừng, API không lên) |
| `FIRST_ADMIN_PASSWORD` | Mật khẩu Admin đầu tiên (mẫu `Admin@12345`) | Chỉ dùng khi **chưa có Admin**; không bao giờ ghi đè mật khẩu đã có. Production từ chối mật khẩu mẫu hoặc yếu. **Secret** |
| `OTP_TEST_MODE` | Hiện mã OTP trên màn hình khi chưa có Zalo | Chỉ máy dev và link dev. `true` + `ENV=production` → API không khởi động |
| `ZALO_APP_ID`, `ZALO_SECRET_KEY`, `ZALO_REFRESH_TOKEN`, `ZALO_TEMPLATE_OTP` | Gửi OTP qua Zalo | **Chưa dùng được** (làm sau). Secret |
| `GOOGLE_CLIENT_ID` | Đăng nhập Google (backend) | Để trống thì nút Google hiện "đang được cấu hình" |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | Nút Google (frontend) | Client ID là thông tin công khai. Deploy lấy từ biến repo `GOOGLE_CLIENT_ID` (Settings → Secrets and variables → Variables), build vào image web |

Các hạn mức (số lần sai, thời gian khóa, hạn OTP…) có mặc định hợp lý; chỉ đổi khi cần, xem bảng ở tài liệu API.

### Thử OTP khi chưa có Zalo (`OTP_TEST_MODE`)

Đặt `OTP_TEST_MODE=true` trong `backend/.env` rồi chạy lại API.

- **Khách** (đặt online, xác minh SĐT, quên mật khẩu, và đăng ký từ T-021): sau khi bấm **Gửi mã**, màn hình hiện hộp vàng **"Mã thử (chỉ link dev): 123456"**. Nhập mã đó vào 6 ô rồi bấm **Xác nhận**.
- **Admin/nhân viên quên mật khẩu:** mã **không** hiện trên màn hình (người lạ vào link dev công khai không được chiếm Admin). Đọc mã trong log API:
  - Máy dev: terminal đang chạy `uvicorn` / `npm run dev`.
  - Link dev: `docker compose -p caulong-dev logs api --tail 50` trên VPS.
- `OTP_TEST_MODE=false` (mặc định): mã không bao giờ xuất hiện trong response hay log.

Thử đặt online trên máy dev (thay bước 3 của mục "Thử trên máy dev" phía trên): chọn ô, nhập họ tên + SĐT, bấm **Gửi mã**, nhập mã thử, rồi mới xác nhận đặt. Đã đăng nhập khách có SĐT xác minh thì bỏ qua bước OTP.

> Khi chưa có Zalo, **production không bật được đặt online** (thiếu kênh OTP) và quên mật khẩu hiện "Chức năng quên mật khẩu đang tạm ngưng. Vui lòng liên hệ chủ sân." Từ T-021, đăng ký tài khoản cũng hiện "Đăng ký tài khoản đang tạm ngưng. Vui lòng liên hệ quầy." Production chỉ đặt tại quầy cho tới khi Zalo xong.

### Cứu Admin khi quên mật khẩu

Khi chưa có Zalo, Admin không tự đặt lại được. Chạy trên VPS, trong thư mục compose của môi trường (`/opt/caulong-dev` hoặc `/opt/caulong`):

```bash
docker compose -p caulong-dev exec api python -m app.scripts.reset_admin_password   # link dev
docker compose -p caulong     exec api python -m app.scripts.reset_admin_password   # production
```

Lệnh hỏi mật khẩu mới hai lần (gõ không hiện trên màn hình; **không** truyền mật khẩu qua tham số dòng lệnh; mật khẩu phải đạt quy tắc: ≥ 8 ký tự, 1 chữ in hoa, 1 chữ số hoặc ký tự đặc biệt). Có một Admin thì dùng luôn, nhiều Admin thì hỏi SĐT. Xong: mọi phiên đăng nhập bị đăng xuất, tài khoản được mở khóa, thao tác ghi vào nhật ký. Lệnh không in mật khẩu. Chỉ người có quyền SSH vào VPS chạy được. Máy dev không dùng Docker: `cd backend; .venv\Scripts\python -m app.scripts.reset_admin_password`.

### Lên T-013: việc phải làm trước khi deploy

| Việc | Vì sao |
|---|---|
| Ghi `FIRST_ADMIN_PHONE` vào `.env` của server **trước** deploy | Admin cũ đăng nhập bằng email, chưa có SĐT. Migration gán SĐT này cho Admin cũ; thiếu hoặc sai thì dừng, API không lên. Mật khẩu cũ giữ nguyên |
| Production: **không** bật `OTP_TEST_MODE` | Bật cùng `ENV=production` thì API không khởi động |
| Link dev: `OTP_TEST_MODE=true`, `GOOGLE_CLIENT_ID` | Để thử OTP và Google |
| Đặt biến repo `GOOGLE_CLIENT_ID` | `cd.yml` build vào image web |
| Sau deploy dev: kiểm `0912345678` + mật khẩu cũ và `nv001` + mật khẩu cũ của "Tài khoản tại máy" | "Tài khoản tại máy" hiện tại được đổi thành nhân viên `NV001` / `nv001` |

Sau khi lên T-013, route cũ `/auth/login` và `/admin/users` bị gỡ (trả 404); `UserOut` không còn `email`.

## Mã đặt sân: một lượt đặt một mã (T-019)

> Đã có trong `dev` (PR #23, `993b27c`); đối chiếu với code backend `be/T-019-ma-chung` @ `f0a1471`. Tên nút chưa kiểm trên giao diện. Thay đổi này **đổi contract API**: backend và frontend lên cùng đợt.

- Mỗi lần khách đặt online, hoặc nhân viên bấm **Đặt sân** ở quầy, tạo **một đơn** có mã `BK-YYYYMMDD-NNN`. Dãy số NNN chung với mã sự kiện, không dùng lại.
- Mỗi **khối** (một sân × khoảng giờ liền nhau) trong đơn có mã con `{mã đơn}-01`, `-02`… Ví dụ khách đặt Sân 2 và Sân 3, mỗi sân hai khoảng giờ: **một** mã đơn, bốn khối `-01` đến `-04`.
- **Khách chỉ thấy mã đơn.** Nội dung chuyển khoản vẫn là `BK` + 11 số (mã đơn bỏ dấu gạch) nên cấu hình SePay không đổi.
- **Quầy:** lịch hiện mã đơn trên khối, chi tiết khối hiện thêm mã con. Thu tiền và "Không thu được" vẫn theo từng khối. Đơn còn từ 2 khối chưa thanh toán thì có thể **thu cả đơn** bằng tiền mặt. Ô tìm mã và `/tra-cuu` nhận cả mã đơn lẫn mã con.
- Một lần đặt ở quầy chọn được nhiều khối trong ngày hôm nay (nhiều sân, nhiều khoảng giờ); chỉ cần một khối trùng lịch là **không khối nào được tạo**.
- **Dữ liệu trên dev:** mỗi booking cũ thành một đơn, mã đơn giữ mã cũ, booking nhận `-01`. Lượt thanh toán đang chờ tại lúc migrate bị cho hết hạn. Hạ cấp (downgrade) chỉ chạy được khi chưa có đơn nào từ 2 khối trở lên.
- **Migration:** `5b98d354dd77`, nối sau `dad220bfc992` (T-016); chuỗi `a3d81f5c2b6e` → `dad220bfc992` → `5b98d354dd77` chỉ có một head.

API: [docs/booking-engine-api.md](docs/booking-engine-api.md) mục 5.1.

## Hội viên và khu hội viên (T-015, T-016, T-020)

> Tất cả phần dưới đã có trong `dev` (PR #21 `c288d08`, rồi PR #23 `993b27c` gồm khu hội viên T-016 và chỉnh T-020), đối chiếu với code. Tên trang và nút của khu hội viên chưa kiểm trên giao diện. Chưa có gì trong `main`/production.

### Màn Hội viên (quản trị)

Vào `/admin/hoi-vien` (menu "Hội viên", Admin và nhân viên) để tra, thêm, sửa hội viên và tạo hồ sơ tạm.

| Việc | Admin | Nhân viên |
|---|:-:|:-:|
| Xem danh sách, **Xem chi tiết** | ✔ | ✔ |
| **Thêm hội viên**, **Tạo hồ sơ tạm**, **Sửa** họ tên / giới tính / Hạng / vợt | ✔ | ✔ |
| Đổi **Trạng thái** Hoạt động / Ngừng | ✔ | ✘ (ô bị khóa, ghi "Chỉ Admin được đổi trạng thái.") |
| **Danh mục vợt** (thêm, sửa tên, ẩn / hiện, xóa) | ✔ | ✘ |

- **Hội viên** có Mã HV (`HV0031`, tự cấp khi lưu, không dùng lại), Hạng và Trạng thái. **Hồ sơ tạm** chỉ có họ tên, giới tính, SĐT; sửa được họ tên và giới tính.
- **Hạng** là trình độ chơi, 8 bậc: Yếu · Trung bình yếu · Trung bình - · Trung bình · Trung bình + · Khá · Bán chuyên · Chuyên nghiệp. Có thể để **Chưa xếp hạng**.
- **Không đổi được SĐT** của hồ sơ. Nhập sai SĐT thì phải tạo hồ sơ mới.
- **SĐT đang là hồ sơ tạm** mà bấm Thêm hội viên: màn báo "Số điện thoại đã có hồ sơ tạm: {Họ tên} (tạo dd/mm/yyyy)" dưới ô SĐT và **không** thêm hội viên (người dùng chốt 31/10; bản đầu có nút "Nâng thành hội viên", T-020 đã gỡ). Hồ sơ tạm chỉ thành hội viên khi chính chủ SĐT xác minh OTP (T-021, bên dưới).
- **Ngừng:** hội viên Ngừng **vẫn đặt được** sân tại quầy (popup Chọn hội viên hiện nhãn "Ngừng"), nhưng **tài khoản web bị khóa**: không đăng nhập, không vào khu hội viên. Bấm lại Hoạt động thì mở.
- **Tìm** theo Mã HV / tên / SĐT. Lọc theo Loại (Tất cả / Hội viên / Hồ sơ tạm), Trạng thái, Hạng, Vợt. Cột **Số lần đặt** sắp xếp được; mặc định hồ sơ mới nhất trước. Có chọn số dòng mỗi trang.
- **Số lần đặt** là số booking (quầy và online) của hồ sơ; **chưa tính vé sự kiện**.
- **Xem chi tiết** mở ngăn bên phải: giới tính, SĐT đầy đủ, vợt, ngày tạo, số lần đặt, tổng giờ, 5 lần đặt gần nhất. Mỗi lần xem được ghi vào nhật ký.
- Màn hiện SĐT **đầy đủ** (không che) cho cả Admin lẫn nhân viên.
- **Hai máy cùng sửa một hội viên:** máy lưu sau nhận "Hội viên này vừa được cập nhật ở máy khác. Tải lại để xem bản mới nhất." kèm nút **Tải lại**, không ghi đè. Hội viên tự sửa ở khu hội viên cũng tính (dùng chung số phiên bản).
- Bấm **Lưu** hai lần liên tiếp (hoặc tự thử lại khi mạng chậm) không tạo hội viên thứ hai: giao diện gửi `Idempotency-Key` cho mỗi lần Thêm hội viên / Tạo hồ sơ tạm.

### Tài khoản hội viên do sân tạo

Quầy thêm hội viên thì hệ thống tạo luôn tài khoản web cho SĐT đó, nếu chưa có:

1. Hội viên đăng nhập ở `/dang-nhap` bằng **SĐT** và mật khẩu ban đầu **là chính SĐT**.
2. Hệ thống đưa sang `/doi-mat-khau`, bắt đặt mật khẩu mới (không được trùng SĐT) trước khi dùng tiếp.
3. **Trong 3 ngày** (`MEMBER_INITIAL_PASSWORD_DAYS`) phải đổi. Quá hạn thì không đăng nhập được bằng mật khẩu ban đầu nữa; hội viên bấm **Quên mật khẩu** và nhập mã OTP.
4. SĐT đã có tài khoản (khách tự đăng ký, Admin, nhân viên) thì **không đụng**, mật khẩu giữ nguyên.

Khách tự đăng ký ở `/dang-ky` là đường khác: xem "Đăng ký tài khoản = hội viên (T-021)" bên dưới.

**Dữ liệu có sẵn trước PR #21:** hội viên cũ chưa có tài khoản. Chạy một lần, chạy lại không sinh trùng:

```powershell
# máy dev (thư mục backend)
.venv\Scripts\python -m app.scripts.backfill_member_accounts

# server
docker compose -p caulong-dev exec api python -m app.scripts.backfill_member_accounts   # production: -p caulong
```

> Không có bước nào chạy script này tự động khi deploy. RELEASE quyết định chạy khi lên dev / production.

### Khu hội viên trên web (T-016)

Khu `/hoi-vien` dành cho khách đã đăng nhập **và là hội viên**. Đợt 1 chỉ có "Hồ sơ của tôi"; các mục còn lại (Tổng quan, Đặt sân, Video & kỷ lục, Danh sách sân, Lịch sử thanh toán) mở trang "Sắp ra mắt".

- **Ai vào được:** tài khoản khách có SĐT trùng SĐT của một **hội viên** (hồ sơ tạm không tính), và SĐT đó là tài khoản do sân tạo **hoặc** đã xác minh bằng OTP. Hệ thống không lưu liên kết riêng mà so SĐT; vì SĐT hồ sơ không đổi được nên liên kết ổn định.
- Khách đăng ký không OTP (tài khoản đời cũ) bằng SĐT của hội viên mà chưa xác minh OTP → chưa vào được (báo "Bạn chưa là hội viên."). Xác minh SĐT trong `/tai-khoan` rồi vào lại. Từ T-021, ai xác minh SĐT cũng tự là hội viên (bên dưới).
- Khách thường (không phải hội viên) giữ `/tai-khoan`. Admin / nhân viên không vào khu này.
- **Hồ sơ của tôi:** hội viên tự sửa Họ tên, Biệt danh (≤ 20 ký tự), Email (không bắt buộc, không trùng người khác, chỉ để liên hệ), Trình độ (= Hạng), Vợt, công tắc "Hiện trên Video & kỷ lục" (mặc định Tắt), và đổi / xóa **ảnh đại diện** (JPG, PNG, WebP, tối đa 5 MB, cắt vuông).
- SĐT hiển thị đầy đủ và **khóa**: muốn đổi SĐT, liên hệ quầy. (Hiện quầy cũng chưa đổi được SĐT hồ sơ.)
- Hai nơi sửa cùng lúc (hai tab, hoặc hội viên và quầy): nơi lưu sau nhận lỗi "vừa được cập nhật ở nơi khác" và không ghi đè. Quầy và hội viên dùng chung số phiên bản (từ T-020).
- Đổi Họ tên thì tên khách trên booking, vé và lượt thanh toán của hồ sơ đổi theo.

Biến mới: `AVATAR_MAX_BYTES` (mặc định 5242880 = 5 MB, đã có trong `backend/.env.example`). T-016 thêm gói `pillow` và `python-multipart`: **phải build lại image backend**. Ảnh lưu trong Postgres (khoảng vài chục KB mỗi hội viên), nên sao lưu DB lớn hơn một chút. Reverse proxy phía trước (Caddy, Next rewrite) phải cho thân request tới khoảng 5,06 MB trên đường tải ảnh.

### Đăng ký tài khoản = hội viên (T-021)

> Đã vào `dev` (PR #24). Đối chiếu với code backend `dev`. Giao diện `/dang-ky` mới chưa bàn giao nên chưa kiểm tên nút.

**Quy tắc:** tài khoản web có SĐT **đã xác minh bằng OTP** là hội viên. Quầy vẫn tạo hội viên (kèm tài khoản) như trên; hai đường cùng tồn tại.

| Khách làm gì | Kết quả |
|---|---|
| Đăng ký ở `/dang-ky` | Hai bước: nhập họ tên, SĐT, mật khẩu → nhận mã OTP → nhập mã. Mã đúng thì tạo tài khoản **và** hồ sơ hội viên cùng lúc, đăng nhập luôn, vào `/hoi-vien` |
| SĐT đã có hồ sơ tạm (khách từng đặt ở quầy) | Hồ sơ tạm được **nâng lên hội viên**, giữ lịch sử đặt sân và Họ tên cũ |
| Đã là hội viên của quầy tạo (có tài khoản) | Không tạo thêm, chỉ liên kết. Phải dùng Đăng nhập / Quên mật khẩu |
| Xác minh SĐT ở `/tai-khoan`, hoặc nhập OTP khi đặt online lúc đã đăng nhập, hoặc Quên mật khẩu | Cùng quy tắc: xác minh xong là hội viên |
| Hội viên đang **Ngừng** | Tài khoản bị khóa, báo "Tài khoản hội viên đang tạm ngừng. Vui lòng liên hệ quầy." |

- Hội viên tự đăng ký có Mã HV, **chưa xếp hạng**, Hoạt động. Màn Hội viên (quản trị) ghi nguồn **"Tự đăng ký online"**.
- Quầy thêm hội viên mà SĐT đang là hồ sơ tạm vẫn báo trùng (như trên); chỉ chính chủ SĐT xác minh OTP mới nâng được hồ sơ tạm.
- Tài khoản đời cũ tự đăng ký không OTP: người xác minh OTP số đó **thắng**; tài khoản cũ bị gỡ SĐT (và vô hiệu nếu không còn cách đăng nhập khác).
- `POST /auth/register` cũ (không OTP) trả 410: đã đóng.
- Khi deploy, migration `9738bbfe2eb7` **tự chạy backfill**: mọi tài khoản khách đang hoạt động đã xác minh SĐT mà chưa là hội viên sẽ thành hội viên. Đây khác với script `backfill_member_accounts` ở trên. Sau khi deploy, kiểm ở màn Hội viên: hội viên mới do backfill mang nguồn "Tự đăng ký online" (hiện là nhãn, chưa có bộ lọc theo nguồn).
- **Production chưa có Zalo:** `OTP_TEST_MODE` tắt, nên `/dang-ky` hiện "Đăng ký tài khoản đang tạm ngưng. Vui lòng liên hệ quầy." cho tới khi có kênh OTP. Link dev dùng `OTP_TEST_MODE=true`: mã hiện trên màn hình.
- Không có biến môi trường hay gói mới.

API, mã lỗi `E-MEM-*`, `E-HV-*`, `E-AUTH-25…32`: [docs/booking-engine-api.md](docs/booking-engine-api.md) mục 12 và 11.2.

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
**Từ T-013 (ADR-008):** JWT chỉ còn cho **khách** (thêm `token_version`: đổi mật khẩu thì JWT cũ hết hiệu lực). Admin và nhân viên dùng **phiên phía server** (cookie `admin_session`, 12 giờ cứng, thu hồi được, đăng xuất từ xa). OTP chỉ bắt buộc ở đặt online; đặt tại quầy không cần.

**SEO.** Trang public prerender tĩnh, dữ liệu qua `'use cache'` + `cacheLife` (tự làm mới).
Mỗi trang tự khai báo `alternates.canonical`; JSON-LD `SportsActivityLocation` (trang chủ),
`Article` (bài viết); `sitemap.xml`, `robots.txt` sinh động. Trang cá nhân/admin `noindex`
và đọc cookie bên trong `<Suspense>` (yêu cầu của Cache Components).

**Giờ giấc.** Mọi thời điểm lưu `timestamptz`; nghiệp vụ (giờ mở cửa, loại ngày, cao điểm)
tính theo `TIMEZONE=Asia/Ho_Chi_Minh`.

## Việc tiếp theo gợi ý

Thứ tự và phạm vi do ARCHITECT giữ trong `board/tasks/` (T-007 thu tiền chuyển khoản QR tại quầy, dùng lại module `payments` của T-008).

- Báo cáo; các màn khu hội viên còn lại (Tổng quan, Đặt sân, Video & kỷ lục, Lịch sử thanh toán).
- Gọi `revalidateTag("posts")` (qua route handler có secret) khi admin đăng bài để sitemap/tin tức cập nhật ngay.
- Gửi thông báo email / Zalo ZNS từ `notifications/handlers.py` qua worker.
- Upload ảnh lên S3/R2, Sentry. Gửi OTP qua Zalo ZNS (T-013 để lại `TODO`).
