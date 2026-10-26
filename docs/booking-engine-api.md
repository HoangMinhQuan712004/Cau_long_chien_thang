# API booking engine và nền bảo mật (T-005)

Tài liệu này dành cho người viết code gọi `/api/v1/booking/**`: cần gửi gì, nhận lỗi gì, ai được gọi gì.
Nguồn: nhánh `be/T-005-nen-tang` (ADR-004, ADR-003). Nếu code và tài liệu lệch nhau, code đúng – báo DOCS-STEWARD sửa.

> Phạm vi hiện tại: **cấu hình sân và bảng giá** (sân, giờ mở cửa, cao điểm, giá, ngày Lễ/Tết, báo giá).
> Lịch, đặt sân, sự kiện, thu tiền thuộc T-006 trở đi. Luồng đặt sân cũ (`/api/v1/bookings`) vẫn chạy song song cho tới khi T-006 phát hành.

## 1. Quy tắc chung cho mọi request ghi

| Quy tắc | Chi tiết |
|---|---|
| Xác thực | Cookie phiên như các API cũ (đăng nhập qua `POST /api/v1/auth/login`) |
| `Origin` | Request `POST/PUT/PATCH/DELETE` mang cookie phải có `Origin` (hoặc `Referer`) thuộc `ALLOWED_ORIGINS`, nếu không → 403 `E-SEC-1`. Thiếu cả hai cũng bị chặn. Trình duyệt tự gửi; code phía server Next gọi API phải tự thêm header `Origin` |
| Body | JSON, tối đa 64 KB (`MAX_BODY_BYTES`) → quá thì 413 `E-SEC-6`. Trường lạ bị từ chối (422): server tự tính giá, tiền, mã, người thao tác nên đừng gửi |
| `Idempotency-Key` | Bắt buộc cho mọi `POST/PUT/PATCH/DELETE` dưới `/booking/**`, **trừ `POST /quote`** |
| Rate limit | Toàn API `RATE_LIMIT_PER_MINUTE` (mặc định 120) lượt/phút/IP; `POST /quote` 60 lượt/phút/người. Vượt → 429 `E-SEC-5` + header `Retry-After` (giây) |
| Nhật ký | Mọi lệnh ghi được ghi vào `audit_log` (chỉ thêm, không sửa; xóa chỉ dòng quá 12 tháng) |

### Idempotency-Key

Chống bấm hai lần hoặc gửi lại khi mạng chập chờn.

- Giá trị: UUID v4, sinh **mỗi lần người dùng bấm nút**; **giữ nguyên khi tự thử lại** cùng thao tác đó. Thiếu hoặc sai dạng → 400 `E-SEC-2`.
- Gửi lại cùng key và cùng nội dung → nhận đúng kết quả cũ (cùng mã HTTP), kèm header `Idempotent-Replayed: true`.
- Cùng key nhưng nội dung khác → 422 `E-SEC-4`.
- Cùng key đang được xử lý ở request khác → 409 `E-SEC-3`; thử lại sau giây lát sẽ nhận kết quả cũ.
- Request **lỗi** (4xx nghiệp vụ) không được lưu: gửi lại cùng key sẽ chạy lại từ đầu.
- Key được giữ 24 giờ, tính riêng cho từng người thao tác.

## 2. Định dạng lỗi

Lỗi nghiệp vụ trả `{"detail": {"code": "E-CFG-7", "message": "…"}}`. Giao diện phải map theo `code`, không dựa vào câu chữ.
Một số lỗi có thêm trường phụ trong `detail` (xem bảng). Lỗi sai định dạng (giờ không phải `HH:00`/`HH:30`, trường lạ…)
vẫn là 422 mặc định của FastAPI, khi đó `detail` là **mảng**. Route cũ ngoài `/booking/**` vẫn trả `detail` là chuỗi.

| Code | HTTP | Khi nào |
|---|---|---|
| E-AUTH-1 | 401 | Chưa đăng nhập (route `/booking/**`) |
| E-AUTH-2 | 403 | Đăng nhập rồi nhưng thiếu quyền |
| E-SEC-1 | 403 | `Origin`/`Referer` không thuộc `ALLOWED_ORIGINS` |
| E-SEC-2 | 400 | Thiếu hoặc sai dạng `Idempotency-Key` |
| E-SEC-3 | 409 | Key đang được xử lý ở request khác |
| E-SEC-4 | 422 | Key đã dùng với nội dung khác |
| E-SEC-5 | 429 | Vượt rate limit (có `Retry-After`) |
| E-SEC-6 | 413 | Body lớn hơn 64 KB |
| E-CFG-1 | 422 / 409 | Tên sân trống hoặc quá 50 ký tự (422); trùng tên, không phân biệt hoa thường (409) |
| E-CFG-2 | 422 | Giờ đóng cửa chưa cách giờ mở ít nhất 60 phút |
| E-CFG-3 | 409 | Đổi giờ mà còn chỗ đã đặt từ ngày mai nằm ngoài giờ mới. Thêm `items:[{code,date,start_time,end_time}]` (tối đa 6) và `more` (số khung còn lại) |
| E-CFG-4 | 409 | Ngừng sân mà còn chỗ đã đặt từ hôm nay. Có `items` và `more` như trên |
| E-CFG-5 | 422 | Khung cao điểm ngắn hơn 30 phút, ngoài giờ mở cửa hoặc chồng nhau |
| E-CFG-6 | 422 | Bảng giá: ô ≤ 0, thiếu ô hoặc trùng ô |
| E-CFG-7 | 409 | `version` cũ (sân hoặc bảng giá đã bị máy khác sửa) – tải lại rồi sửa tiếp |
| E-CFG-8 | 409 | Khoảng Lễ/Tết trùng ngày đã có: "Ngày dd/mm đã nằm trong {tên}." |
| E-CFG-9 | 422 | `resource_type_code` không tồn tại |
| E-CFG-10 | 422 | Báo giá: khung ngoài giờ mở, sân đang ngừng, hoặc giờ kết thúc ≤ giờ bắt đầu |
| E-019 | 422 | Báo giá: thiếu giá cho khung |
| E-NOT-FOUND | 404 | Mã sân hoặc id Lễ/Tết không có |

## 3. Quyền

Quyền khai báo tập trung ở `backend/app/core/permissions.py`. Router dùng `Depends(require(Perm.X))`,
**không so vai trực tiếp**. Vai hiện có: `admin` = Admin (chủ sân), `staff` = Tài khoản tại máy, `customer` = khách.

| Quyền | admin | staff | customer | Dùng cho |
|---|:-:|:-:|:-:|---|
| `booking.resources.view` | ✔ | ✔ | | Danh mục sân |
| `booking.config.manage` | ✔ | | | Sửa sân, giờ, bảng giá, Lễ/Tết; xem bảng giá và Lễ/Tết |
| `booking.quote` | ✔ | ✔ | | Báo giá khung |
| `booking.calendar.view`, `booking.search`, `booking.counter.create`, `booking.session.view`, `booking.collect`, `booking.uncollectible`, `member.search` | ✔ | ✔ | | Khai báo sẵn cho T-006 trở đi (chưa có route) |
| `booking.session.manage`, `booking.transactions.view` | ✔ | | | Khai báo sẵn cho T-006 trở đi (chưa có route) |

Chưa đăng nhập → 401 `E-AUTH-1`; thiếu quyền → 403 `E-AUTH-2`. Thêm route mới phải khai báo quyền; `tests/test_permissions.py` quét mọi route quản trị.

## 4. Endpoint hiện có – tiền tố `/api/v1/booking`

| Method | Path | Quyền | Ghi chú |
|---|---|---|---|
| GET | `/resources` | `booking.resources.view` | Danh sách sân, loại sân, lịch hiện hành (`schedule`) và lịch chờ áp dụng (`pending_schedule`) |
| POST | `/resources` | `booking.config.manage` | Thêm sân → 201. Body `{name, resource_type_code, open_time, close_time, peak_bands}`. Mã `S07…` hệ thống cấp; giờ áp dụng **ngay hôm nay** |
| PATCH | `/resources/{code}` | `booking.config.manage` | Body có `version`, chỉ gửi trường muốn đổi (`name`, `resource_type_code`, `is_active`, `open_time`, `close_time`, `peak_bands`). Đổi giờ/cao điểm có hiệu lực từ **ngày mai** (hiện ở `pending_schedule`) |
| GET | `/prices` | `booking.config.manage` | Cả bảng giá + `version` |
| PUT | `/prices` | `booking.config.manage` | Body `{version, prices}`, phải gửi **đủ 12 ô** (2 loại sân × 3 loại ngày × 2 band) |
| GET | `/special-days?year=2026` | `booking.config.manage` | Danh sách ngày Lễ/Tết |
| POST | `/special-days` | `booking.config.manage` | Body `{date_from, date_to?, name}` → 201; bỏ `date_to` = một ngày |
| DELETE | `/special-days/{id}` | `booking.config.manage` | → 204 |
| POST | `/quote` | `booking.quote` | Body `{resource_code, date, start_hour, end_hour}` → giá từng khung + `total_amount`. Không cần `Idempotency-Key` |

Quy ước dữ liệu:

- Giờ dạng `"HH:MM"` (phút là `00` hoặc `30`); đóng cửa được phép `"24:00"`.
- `peak_bands`: danh sách cặp giờ, ví dụ `[["05:00","07:00"],["17:00","21:00"]]`.
- `day_type`: `weekday` | `weekend` | `holiday` (ngày thuộc danh mục Lễ/Tết → `holiday`; thứ Bảy, Chủ nhật → `weekend`).
- `band` của bảng giá: `offpeak` | `peak`. Trong báo giá, mỗi khung 1 giờ có thể là `offpeak` | `partial` (một nửa cao điểm) | `peak`.
- Tiền là số nguyên VND. Khung nửa cao điểm có tổng lẻ thì làm tròn lên.
- Giá mới chỉ áp cho khung **chưa đặt**; booking chốt giá lúc đặt.
- Phiên bản (`version`) chống ghi đè: gửi lại đúng `version` đã đọc; lệch → 409 `E-CFG-7`.

Thay đổi ở route cũ (để tránh lộ SĐT): `GET /api/v1/admin/users` trả `phone_masked` (ví dụ `0911 xxx 333`) **thay cho** `phone`;
`GET /api/v1/admin/bookings` che `customer_phone` (giữ tên trường).

## 5. Biến môi trường mới

Khai báo trong `backend/app/core/config.py`, mẫu ở `backend/.env.example`.

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ALLOWED_ORIGINS` | `["http://localhost:3000"]` | Origin được gửi request ghi kèm cookie (chống CSRF). Production: `["https://chienthang.superbai.vip"]`; dev: `["https://chienthang-dev.superbai.vip"]`. Worktree FRONTEND chạy cổng 3102 phải thêm `http://localhost:3102` |
| `TRUSTED_PROXY_COUNT` | `0` | Số proxy tin cậy đứng trước API để lấy IP thật từ `X-Forwarded-For` (Caddy → Next → API là 2). `0` = dùng IP kết nối trực tiếp, khi đó mọi người sau cùng một proxy dùng chung một bộ đếm → dễ dính 429 |
| `RATE_LIMIT_ENABLED` | `true` | Bật/tắt rate limit |
| `RATE_LIMIT_PER_MINUTE` | `120` | Giới hạn mặc định theo IP |
| `MAX_BODY_BYTES` | `65536` | Kích thước body tối đa |
| `TENANT_ID` | `1` | Tenant của bản chạy này (mỗi dự án một bản chạy) |

Rate limit dùng Redis. Redis lỗi thì cho qua và ghi log (không chặn người dùng).

## 6. Chạy thử cục bộ

```powershell
cd backend
.venv\Scripts\alembic upgrade head        # tạo schema booking, audit_log, idempotency_keys
.venv\Scripts\python -m app.scripts.seed  # ENV khác production: S01–S06, bảng giá, Lễ/Tết 2026
.venv\Scripts\uvicorn app.main:app --reload --port 8000
```

Tài liệu OpenAPI sống: `http://localhost:8000/docs` (tắt ở production). Migration quay lui được:
`alembic downgrade base` xóa schema `booking` và hai bảng nền, không đụng bảng cũ.
