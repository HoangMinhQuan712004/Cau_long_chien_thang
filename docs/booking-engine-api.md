# API booking engine, đặt online, đăng nhập, hội viên (T-005, T-006, T-008, T-012, T-013, T-015, T-016)

Tài liệu này dành cho người viết code gọi API đặt sân: cần gửi gì, nhận lỗi gì, ai được gọi gì.
Nguồn: code `dev` (T-005, T-006, T-008, T-012, T-013, và quản trị hội viên của PR #21 `c288d08`); mục 12.6 (khu hội viên, T-016) đối chiếu với `be/T-016-khu-hoi-vien` @ `fd8db2f` (**chưa vào `dev`**); spec `board/tasks/`; ADR-001, ADR-003, ADR-004, ADR-007, ADR-008, ADR-009.
Nếu code và tài liệu lệch nhau, code đúng – báo DOCS-STEWARD sửa. OpenAPI sống: `/docs` của API (tắt ở link dev và production).

> Phạm vi: cấu hình sân và bảng giá (T-005); lịch, đặt sân tại quầy, sự kiện và vé, thu tiền mặt, Không thu được, Lịch sử giao dịch (T-006);
> **khách đặt online, thanh toán QR SePay, tra cứu booking, Tiền về cần xử lý (T-008), Admin tự cài tài khoản nhận tiền và khóa SePay (T-012) – mục 10**.
> **Đăng nhập, nhiều tài khoản nhân viên, OTP, tài khoản khách (T-013) – mục 11; xác minh SĐT bằng OTP khi đặt online – mục 10.2.**
> **Màn Hội viên quản trị, tài khoản hội viên, danh mục vợt (PR #21) và khu hội viên trên web (T-016) – mục 12.**
> **Chưa có:** thu tiền chuyển khoản QR tại quầy (T-007), bán vé sự kiện online, báo cáo, các màn khu hội viên ngoài "Hồ sơ của tôi".
> **Luồng đặt sân cũ đã bị gỡ** trong T-006, xem mục 8.
> Mục 10 (T-008, T-012), mục 11 (T-013) và mục 12.1–12.5 (PR #21) đã có trong `dev`; mục 12.6 (T-016) chưa. Chưa có trong `main`/production.

## 1. Quy tắc chung cho mọi request ghi

| Quy tắc | Chi tiết |
|---|---|
| Xác thực | Cookie. Hiện trên `dev`: đăng nhập qua `POST /api/v1/auth/login`. **(T-013)** `/auth/login` bị gỡ: Admin/nhân viên dùng cookie `admin_session` (phiên phía server, 12 giờ), khách dùng JWT; cả hai đăng nhập qua `POST /api/v1/auth/sign-in` – mục 11 |
| `Origin` | Request `POST/PUT/PATCH/DELETE` mang cookie phải có `Origin` (hoặc `Referer`) thuộc `ALLOWED_ORIGINS`, nếu không → 403 `E-SEC-1`. Thiếu cả hai cũng bị chặn. Trình duyệt tự gửi; code phía server Next gọi API phải tự thêm header `Origin` |
| Body | JSON, tối đa 64 KB (`MAX_BODY_BYTES`) → quá thì 413 `E-SEC-6`. Trường lạ bị từ chối (422): server tự tính giá, tiền, mã, trạng thái thanh toán, tên khách, người thao tác, nên **đừng gửi** `amount`, `price`, `code`, `payment_status`, `customer_name`, `created_by` |
| `Idempotency-Key` | Bắt buộc cho mọi `POST/PUT/PATCH/DELETE` của booking engine và `/front-desk/**`, **trừ `POST /booking/quote`** |
| Rate limit | Toàn API `RATE_LIMIT_PER_MINUTE` (mặc định 120) lượt/phút/IP. Riêng 60 lượt/phút/người cho `POST /booking/quote`, `GET /booking/search`, `GET /members/search`. Vượt → 429 `E-SEC-5` + header `Retry-After` (giây) |
| Nhật ký | Mọi lệnh ghi thành công ghi đúng 1 dòng `audit_log` (chỉ thêm, không sửa; xóa chỉ dòng quá 12 tháng). Ngoại lệ: đặt quầy kèm hồ sơ tạm **mới** ghi 2 dòng (`member.temp.create` và `booking.counter.create`). Thao tác bị chặn không ghi |
| Dữ liệu cá nhân | Không response nào trả `id` nội bộ hay `customer_ref`. API quản trị/nhân viên (lịch, chi tiết đơn, vé, giao dịch, hội viên) trả SĐT **đầy đủ** (`phone`) cho cả Admin lẫn nhân viên. Trang khách (`/web/booking/**`) vẫn che dạng `0987 xxx 321` (`phone_masked`); log và Zalo luôn che |

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
vẫn là 422 mặc định của FastAPI, khi đó `detail` là **mảng**.

### Bảo mật và quyền

| Code | HTTP | Khi nào |
|---|---|---|
| E-AUTH-1 | 401 | Chưa đăng nhập. **(T-013)** Với phiên Admin/nhân viên có thêm `detail.reason` ∈ `unauthenticated` · `expired` · `password_changed` · `account_disabled` |
| E-AUTH-2 | 403 | Đăng nhập rồi nhưng thiếu quyền. Cũng dùng khi đặt tại quầy cho ngày khác hôm nay (kể cả Admin: ngày sau chỉ qua Đặt sự kiện) |
| E-SEC-1 | 403 | `Origin`/`Referer` không thuộc `ALLOWED_ORIGINS` |
| E-SEC-2 | 400 | Thiếu hoặc sai dạng `Idempotency-Key` |
| E-SEC-3 | 409 | Key đang được xử lý ở request khác |
| E-SEC-4 | 422 | Key đã dùng với nội dung khác |
| E-SEC-5 | 429 | Vượt rate limit (có `Retry-After`) |
| E-SEC-6 | 413 | Body lớn hơn 64 KB |
| E-NOT-FOUND | 404 | Mã sân, sự kiện, booking/vé hoặc id Lễ/Tết không có |

### Cấu hình sân và bảng giá

| Code | HTTP | Khi nào |
|---|---|---|
| E-CFG-1 | 422 / 409 | Tên sân trống hoặc quá 50 ký tự (422); trùng tên, không phân biệt hoa thường (409) |
| E-CFG-2 | 422 | Giờ đóng cửa chưa cách giờ mở ít nhất 60 phút |
| E-CFG-3 | 409 | Đổi giờ mà còn chỗ đã đặt từ ngày mai nằm ngoài giờ mới. Thêm `items:[{code,date,start_time,end_time}]` (tối đa 6) và `more` (số khung còn lại) |
| E-CFG-4 | 409 | Ngừng sân mà còn chỗ đã đặt từ hôm nay. Có `items` và `more` như trên |
| E-CFG-5 | 422 | Khung cao điểm ngắn hơn 30 phút, ngoài giờ mở cửa hoặc chồng nhau |
| E-CFG-6 | 422 | Bảng giá: ô ≤ 0, thiếu ô hoặc trùng ô |
| E-CFG-7 | 409 | `version` cũ (sân hoặc bảng giá đã bị máy khác sửa) – tải lại rồi sửa tiếp |
| E-CFG-8 | 409 | Khoảng Lễ/Tết trùng ngày đã có: "Ngày dd/mm đã nằm trong {tên}." |
| E-CFG-9 | 422 | `resource_type_code` không tồn tại |
| E-CFG-10 | 422 | Khung không bán được: ngoài giờ mở của sân, sân đang ngừng, hoặc giờ kết thúc ≤ giờ bắt đầu (báo giá và đặt sân) |
| E-019 | 422 | Thiếu giá cho khung |

### Đặt sân, sự kiện, thu tiền (số mã theo SRS v0.2)

| Code | HTTP | Khi nào |
|---|---|---|
| E-001 | 422 | Thiếu ô bắt buộc (tên ô nằm trong `message`) |
| E-002 | 422 | SĐT sai định dạng (cần `0` + 9 chữ số) |
| E-003 | 409 | Khung vừa có người khác đặt (chống trùng lịch ở DB) |
| E-004 | 422 | Khung hoặc buổi đã qua (khung đã qua = giờ kết thúc ≤ bây giờ; khung đang diễn ra vẫn đặt được) |
| E-009 | 422 | Số chỗ ngoài 1–99 |
| E-010 | 409 | Sự kiện vướng khung đã có người đặt: "Khung HH:MM–HH:MM ở {Tên sân} đã có người đặt…" |
| E-012 | 409 | Dữ liệu vừa được cập nhật ở máy khác (`version` cũ, hoặc booking/vé không còn Chưa thanh toán) – tải lại |
| E-013 | 422 | Giá vé không hợp lệ (số nguyên ≥ 0) |
| E-014 | 422 | Không tìm thấy hội viên |
| E-016 | 422 | Khoảng ngày sai (từ > đến) |
| E-018 | 409 | SĐT này là của hội viên – chọn hội viên thay vì tạo hồ sơ tạm |
| E-020 | 422 | Khoảng ngày quá 92 ngày |
| E-021 | 404 | Không thấy mã khi tìm |
| E-023 | 409 | Xóa buổi nhưng đã có vé hoặc chỗ đang giữ |
| E-024 | 409 | Sự kiện đã đủ chỗ |
| E-BOOK-1 | 422 | Ngày sau "hết tháng sau" – **T-008 bỏ giới hạn này** (người dùng chốt 28/10): backend không còn trả mã này |
| E-BOOK-2 | 422 | Sân của sự kiện không liền nhau |
| E-PAY-0 | 422 | Thu chuyển khoản tại quầy – chưa hỗ trợ (chờ T-007) |
| E-PAY-1 | 422 | Đánh dấu Không thu được với booking online, hoặc chưa tới giờ chơi |

Thông báo thành công (E-005, E-006, E-008, E-011, E-022, E-026) không có trong API: giao diện tự dựng từ response.

## 3. Quyền

Quyền khai báo tập trung ở `backend/app/core/permissions.py`. Router dùng `Depends(require(Perm.X))`,
**không so vai trực tiếp**. Vai hiện có: `admin` = Admin (chủ sân, có mọi quyền), `staff` = Tài khoản tại máy (dùng chung), `member` = khách có tài khoản web (chưa có quyền booking nào; trước PR #21 vai này tên `customer`).
**(T-013)** `staff` đổi thành **mỗi nhân viên một tài khoản** (mã `NV001`…); quyền của `staff` giữ nguyên như cột `staff` dưới đây. Thêm quyền `staff.manage` (`Perm.STAFF_MANAGE`) chỉ Admin có; `content.manage` (`Perm.CONTENT_MANAGE`, tin tức / trang nội dung, chỉ Admin) thay cho kiểm vai trực tiếp trước đây. Quyền vẫn tính từ `principal_of`, nhưng người dùng giờ đến từ hai nguồn: cookie `admin_session` (Admin/nhân viên) hoặc JWT (khách).

| Quyền | admin | staff | Dùng cho |
|---|:-:|:-:|---|
| `booking.resources.view` | ✔ | ✔ | `GET /booking/resources` |
| `booking.config.manage` | ✔ | | Sửa sân, giờ, bảng giá, Lễ/Tết; xem bảng giá đầy đủ và Lễ/Tết |
| `booking.quote` | ✔ | ✔ | `POST /booking/quote` |
| `booking.calendar.view` | ✔ | ✔ | `GET /booking/calendar` |
| `booking.search` | ✔ | ✔ | `GET /booking/search` |
| `booking.counter.create` | ✔ | ✔ | `POST /front-desk/bookings` |
| `booking.ticket.create` | ✔ | ✔ | `POST /front-desk/sessions/{code}/tickets` |
| `booking.item.view` | ✔ | ✔ | `GET /booking/items/{code}` |
| `booking.session.view` | ✔ | ✔ | `GET /booking/sessions/{code}` |
| `booking.session.manage` | ✔ | | Tạo và xóa sự kiện |
| `booking.collect` | ✔ | ✔ | Thu tiền |
| `booking.uncollectible` | ✔ | ✔ | Đánh dấu Không thu được |
| `booking.transactions.view` | ✔ | | Lịch sử giao dịch |
| `member.search` | ✔ | ✔ | `GET /members/search` |
| `member.manage` (PR #21) | ✔ | ✔ | Màn Hội viên: danh sách, chi tiết, thêm, sửa, hồ sơ tạm; đọc danh mục vợt (mục 12) |
| `member.status` (PR #21) | ✔ | | Đổi Trạng thái Hoạt động / Ngừng của hội viên |
| `racket.manage` (PR #21) | ✔ | | Thêm, sửa, ẩn, xóa vợt trong danh mục |
| `payments.view` | ✔ | | `GET /payments/bank-transactions` (Tiền về cần xử lý) |
| `payments.resolve` | ✔ | | `POST /payments/bank-transactions/{id}/resolve`, `POST /payments/dev/simulate` |
| `payments.settings` | ✔ | | `GET/PUT /payments/settings`, `GET /payments/banks` (T-012) |
| `staff.manage` (T-013) | ✔ | | `/admin/staff*`: danh sách, tạo, khóa, đặt lại mật khẩu, phiên của nhân viên (mục 11.3) |
| `content.manage` (T-013) | ✔ | | Quản lý tin tức / trang nội dung |

API **công khai** của T-008 (`/web/booking/**`, webhook `POST /payments/sepay/webhook`) không dùng quyền: khách không đăng nhập (mục 10). **(T-013)** Các route `/auth/sign-in`, `/auth/google`, `/auth/register`, `/auth/password-reset/*` cũng công khai (mục 11).

Chưa đăng nhập → 401 `E-AUTH-1`; thiếu quyền → 403 `E-AUTH-2`. Thêm route mới phải khai báo quyền; `tests/test_permissions.py` quét mọi route quản trị.

## 4. Cấu hình sân và bảng giá – tiền tố `/api/v1/booking`

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
| GET | `/prices/public` | **không cần đăng nhập** | Bảng giá rút gọn cho trang chủ (mục 4.1) |

Quy ước dữ liệu:

- Giờ dạng `"HH:MM"` (phút là `00` hoặc `30`); đóng cửa được phép `"24:00"`.
- `peak_bands`: danh sách cặp giờ, ví dụ `[["05:00","07:00"],["17:00","21:00"]]`.
- `day_type`: `weekday` | `weekend` | `holiday` (ngày thuộc danh mục Lễ/Tết → `holiday`; thứ Bảy, Chủ nhật → `weekend`).
- `band` của bảng giá: `offpeak` | `peak`. Trong báo giá, mỗi khung 1 giờ có thể là `offpeak` | `partial` (một nửa cao điểm) | `peak`.
- Tiền là số nguyên VND. Khung nửa cao điểm có tổng lẻ thì làm tròn lên.
- Giá mới chỉ áp cho khung **chưa đặt**; booking chốt giá lúc đặt.
- `version` chống ghi đè: gửi lại đúng `version` đã đọc; lệch → 409 `E-CFG-7`.

### 4.1 Bảng giá công khai (trang chủ)

`GET /api/v1/booking/prices/public` – không cần đăng nhập, header `Cache-Control: public, max-age=300`. Không lộ `version`, người sửa hay id nội bộ.
Trả `{currency, unit, updated_at, resource_types[], prices[], opening_hours, peak_bands[], special_days[]}`:

| Trường | Ý nghĩa |
|---|---|
| `resource_types[]` | `{code, name, resource_count}` – chỉ loại có sân đang hoạt động |
| `prices[]` | `{resource_type_code, day_type, band, price_per_hour}` |
| `opening_hours` | `{earliest_open, latest_close}` theo lịch hiệu lực hôm nay của sân đang hoạt động; từng trường có thể `null` khi chưa có sân hoạt động |
| `peak_bands[]` | `{resource_type_code, bands}` – hợp các khung cao điểm hôm nay theo loại |
| `special_days[]` | `{date_from, date_to, name}` – Lễ/Tết từ hôm nay đến hết năm |

## 5. Lịch, đặt tại quầy, sự kiện, thu tiền (T-006)

Quyền theo bảng mục 3. "Hôm nay" tính theo `Asia/Ho_Chi_Minh`.

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/api/v1/booking/calendar?date=YYYY-MM-DD` | Lịch một ngày: `{date, now, is_past, columns[], resources[], blocks[], unpaid_count, can}` |
| GET | `/api/v1/booking/search?code=` | Tìm **chính xác** theo mã (bỏ khoảng trắng, không phân biệt hoa thường) → `{kind: booking\|ticket\|session, code, play_date}`; không thấy → 404 `E-021` |
| GET | `/api/v1/members/search?q=` | Tối đa 20 hội viên `{ref, member_code, name, phone, tier, is_active}`; tìm theo mã, tên hoặc SĐT (≥ 3 chữ số), gồm cả hội viên Ngừng |
| POST | `/api/v1/front-desk/bookings` → 201 | Đặt sân tại quầy. Body `{resource_code, date, start_hour, end_hour, customer}` → `ItemOut` |
| GET | `/api/v1/booking/items/{code}` | Thông tin booking hoặc vé → `ItemOut` |
| POST | `/api/v1/booking/sessions` → 201 | Tạo sự kiện (Admin). Body `{resource_codes[], date, start_hour, end_hour, name, capacity, ticket_price}` → `SessionOut` |
| GET | `/api/v1/booking/sessions/{code}` | Chi tiết sự kiện → `SessionOut` |
| DELETE | `/api/v1/booking/sessions/{code}` | Xóa sự kiện (Admin). Body `{version}` → 200 `SessionOut` với `status: "deleted"` |
| POST | `/api/v1/front-desk/sessions/{code}/tickets` → 201 | Đăng ký vé tại quầy. Body `{customer}` → `ItemOut` (`kind: "ticket"`) |
| POST | `/api/v1/booking/items/{code}/collect` | Thu tiền. Body `{method: "cash", version}` → `ItemOut`; `"transfer"` → 422 `E-PAY-0` |
| POST | `/api/v1/booking/items/{code}/uncollectible` | Không thu được. Body `{reason, version}` (lý do 1–200 ký tự) → `ItemOut` |
| GET | `/api/v1/booking/transactions?from&to&resource&status&method&q&page` | Lịch sử giao dịch (Admin) |

### Khách đặt (`customer`)

Client chỉ gửi **một** trong hai dạng; snapshot tên/SĐT do server dựng, client không bao giờ gửi:

- Hội viên: `{"member_code": "HV0031"}`.
- Hồ sơ tạm: `{"temp": {"full_name": "…", "phone": "0987654321", "note": "…"}}` – họ tên 1–100 ký tự, SĐT `0` + 9 chữ số, ghi chú tùy chọn (lưu vào booking).
  SĐT trùng hồ sơ tạm cũ → dùng lại hồ sơ cũ và **giữ tên cũ**; trùng SĐT hội viên → 409 `E-018`.

### Lịch (`/booking/calendar`)

- `columns[]`: các giờ bắt đầu (số nguyên) từ giờ mở sớm nhất đến đóng muộn nhất của các sân; tự nới khi có khối ngoài giờ.
- `resources[]`: `{code, name, type, is_active, off_hours[]}`; `off_hours` là các giờ ô Xám (ngoài giờ mở hoặc sân Ngừng). Sân ngừng chỉ hiện khi còn chỗ chiếm trong ngày.
- `blocks[]`: `{type: booking|session|hold, code, resource_codes[], start_time, end_time, start_hour, end_hour}`, thêm:
  booking → `payment_status, customer_name, phone, source`; sự kiện → `name, taken, capacity, is_full, unpaid_tickets`; giữ chỗ → `expires_at` (`code` là `null`).
- `unpaid_count`: số booking + vé Chưa thanh toán của **ngày đang xem**.
- `can`: `{counter_book, create_session}` – theo quyền của người đang đăng nhập.
- Xem được ngày đã qua (chỉ xem) và **mọi ngày tương lai** (từ T-008: booking online đặt xa vẫn phải hiện). Từ T-008, Admin tạo sự kiện cho **mọi ngày tương lai** (`can.create_session` = Admin và ngày ≥ hôm nay; ngày đã qua → 422 `E-004`). `can.counter_book` chỉ `true` cho hôm nay.

### Booking và vé (`ItemOut`)

`{kind: booking|ticket, code, version, source, customer, schedule, payment, note?, created_by, created_at, actions[], price_breakdown[]}`:

- `customer`: `{name, phone, profile_label, kind, member_code, tier}`.
- `schedule`: `{resource_codes[], resource_names[], play_date, start_time, end_time, session?}`.
- `payment`: `{amount, payment_status, payment_method?, paid_at?, collected_by?, uncollectible_reason?, marked_by?, marked_at?}`.
- `payment_status`: `unpaid` → `paid` hoặc `unpaid` → `uncollectible`. Hai trạng thái cuối **không đổi** (không hủy, không hoàn tiền).
- `actions[]`: chỉ gồm thao tác được phép **lúc này** và người đang đăng nhập có quyền (`collect`, `uncollectible`).
- `price_breakdown[]`: `{start_time, end_time, band, label, price}` – giá từng khung chốt lúc đặt (vé: mảng rỗng).
- Gửi `collect`/`uncollectible` với `version` cũ hoặc khi đã đổi trạng thái → 409 `E-012`, không ghi đè.

### Sự kiện (`SessionOut`)

`{code, name, play_date, start_time, end_time, resources[], ticket_price, capacity, taken, is_full, status, created_by, created_at, version, tickets[], active_holds[], can}`:

- `tickets[]` (mới nhất trước): `{code, customer_name, phone, source, payment_status, amount, created_at}`. Mã vé `{mã sự kiện}-Vnn`.
- `taken` = số vé (mọi trạng thái) + chỗ giữ online còn hạn. Đăng ký vé khóa dòng sự kiện nên 20 request tranh chỗ cuối chỉ 1 thành công, còn lại `E-024`.
- `active_holds[]`: `{seats, expires_at}`. `can`: `{register, delete}`.
- Xóa sự kiện chỉ khi chưa có vé và chưa có chỗ giữ (xóa mềm, nhả khung); ngược lại 409 `E-023`.

### Quy tắc cần nhớ

- Đặt tại quầy: **một sân, hôm nay, cho cả Admin và Tài khoản tại máy**; ngày khác hoặc nhiều sân → 403/422 ngay cả khi giao diện bị sửa. Ngày sau và nhiều sân chỉ qua "Tạo sự kiện" (Admin), và từ T-008 sự kiện không còn giới hạn "hết tháng sau".
- Server tự tính tiền từ bảng giá lúc lưu; thiếu giá → `E-019`. Đổi bảng giá sau đó không đổi `amount` đã lưu.
- Không thu được: chỉ booking/vé `source=counter`, đang Chưa thanh toán và **đã tới giờ chơi** (`E-PAY-1` nếu không). Khung **không** bán lại.
- Vé tại quầy chỉ cho buổi **hôm nay, chưa kết thúc** (ngược lại `E-004`).
- Chống trùng lịch bằng exclusion constraint Postgres, không bằng code: hai máy cùng đặt một khung → đúng một thành công, máy kia nhận `E-003` (hoặc `E-010` với sự kiện).
- Mã booking/sự kiện `BK-YYYYMMDD-NNN` theo **ngày chơi**, tuần tự; mã đã lưu không cấp lại.

### Lịch sử giao dịch (`/booking/transactions`, chỉ Admin)

- Bộ lọc: `from`, `to` (ngày chơi; mặc định hôm nay trừ 6 ngày đến hôm nay, tối đa 92 ngày → `E-020`, từ > đến → `E-016`), `resource`, `status`, `method`
  (chọn phương thức ⇒ chỉ lấy `paid`; "Chuyển khoản" gồm cả online), `q` (mã booking/vé, tên, SĐT), `page` (8 dòng/trang).
- Trả `{date_from, date_to, rows[], page, page_size: 8, total, cards:{paid, unpaid, uncollectible}}`, mỗi thẻ có `{amount, count}`, tính đúng theo bộ lọc.
- Sắp xếp: giờ chơi mới nhất → mã sân → mã.

## 6. Biến môi trường

Khai báo trong `backend/app/core/config.py`, mẫu ở `backend/.env.example`.

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ALLOWED_ORIGINS` | `["http://localhost:3000"]` | Origin được gửi request ghi kèm cookie (chống CSRF). Production: `["https://chienthang.superbai.vip"]`; dev: `["https://chienthang-dev.superbai.vip"]`. Worktree FRONTEND chạy cổng 3102 phải thêm `http://localhost:3102` |
| `TRUSTED_PROXY_COUNT` | `0` | Số proxy tin cậy đứng trước API để lấy IP thật từ `X-Forwarded-For`. **Trên server dev và production đặt `1`**: Caddy ghi `X-Forwarded-For` = IP client, Next chuyển nguyên và không nối thêm. Đặt `2` sẽ lấy nhầm IP container web (đo trên dev: `172.19.0.6`) → mọi người dùng chung một bộ đếm, dễ dính 429. `0` (mặc định, dùng khi chạy cục bộ không qua proxy) = dùng IP kết nối trực tiếp; nếu đặt `0` trên server thì cũng chung một bộ đếm |
| `RATE_LIMIT_ENABLED` | `true` | Bật/tắt rate limit |
| `RATE_LIMIT_PER_MINUTE` | `120` | Giới hạn mặc định theo IP |
| `MAX_BODY_BYTES` | `65536` | Kích thước body tối đa |
| `TENANT_ID` | `1` | Tenant của bản chạy này (mỗi dự án một bản chạy) |
| `ENV` | `development` | Chỉ nhận `development` (máy dev) · `staging` (link dev công khai) · `production`. Giá trị khác → API không khởi động. `staging` và `production` bắt buộc `SECRET_KEY` ≥ 32 ký tự và **tắt `/docs`, `/api/v1/openapi.json`** |
| `PAYMENTS_ENCRYPTION_KEY` | trống | Khóa Fernet (44 ký tự base64 urlsafe = 32 byte) mã hóa khóa webhook lưu trong DB (T-012). **Secret. Bắt buộc khi `ENV=staging`/`production`** (thiếu hoặc sai dạng → API không khởi động). `development` thiếu → khóa tạm + log cảnh báo. Đổi hoặc mất khóa này thì khóa webhook đã lưu không đọc được (webhook 503, đặt online tự tắt) cho tới khi Admin nhập lại |
| `SEPAY_BANK_CODE` | trống | **Dự phòng** (chỉ dùng khi chưa có cài đặt lưu trên trang, mục 10.7). Mã ngân hàng cho `qr.sepay.vn` (ví dụ `Vietcombank`) |
| `SEPAY_BANK_NAME` | trống | Tên ngân hàng hiển thị cho khách |
| `SEPAY_ACCOUNT_NUMBER` | trống | Số tài khoản nhận tiền. Webhook báo tiền vào tài khoản khác sẽ bị bỏ qua (`ignored`) |
| `SEPAY_ACCOUNT_NAME` | trống | Tên chủ tài khoản hiển thị cho khách |
| `SEPAY_WEBHOOK_SECRET` | trống | Khóa ký webhook (HMAC). **Secret – không ghi vào repo, board hay tin nhắn** |
| `SEPAY_TIMESTAMP_TOLERANCE_SECONDS` | `0` | `0` = không chặn theo tuổi của timestamp; `> 0` = lệch quá số giây này → 401 |
| `ONLINE_HOLD_MINUTES` | `5` | Thời gian giữ chỗ online |
| `ONLINE_HOLD_GRACE_SECONDS` | `60` | Ân hạn nhận tiền báo trễ sau khi hết giữ chỗ (khung vẫn bị chiếm trong lúc này) |
| `PAYMENTS_SIMULATE` | `false` | Bật `POST /payments/dev/simulate` (giả lập tiền về). `ENV=production` mà bật → API **không khởi động** |
| `FIRST_ADMIN_PHONE` **(T-013)** | `0912345678` | Thay `FIRST_ADMIN_EMAIL`. SĐT Admin đầu tiên. Migration T-013 cũng dùng biến này để gán SĐT cho Admin cũ chưa có; **thiếu hoặc sai → migration dừng**. Production: SĐT thật, phải có trong `.env` **trước** khi deploy |
| `FIRST_ADMIN_PASSWORD` | `Admin@12345` (mẫu, `.env.example`) | Chỉ dùng khi **chưa có Admin**; không bao giờ ghi đè mật khẩu Admin đã có. Production từ chối mật khẩu mẫu hoặc yếu |
| `ADMIN_SESSION_HOURS` **(T-013)** | `12` | Hạn cứng của phiên Admin/nhân viên |
| `LOGIN_MAX_ATTEMPTS` · `LOGIN_LOCK_MINUTES` | `5` · `15` | Số lần sai liên tiếp và thời gian khóa tài khoản |
| `LOGIN_IP_MAX_ATTEMPTS` · `LOGIN_IP_WINDOW_MINUTES` | `20` · `15` | Giới hạn lần sai theo IP |
| `REGISTER_IP_MAX_PER_HOUR` | `10` | Đăng ký tài khoản khách theo IP |
| `OTP_TTL_MINUTES` · `OTP_MAX_ATTEMPTS` · `OTP_RESEND_SECONDS` | `5` · `5` · `60` | Hạn mã, số lần nhập sai, giãn cách gửi lại |
| `OTP_MAX_PER_HOUR` · `OTP_IP_MAX_PER_HOUR` | `5` · `20` | Số mã tối đa mỗi giờ theo SĐT và theo IP |
| `OTP_RESET_TOKEN_MINUTES` · `BOOKING_PHONE_TOKEN_MINUTES` | `10` · `30` | Hạn `reset_token` (quên mật khẩu) và `phone_token` (đặt online) |
| `OTP_TEST_MODE` | `false` | Chế độ thử OTP, mục 11.5. `true` cùng `ENV=production` → API **không khởi động** |
| `ZALO_APP_ID` · `ZALO_SECRET_KEY` · `ZALO_REFRESH_TOKEN` · `ZALO_TEMPLATE_OTP` | trống | Gửi OTP qua Zalo ZNS. **Chưa dùng được** (client còn `TODO`). Secret – không ghi vào repo |
| `GOOGLE_CLIENT_ID` | trống | Đăng nhập Google (backend kiểm `aud`). Frontend dùng `NEXT_PUBLIC_GOOGLE_CLIENT_ID` (công khai, truyền lúc build qua biến repo `GOOGLE_CLIENT_ID`) |

**Biến đánh dấu (T-013)** có trong `dev`; giá trị mặc định khớp `backend/.env.example`.

**Bật đặt online**: từ T-012 Admin cài trên trang (mục 10.7); các biến `SEPAY_*` chỉ là dự phòng khi **chưa có dòng cài đặt trong DB**. Khi dùng `.env`, đặt online bật khi đủ 5 biến `SEPAY_*` đầu (mã NH, tên NH, số TK, tên chủ TK, secret). Thiếu thì `online_enabled=false`:
khách vẫn xem lịch nhưng không đặt được (`E-WEB-5`, giao diện hiện "gọi hotline").
**(T-013)** Ngoài SePay, đặt online còn cần **kênh OTP**: đủ 4 biến `ZALO_*` **hoặc** `OTP_TEST_MODE=true`. Thiếu kênh OTP thì xử lý như thiếu SePay (`online_enabled=false`, `E-WEB-5`). Vì Zalo chưa làm, production chỉ đặt tại quầy cho tới khi có Zalo.

Rate limit dùng Redis. Redis lỗi thì cho qua và ghi log (không chặn người dùng).

**Đã bỏ** (T-006): `OPEN_TIME`, `CLOSE_TIME`, `SLOT_MINUTES`, `MIN_BOOKING_MINUTES`, `MAX_ADVANCE_DAYS`, `HOLD_MINUTES`.
Giờ mở cửa, cao điểm, giá theo từng sân trong booking engine; thời gian giữ chỗ nằm trong `tenant.settings`. Còn dòng cũ trong `.env` thì vô hại (bị bỏ qua).

## 7. Worker (ARQ)

Chạy bằng `arq app.workers.worker.WorkerSettings`.

| Job | Chu kỳ | Việc |
|---|---|---|
| `publish_booking_outbox` | mỗi 2 giây | Đọc outbox của engine, phát sự kiện nội bộ (vd. `booking.created`) |
| `expire_holds` | mỗi 30 giây | Giữ chỗ quá `expires_at` → hết hạn, nhả khung. Giữ chỗ quá hạn không hiện trên lịch và không chặn đặt dù job chưa chạy. Từ T-008 cũng đóng lượt thanh toán online `pending` quá `expires_at` + ân hạn (→ `expired`) và phát `checkout.expired` nếu lượt đó đã nhận một phần tiền |
| `purge_audit_log` | hằng ngày 03:15 | Xóa dòng nhật ký quá 12 tháng |
| `purge_idempotency_keys` | mỗi giờ (phút 5) | Xóa key quá 24 giờ |
| `purge_otp_codes` (T-013) | mỗi giờ (phút 35) | Xóa mã OTP quá 24 giờ |
| `send_zalo_otp` (T-013) | theo yêu cầu | Gửi OTP qua Zalo ZNS. **Hiện là stub, chưa gửi thật** |

Job `expire_pending_bookings` của luồng cũ đã bỏ.

## 8. Luồng đặt sân cũ đã gỡ (T-006)

Các route sau **trả 404**: `/bookings*`, `/admin/bookings*` (kể cả `/payments`), `/courts`, `/admin/courts*`, `/venue/config`, `/price-rules`, `/admin/price-rules*`.
Module `bookings`, `courts`, `payments` đã xóa khỏi code. Còn giữ: `auth`, `content`, `notifications`.

- Bảng cũ `courts`, `price_rules`, `bookings`, `booking_slots`, `payments` được **đổi tên** thành `legacy_*` bằng migration (**không xóa dữ liệu**, downgrade đổi lại). `alembic check` bỏ qua các bảng `legacy_*`. Xóa hẳn ở một task sau khi người dùng xác nhận.
- Trước khi lên production cần đếm đơn cũ còn hiệu lực (RELEASE báo người dùng).
- `GET /admin/users` đã đổi thành `GET /admin/staff` (mục 11); danh sách nhân viên không có trường SĐT.
- Trang chủ lấy bảng giá từ `GET /booking/prices/public`; khu đặt online tạm thay bằng thông tin đặt tại quầy cho tới khi có Web khách hàng (T-008).

## 9. Chạy thử cục bộ

```powershell
cd backend
.venv\Scripts\alembic upgrade head        # tạo schema booking, audit_log, idempotency_keys, bảng booking/session/ticket
.venv\Scripts\python -m app.scripts.seed  # admin đầu tiên; khi ENV khác production: sân S01–S06, bảng giá, Lễ/Tết 2026, 10 hội viên, 4 hồ sơ tạm
.venv\Scripts\uvicorn app.main:app --reload --port 8000
```

Hoặc cả DB + API + web bằng một lệnh ở gốc repo: xem README mục "Chạy dev". Compose của dev/production đặt `ENV=production` nên seed bỏ qua dữ liệu demo;
muốn nạp demo trên server dev thì chạy một lần với `ENV=development` (việc của RELEASE).
Migration quay lui được (`alembic downgrade`), không xóa dữ liệu bảng cũ.

## 10. Đặt online, thanh toán QR SePay, tra cứu (T-008)

> Đã có trong `dev` (PR #16). Đối chiếu code: `backend/app/modules/web_booking/`, `payments/`, `booking_engine/online_service.py`.

### 10.1 Luồng

1. Khách xem lịch: `GET /web/booking/calendar` (không cần đăng nhập).
2. Chọn ô, nhập họ tên + SĐT. **(T-013)** Khách bấm "Gửi mã" (`POST /web/booking/phone/request`), nhập OTP (`POST /web/booking/phone/verify` → `phone_token`); khách đã đăng nhập với SĐT đã xác minh thì bỏ qua bước này. Rồi `POST /web/booking/checkouts` → server giữ chỗ **5 phút**, cấp mã `BK-YYYYMMDD-NNN` cho từng dải giờ liền nhau của từng sân, trả `token` (chỉ trả **một lần**) và thông tin chuyển khoản.
3. Khách quét QR, chuyển khoản với **nội dung = `pay_ref`**. Trang hỏi `GET /web/booking/checkouts/{token}` (mỗi 3 giây).
4. SePay báo tiền về qua webhook → server đủ tiền thì **trong cùng transaction** tạo booking (`source=online`, cùng mã đã cấp, `payment_status=paid`, `payment_method=online_transfer`) và đóng lượt thanh toán `paid`.
5. Quá `expires_at` + 60 giây mà chưa đủ tiền → worker đóng lượt `expired`, nhả khung. Tiền về sau đó **không** tạo booking: ghi thành "cần hoàn" cho Admin xử lý.

`pay_ref` = mã booking đầu tiên bỏ gạch (`BK-20261020-023` → `BK20261020023`). Booking online hiện trên lịch quầy như T-006 (Đỏ, nguồn Online).

### 10.2 API công khai – tiền tố `/api/v1/web/booking`

| Method | Path | Rate limit | Ghi chú |
|---|---|---|---|
| GET | `/calendar?date=YYYY-MM-DD` | 60/phút/IP | `Cache-Control: no-store`. Ngày đã qua → 422 `E-WEB-2` |
| POST | `/checkouts` → 201 | 6 lần/10 phút/IP (tính cả lần lỗi) | Cần `Origin` hợp lệ và `Idempotency-Key`. Thiếu cấu hình SePay → 503 `E-WEB-5` |
| POST | `/phone/request` → 202 **(T-013)** | theo mục 11.4 | Body `{phone}` → `{resend_after}`; chế độ thử thêm `test_otp`. Cần `Origin`, không cần đăng nhập |
| POST | `/phone/verify` **(T-013)** | theo mục 11.4 | Body `{phone, otp}` → `{phone_token, expires_at, account_verified}`. Khách đang đăng nhập có SĐT tài khoản trùng SĐT vừa xác minh → `account_verified: true` và tài khoản được đánh dấu đã xác minh, lần đặt sau bỏ qua OTP. Không gắn SĐT cho tài khoản chưa có SĐT, không gộp (việc đó qua `/auth/phone/*`) |
| GET | `/checkouts/{token}` | 120/phút/IP | `no-store`. Token sai → 404 `E-WEB-6` |
| POST | `/lookup` | 10/phút/IP | Cần `Origin`; **không** cần `Idempotency-Key` |

Vượt rate limit → 429 `E-SEC-5`. Không cần cookie.

**`GET /calendar`** → `{date, server_now, online_enabled, hold_minutes, columns[], resources[]}`;
`resources[]` = `{code, name, slots[]}`, mỗi ô `{start_hour, state, price, band, taken, capacity}`.

| `state` | Ý nghĩa | Trường kèm theo |
|---|---|---|
| `free` | Trống, bán được | `price` (VND), `band` (`offpeak`/`peak`) |
| `booked` | Đã có booking **hoặc** người khác đang giữ chỗ | – |
| `event` | Sự kiện (chỉ hiển thị, chưa bán vé online) | `taken`, `capacity` |
| `closed` | Không bán: khung đã bắt đầu/đã qua, hoặc ngoài giờ mở của sân | – |

Trường không dùng có giá trị `null`. Response **không** chứa tên, SĐT, mã hay ghi chú của ai. Sân ngừng hoạt động không có trong danh sách.

**`POST /checkouts`** – body (trường lạ bị từ chối):

```json
{ "date": "2026-10-20",
  "slots": [{ "resource_code": "S01", "start_hour": 19 }, { "resource_code": "S01", "start_hour": 20 }],
  "full_name": "Phạm Quang Minh", "phone": "0935 240 123", "note": "cần mượn vợt",
  "phone_token": "…từ /phone/verify (T-013)…" }
```

- Tối đa **16** ô/lần, trong **một ngày**, nhiều sân được. Không giới hạn số ngày đặt trước. `note` ≤ 200 ký tự, họ tên 1–100 ký tự.
- SĐT chuẩn hóa như quầy (bỏ khoảng trắng/chấm/gạch, `+84` → `0`), phải là `0` + 9 chữ số.
- **Không gửi giá hay tổng tiền**: server tự tính từ bảng giá hiện hành và chốt lúc đặt.
- Một SĐT chỉ có **1 lượt đang chờ** thanh toán (lượt thứ hai → 409 `E-WEB-4`).
- **(T-013) Phải xác minh SĐT bằng OTP trước khi giữ chỗ.** Body thêm `phone_token`, lấy từ `POST /phone/verify`. Thiếu, sai, hết hạn (30 phút) hoặc khác SĐT trong body → 403 `E-WEB-8`. Một `phone_token` dùng được cho nhiều lượt checkout của **cùng SĐT** trong hạn. **Ngoại lệ:** khách đã đăng nhập, SĐT đã xác minh và trùng body thì không cần `phone_token`. `/tra-cuu` (mã + SĐT) và đặt tại quầy **không** cần OTP.
- Trùng khung do exclusion constraint → 409 `E-WEB-3`, không tạo gì. Hai máy bấm cùng lúc: đúng một bên thành công.

→ 201:

```json
{ "token": "…43 ký tự…", "status": "pending", "expires_at": "…+07:00", "server_now": "…+07:00",
  "amount": 288000, "paid_amount": 0, "paid_at": null, "pay_ref": "BK20261020023",
  "bank": { "bank_name": "…", "account_number": "…", "account_name": "…", "qr_url": "https://qr.sepay.vn/img?…" },
  "customer": { "full_name": "Phạm Quang Minh", "phone_masked": "0935 xxx 123" },
  "items": [{ "code": "BK-20261020-023", "resource_code": "S01", "resource_name": "Sân 1", "play_date": "2026-10-20",
              "start_hour": 19, "start_time": "19:00", "end_time": "21:00", "hours": 2, "amount": 288000 }] }
```

- `token` chỉ có ở lần tạo; server chỉ lưu hash (SHA-256) và không đưa token vào log. Client giữ token để mở `/thanh-toan/{token}`, **không** đặt vào query string.
- `status`: `pending` → `paid` hoặc `expired`. `bank` chỉ có khi `pending` (các trạng thái khác là `null`).
- Đếm ngược theo `expires_at` và `server_now` (bù lệch giờ máy khách), không theo đồng hồ máy.

**`GET /checkouts/{token}`** → cùng dạng, không có `token`.

**`POST /lookup`** – body `{"code": "bk20261020023", "phone": "0935240123"}`. Mã nhận có/không gạch, hoa/thường, khoảng trắng thừa.

→ 200 `{code, status, resource_name, play_date, start_time, end_time, hours, customer_name, phone_masked, amount, payment_method_label, paid_at, pending}`:

| `status` | Ý nghĩa |
|---|---|
| `paid` | Đã thanh toán |
| `unpaid` | Chưa thanh toán (booking quầy) |
| `uncollectible` | Không thu được |
| `pending` | Giữ chỗ còn hạn; có `pending: {expires_at, server_now, pay_ref, amount, bank}` (`amount` là tổng cả lượt) |
| `expired` | Giữ chỗ hết hạn |

Sai mã **hay** sai SĐT đều trả cùng 404 `E-WEB-7`, kể cả khi mã là vé/sự kiện (chưa hỗ trợ). SĐT luôn che.

### 10.3 Mã lỗi

| Code | HTTP | Thông điệp / khi nào |
|---|---|---|
| E-WEB-1 | 422 | Theo trường: "Vui lòng nhập họ tên." · "Số điện thoại không hợp lệ — cần đủ 10 số." · "Ghi chú tối đa 200 ký tự." · "Chọn ít nhất 1 khung giờ." · "Mỗi lần đặt tối đa 16 khung giờ." |
| E-WEB-2 | 422 | "Không đặt được ngày đã qua." hoặc khung đã qua, ngoài giờ mở cửa, sân ngừng hoạt động |
| E-WEB-3 | 409 | "Khung giờ vừa có người đặt. Vui lòng chọn khung khác." Kèm `detail.conflicts: [{resource_code, start_hour}]` |
| E-WEB-4 | 409 | SĐT này đang có lượt giữ chỗ chưa thanh toán |
| E-WEB-5 | 503 | Đặt online đang tạm ngưng (chưa đủ cấu hình SePay; từ T-013 còn thiếu cả kênh OTP). Gọi hotline |
| E-WEB-6 | 404 | "Không tìm thấy lượt thanh toán." (token sai hoặc không có) |
| E-WEB-7 | 404 | "Không tìm thấy booking. Kiểm tra lại mã và số điện thoại." |
| E-WEB-8 | 403 | **(T-013)** "Vui lòng xác minh số điện thoại trước khi đặt sân." Thiếu/sai/hết hạn `phone_token`, hoặc token của SĐT khác |
| E-019 | 422 | Thiếu giá cho một khung |
| E-SEC-1 | 403 | Thiếu hoặc sai `Origin`/`Referer` (`POST /checkouts`, `POST /lookup`) |
| E-PAY-2 | 409 | "Giao dịch đã được xử lý." (đánh dấu Đã xử lý lần hai) |

`E-PAY-1` vẫn là lỗi Không thu được của T-006 (mục 5), không phải lỗi thanh toán online.

### 10.4 Webhook SePay – `POST /api/v1/payments/sepay/webhook`

Ngoại lệ có chủ đích của ADR-004: **không** cookie, **không** `Origin`, **không** `Idempotency-Key`. Xác thực bằng HMAC (ADR-001); chống trùng bằng khóa duy nhất (`provider`, `id` của SePay). Route không có trong OpenAPI.

| Mục | Quy tắc |
|---|---|
| Header | `X-SePay-Timestamp` (chuỗi số) và `X-SePay-Signature` **dạng `sha256=<hex>`** – thiếu tiền tố `sha256=` → 401 |
| Chữ ký | `HMAC-SHA256(khóa webhook, "{timestamp}.{raw_body}")` (khóa Admin lưu ở trang Cài đặt thanh toán, hoặc `SEPAY_WEBHOOK_SECRET` khi chưa lưu – mục 10.7), so sánh hằng thời gian, tính trên **body gốc** (đừng parse lại). Next rewrite và Caddy phải giữ nguyên body và header `X-SePay-*` |
| Trả về | Luôn `{"success": true\|false}`. Chưa cấu hình secret → 503; thiếu/sai chữ ký hoặc timestamp → 401; body sai (không phải JSON object, thiếu `id`, `transferType` ∉ `in`/`out`, `transferAmount` không phải số nguyên > 0) → 400; lỗi DB → 500 (SePay sẽ gửi lại) |
| Trùng | Cùng `id` đã ghi → 200 `{"success": true}`, không cộng tiền lần hai |
| Bỏ qua | `transferType=out`, hoặc `accountNumber` khác `SEPAY_ACCOUNT_NUMBER` → ghi lại với `outcome=ignored` |
| Lấy mã | Trường `code`; nếu `null` thì tìm `BK` + 11 chữ số trong `content` (không phân biệt hoa thường), chỉ dùng khi tìm thấy đúng **một** mã khác nhau |

Kết quả ghi vào `payments.bank_transaction.outcome`:

| `outcome` | Khi nào | `refund_amount` |
|---|---|---|
| `applied` | Đủ tiền, đã tạo booking | Phần trả thừa (nếu có) |
| `partial` | Chuyển thiếu; lượt vẫn chờ, lần sau cộng dồn | 0 |
| `refund_needed` | Lượt đã `paid`, đã `expired` hoặc tiền về sau ân hạn; **không** tạo booking | Cả giao dịch (lượt hết hạn: cộng cả các lần `partial` trước, mỗi giao dịch đúng số của nó) |
| `unmatched` | Không có mã, hoặc không có lượt mang `pay_ref` đó | 0 |
| `ignored` | Tiền ra hoặc sai tài khoản | 0 |

Hạn nhận tiền: giờ giao dịch (`transactionDate`, giờ VN) ≤ `expires_at` + 60 giây. Trả đủ tiền ở hai webhook gần nhau cho cùng lượt → chỉ tạo booking một lần.
Khi booking online được tạo, module `members` tạo hồ sơ tạm theo SĐT nếu chưa có (giữ tên cũ nếu đã có); lỗi bước này không làm mất booking.

### 10.5 Tiền về cần xử lý và giả lập (Admin)

| Method | Path | Quyền | Ghi chú |
|---|---|---|---|
| GET | `/payments/bank-transactions?needs_action=true&limit=100` | `payments.view` | Mới nhất trước, `limit` 1–500. `needs_action=true` = chưa xử lý và là `unmatched`, `refund_needed`, hoặc `applied` có `refund_amount > 0` |
| POST | `/payments/bank-transactions/{id}/resolve` | `payments.resolve` | Body `{"note": "…"}` (1–500 ký tự, trống → 422 `E-001`); `Idempotency-Key`. Đã xử lý → 409 `E-PAY-2`; id không có → 404 `E-NOT-FOUND` |
| POST | `/payments/dev/simulate` | `payments.resolve` + `PAYMENTS_SIMULATE=true` | Body `{"pay_ref": "BK20261020023", "amount": 288000}`; `Idempotency-Key`. Cờ tắt → **404 với mọi người**. Đi đúng đường xử lý của webhook (id giả `sim-<uuid>`, bỏ qua kiểm chữ ký) |

`BankTransactionOut`: `{id, provider, provider_txn_id, received_at, transaction_at, amount, content, code, outcome, refund_amount, booking_codes[], resolved_at, resolved_by_label, note}`.
Staff gọi → 403 `E-AUTH-2`; khách → 401/403.

### 10.6 Thử trên máy dev (không cần tài khoản SePay)

Xem README mục "Đặt online và SePay" – có sẵn các biến giả và các bước giả lập tiền về. Từ T-012, có thể nhập tài khoản và khóa giả ngay trên trang Cài đặt thanh toán thay cho `.env` (mục 10.7).

### 10.7 Cài đặt thanh toán do Admin tự nhập (T-012)

> Đã có trong `dev` (PR #16). Đối chiếu code: `backend/app/modules/payments/settings_service.py`, `config.py`, `banks.py`. Hướng dẫn cho chủ sân: README mục "Hướng dẫn chủ sân cài SePay".

Admin nhập ngân hàng, số tài khoản, tên chủ, khóa webhook và công tắc **Nhận đặt online** trên `/admin/cai-dat/thanh-toan` thay vì ghi `SEPAY_*` vào `.env` server.

| Method | Path | Quyền | Ghi chú |
|---|---|---|---|
| GET | `/payments/settings` | `payments.settings` | Cấu hình đang hiệu lực + trạng thái |
| PUT | `/payments/settings` | `payments.settings` | `Idempotency-Key` + `Origin`. Mỗi lần lưu bắt buộc `current_password` |
| GET | `/payments/banks` | `payments.settings` | `[{code, short_name, name}]`, 30 ngân hàng, mã VietQR (`VCB`, `BIDV`, `ICB`, `MB`, `TCB`, `ACB`…) |

`GET /payments/settings` → `{bank_code, bank_name, account_number, account_name, online_toggle, online_enabled, missing[], secret_set, secret_last4, webhook_url, pay_code_hint, last_webhook_at, updated_at, updated_by_label, pending_checkouts, simulate_enabled}`:

- `missing[]` ⊂ `bank`, `account_number`, `account_name`, `webhook_secret` (chỉ tính theo nguồn đang dùng). `online_enabled` = `online_toggle` **và** `missing` rỗng.
- Khóa webhook **không bao giờ** có trong response, log hay nhật ký; chỉ có `secret_set` và `secret_last4` (4 ký tự cuối).
- `webhook_url` = `ALLOWED_ORIGINS[0]` + `/api/v1/payments/sepay/webhook`. `pay_code_hint` = "BK + 11 chữ số".
- `last_webhook_at`: cập nhật mỗi webhook có **chữ ký hợp lệ** (kể cả "Gửi thử" của SePay), **chỉ khi đã có dòng cài đặt** (đang dùng `.env` thì không có mốc này).
- `pending_checkouts`: số lượt đặt online đang chờ thanh toán. `simulate_enabled` = `PAYMENTS_SIMULATE` bật và không phải production.

`PUT /payments/settings` – body (trường lạ bị từ chối):

```json
{ "bank_code": "VCB", "account_number": "0123456789", "account_name": "Nguyễn Văn Đạt",
  "online_toggle": true, "webhook_secret": "…16–128 ký tự…", "current_password": "…" }
```

- `webhook_secret` bỏ qua hoặc `null` = giữ khóa cũ. Dòng cài đặt mới **không** kế thừa khóa từ `.env`.
- Tên chủ tài khoản được chuẩn hóa: viết hoa, bỏ dấu, gộp khoảng trắng (`"  Nguyễn  Văn Đạt "` → `NGUYEN VAN DAT`), rồi kiểm 2–50 ký tự A–Z và khoảng trắng.
- → 200 cùng dạng `GET`. Xóa cache cấu hình ngay khi lưu (cache bình thường ≤ 10 giây).
- Ghi nhật ký `payments.settings.update`: các trường đổi; số tài khoản chỉ 4 số cuối cũ → mới; khóa ghi "đã đổi"; lần lưu đầu từ `.env` ghi thêm nguồn chuyển sang trang.

| Code | HTTP | Khi nào |
|---|---|---|
| E-AUTH-7 | 400 | "Mật khẩu không đúng." |
| E-SEC-5 | 429 | 5 lần sai mật khẩu / 15 phút / tài khoản; trong thời gian khóa, nhập đúng cũng bị 429 (có `Retry-After`) |
| E-PAY-3 | 409 | Đổi ngân hàng hoặc số tài khoản (so với cấu hình đang hiệu lực, kể cả lần lưu đầu từ `.env`) khi còn lượt chờ thanh toán: "Đang có {n} lượt chờ thanh toán. Tắt Nhận đặt online, đợi các lượt hết hạn (tối đa 6 phút) rồi đổi tài khoản." Đổi tên chủ, khóa, công tắc thì không chặn |
| E-PAY-4 | 422 | Theo trường: "Chọn ngân hàng." · "Số tài khoản gồm 6–20 chữ số." · "Tên chủ tài khoản 2–50 ký tự, không dấu." · "Khóa bí mật 16–128 ký tự." · "Chưa đủ thông tin để bật đặt online." |

Thiếu trường bắt buộc hoặc trường lạ → 422 định dạng mặc định của FastAPI. Staff gọi → 403, khách → 401/403.

**Nguồn cấu hình** (mọi chỗ đọc `SEPAY_*` ở T-008 đã chuyển sang đây: QR, `online_enabled` của lịch khách, kiểm chữ ký webhook, bỏ qua giao dịch sai số tài khoản):

- Chưa có dòng `payments.settings` → dùng `SEPAY_*` trong `.env` (công tắc coi như bật nếu đủ biến).
- **Đã có dòng → DB là nguồn duy nhất**, không trộn từng trường với `.env`.
- Tham số `bank` trong `qr_url` là `short_name` của ngân hàng (ví dụ `Vietcombank`).
- Khóa webhook lưu bằng Fernet với `PAYMENTS_ENCRYPTION_KEY`. Không giải mã được (đổi/mất khóa) → coi như chưa có khóa: webhook 503, `online_enabled=false`, `missing` có `webhook_secret`.

## 11. Đăng nhập, nhân viên, OTP, tài khoản khách (T-013)

> Đã vào `dev` (PR #18, #19), chưa vào `main`. Spec: `board/tasks/T-013-dang-nhap-nhan-vien.md`, ADR-008. Nếu code lệch, code đúng.
> Phá vỡ tương thích: `/auth/login` → `/auth/sign-in`; `/admin/users` → `/admin/staff`; Admin/nhân viên không còn JWT; `UserOut` bỏ `email`. Backend và frontend phải lên cùng một đợt.

### 11.1 Ai đăng nhập bằng gì

| Vai | Đăng nhập bằng | Phiên | Vào |
|---|---|---|---|
| Admin (chủ sân) | Số điện thoại + mật khẩu | `admin_session` (server, 12 giờ cứng, thu hồi được) | `/admin` |
| Nhân viên | Tên đăng nhập + mật khẩu (mỗi người một tài khoản, mã `NV001`…) | như Admin | `/admin` |
| Khách | SĐT hoặc tên đăng nhập + mật khẩu, hoặc Google | JWT cookie (như cũ) + `token_version` | `/tai-khoan` |

- Một ô nhập chung "Số điện thoại hoặc tên đăng nhập". Chuỗi giống SĐT (nhận `+84`, khoảng trắng, dấu chấm, gạch) được chuẩn hóa thành `0xxxxxxxxx` rồi tìm theo SĐT; còn lại tìm theo `username`, không phân biệt hoa thường.
- Mỗi trình duyệt chỉ giữ **một** loại phiên: đăng nhập khách xóa `admin_session`, đăng nhập Admin/nhân viên xóa cookie JWT.
- Cookie `admin_session`: `httpOnly`, `secure` theo `COOKIE_SECURE`, `samesite=lax`, path `/`. Server chỉ lưu SHA-256 của token.
- Quyền của nhân viên **giữ nguyên** so với "Tài khoản tại máy" (cột `staff` ở mục 3). Nhãn người thao tác trong nhật ký và Lịch sử giao dịch: `NV007 · Nguyễn Văn An`; bản ghi cũ vẫn nhãn "Tài khoản tại máy".
- Đặt sân tại quầy **không** cần OTP.

### 11.2 API đăng nhập – tiền tố `/api/v1`

Lỗi dạng `{detail:{code,message,…}}`. Mọi POST cần `Origin` hợp lệ; `Idempotency-Key` **không bắt buộc** cho nhóm auth.

| Method | Path | Ai gọi | Ghi chú |
|---|---|---|---|
| POST | `/auth/sign-in` `{login 1–50, password 1–128}` | công khai | Khách → `{kind:"member", account:UserOut}`. Admin/nhân viên → `{kind:"admin", account:{kind:"admin"\|"staff", display_name, role_label, staff_code?}, expires_at}` |
| POST | `/auth/google` `{credential}` | công khai | ID token Google (≤ 4096 ký tự). Kết quả như khách |
| POST | `/auth/register` `{full_name, phone, password}` → 201 | công khai | Khách tự đăng ký, **không** có email. SĐT chưa được coi là đã xác minh |
| POST | `/auth/refresh` · `/auth/logout` · GET `/auth/me` | khách | Như cũ; JWT mang thêm claim `ver` |
| GET | `/admin/auth/me` | Admin/nhân viên | `{account, expires_at}` |
| POST | `/admin/auth/logout` | Admin/nhân viên | Thu hồi phiên hiện tại |
| POST | `/auth/password-reset/request` `{phone}` → 202 | công khai | `{resend_after}`; chế độ thử thêm `test_otp` (mục 11.5) |
| POST | `/auth/password-reset/verify` `{phone, otp}` | công khai | `otp` đúng 6 chữ số → `{reset_token}` (hạn 10 phút) |
| POST | `/auth/password-reset/confirm` `{reset_token, password}` → 204 | công khai | Đổi mật khẩu, thu hồi mọi phiên Admin/nhân viên, xóa khóa; SĐT coi là đã xác minh. `reset_token` dùng một lần |
| POST | `/auth/phone/request` `{phone}` → 202 · `/auth/phone/verify` `{phone, otp}` | khách đã đăng nhập | Gắn và xác minh SĐT. Mã gắn với tài khoản yêu cầu: khách B không dùng được mã gửi cho khách A. Verify → `{merged, password_cleared, account}` và đặt lại cookie JWT (gộp: JWT của chủ SĐT). Không có kênh OTP → 503 `E-AUTH-24` |

`UserOut` = `{id, phone, phone_verified, username, full_name, google_email, role, is_active, must_change_password}` (**không còn `email`**; `role` là `member` với khách; T-016 thêm `is_member`, mục 12.6). `phone` là SĐT đầy đủ vì API chỉ trả cho chính chủ. `/auth/register` đăng nhập luôn (cookie JWT). `/auth/me` chỉ dành cho khách: phiên Admin/nhân viên gọi vào → 401.

**Origin.** Mọi `POST` auth thiếu hoặc sai `Origin` → 403 `E-SEC-1`, kể cả khi chưa có cookie. `GET` (như `/auth/me`, `/admin/auth/me`) không cần `Origin`.

**Khóa tài khoản.** Sai mật khẩu 5 lần liên tiếp → khóa 15 phút (`E-AUTH-11`, 423, có `retry_after`). Hết khóa thì đếm lại từ 0; đăng nhập đúng đưa về 0. Tài khoản không tồn tại và tài khoản sai mật khẩu trả **cùng** `E-AUTH-10`. Theo IP: từ 20 lần sai trong 15 phút → `E-AUTH-12` (429, `retry_after`), tính cả lần Google token sai.

**Phiên hết hạn / bị thu hồi.** API quản trị trả 401 `E-AUTH-1` kèm `detail.reason`; giao diện chuyển về `/dang-nhap?ly-do=het-han|doi-mat-khau|tai-khoan-khoa` và hiện lời giải thích.

**Mật khẩu mới** (đăng ký, tạo nhân viên, đặt lại, lệnh server): ≥ 8 ký tự, có 1 chữ in hoa và 1 chữ số hoặc ký tự đặc biệt; sai → 422 với câu "Mật khẩu cần … .". Mật khẩu cũ yếu vẫn đăng nhập được.

**Google.** Server kiểm ID token (RS256, `aud`, `iss`, `exp`; khóa JWKS cache 1 giờ), tìm theo `google_sub`, chưa có thì tạo khách không mật khẩu và không SĐT. **Không bao giờ nối tài khoản theo email.** Chưa đặt `GOOGLE_CLIENT_ID` → `E-AUTH-19`. Token Google sai cộng vào bộ đếm sai theo IP của đăng nhập (`E-AUTH-12`); JWKS không kết nối được thì không cộng (`E-AUTH-21`).

**Xác minh SĐT của khách (`/auth/phone/*`).**

| Tình huống | Kết quả |
|---|---|
| SĐT chưa ai dùng | Gắn vào tài khoản, `phone_verified_at = now` |
| SĐT thuộc tài khoản khách khác **và** tài khoản hiện tại là tài khoản Google chưa có SĐT | **Gộp**: xóa tài khoản Google, chuyển `google_sub`/`google_email` sang chủ SĐT, **xóa mật khẩu của chủ SĐT** (`password_cleared=true`; từ nay đăng nhập bằng Google hoặc Quên mật khẩu), cấp lại JWT cho chủ SĐT |
| Chủ SĐT là Admin/nhân viên, bị khóa, hoặc đã có Google khác | `E-AUTH-18` |
| Tài khoản hiện tại đã có SĐT | `E-AUTH-17` |

### 11.3 Quản lý nhân viên – chỉ Admin (`Perm.STAFF_MANAGE`)

Trang `/admin/nhan-vien` (menu "Nhân viên"). Nhân viên gọi các route này → 403 `E-AUTH-2`. Các lệnh ghi này **không** bắt buộc `Idempotency-Key`. Phản hồi `StaffOut` = `{id, staff_code, full_name, username, is_active, created_at, last_login_at, active_sessions}`; phiên = `{id, created_at, expires_at, user_agent, ip_masked}`.

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/admin/staff` | Mã, họ tên, tên đăng nhập, trạng thái, lần đăng nhập gần nhất, số phiên đang mở |
| POST | `/admin/staff` `{full_name, password}` | Chỉ gửi họ tên và mật khẩu. Server sinh mã `NV%03d` (theo sequence, **không dùng lại**) và tên đăng nhập (tên cuối bỏ dấu + `.` + mã thường, ≤ 30 ký tự; `Nguyễn Văn An` → `an.nv007`). Client không gửi được `username` hay mã |
| PATCH | `/admin/staff/{id}` `{full_name?, is_active?}` | Khóa (`is_active=false`) thu hồi mọi phiên của nhân viên (`account_disabled`) |
| POST | `/admin/staff/{id}/password` `{password}` → 204 | Đặt lại mật khẩu: thu hồi mọi phiên (`password_changed`), xóa trạng thái khóa do nhập sai |
| GET | `/admin/staff/{id}/sessions` | Thời điểm, hạn, trình duyệt, IP (đã che) |
| DELETE | `/admin/staff/{id}/sessions/{sid}` | Đăng xuất từ xa một phiên (`revoked_by_admin`) |

Giao diện: nút **Tạo mật khẩu ngẫu nhiên**; sau khi tạo hiện mã + tên đăng nhập với nút **Sao chép tên đăng nhập** / **Sao chép cả mật khẩu** (mật khẩu không hiện lại sau khi rời trang); **Khóa** cần bấm hai lần ("Bấm lần nữa để khóa"), rồi **Mở khóa**; **Phiên đang mở (n)** liệt kê phiên với nút **Đăng xuất** từng phiên. Mọi thao tác ghi nhật ký (`staff.create`, `staff.update`, `staff.disable`, `staff.enable`, `staff.password_reset`, `auth.session_revoked`).

### 11.4 OTP và quên mật khẩu

- Luồng giao diện: `/quen-mat-khau` (nhập SĐT, nút **Gửi mã**) → `/quen-mat-khau/xac-minh` (6 ô, dán được; **Xác nhận**, **Gửi lại mã** sau 60 giây, **Đổi số**) → `/quen-mat-khau/dat-lai` (mật khẩu mới + nhập lại, **Đổi mật khẩu**; lỗi phiên hết hạn có nút **Làm lại từ đầu**) → `/dang-nhap`. Dùng cho mọi vai.
- Mã OTP: 6 số, server chỉ lưu `HMAC-SHA256` với `SECRET_KEY`, hạn **5 phút**, sai **5 lần** thì mã chết (`E-AUTH-15`), gửi mã mới thì mã cũ hết hiệu lực. Gửi lại sau **60 giây**; tối đa **5 mã/giờ/SĐT** và **20 mã/giờ/IP** (`E-AUTH-13`, 429, `retry_after` = thời gian chờ dài nhất).
- **Chống dò tài khoản:** SĐT chưa có tài khoản vẫn nhận 202 y hệt; xác minh với SĐT đó trả lỗi y hệt "mã sai/hết hạn".
- Đặt lại thành công: đổi mật khẩu, `token_version += 1` (JWT khách cũ hết hiệu lực), thu hồi mọi phiên Admin/nhân viên, xóa khóa, ghi `auth.password_reset_done`. `reset_token` sai hoặc hết hạn → `E-AUTH-16`.
- Mỗi lần yêu cầu mã ghi một dòng `otp_codes` (kể cả SĐT không có tài khoản, để trả y hệt); có khóa theo SĐT nên yêu cầu đồng thời chỉ phát một mã. Mã quá 24 giờ bị worker xóa.
- Gửi mã qua Zalo ZNS (job ARQ `send_zalo_otp`): **chưa làm**, client để `TODO(zalo-zns)`. Production thiếu cấu hình Zalo → quên mật khẩu trả `E-AUTH-23` (503) và đặt online tạm ngưng (như thiếu SePay).

### 11.5 Chế độ thử OTP (`OTP_TEST_MODE`)

Chỉ cho máy dev và link dev, khi chưa có Zalo.

| `OTP_TEST_MODE` | Mã OTP của **khách** (`booking_phone`, `phone_verify`, `password_reset`) | Mã `password_reset` của **Admin/nhân viên** |
|---|---|---|
| `true` | Có trong response (`test_otp`); giao diện hiện hộp vàng "Mã thử (chỉ link dev): 123456". SĐT không có tài khoản: `test_otp: null` | **Không** có trong response; chỉ ghi log server mức cảnh báo (SĐT đã che; xem bằng `docker logs`), để người lạ trên link dev công khai không chiếm được Admin |
| `false` (mặc định) | Không bao giờ có trong response hay log | Như khách |

`OTP_TEST_MODE=true` cùng `ENV=production` → API **không khởi động**.

### 11.6 Mã lỗi (T-013)

| Code | HTTP | Thông điệp / khi nào |
|---|---|---|
| E-AUTH-10 | 401 | "Số điện thoại, tên đăng nhập hoặc mật khẩu không đúng." (cả khi không có tài khoản) |
| E-AUTH-11 | 423 | "Bạn đã nhập sai 5 lần. Vui lòng thử lại sau 15 phút." + `retry_after` (số lấy từ cấu hình) |
| E-AUTH-12 | 429 | "Có quá nhiều lần đăng nhập sai từ mạng này…" + `retry_after` |
| E-AUTH-13 | 429 | "Bạn đã yêu cầu gửi mã quá nhiều lần. Vui lòng thử lại sau." + `retry_after` |
| E-AUTH-14 | 400 | "Mã xác minh không đúng." + `attempts_left` |
| E-AUTH-15 | 400 | "Mã xác minh đã hết hạn hoặc không còn hiệu lực. Vui lòng gửi lại mã." |
| E-AUTH-16 | 400 | "Phiên đặt lại mật khẩu đã hết hạn. Vui lòng làm lại từ đầu." |
| E-AUTH-17 | 409 | "Tài khoản đã có số điện thoại." |
| E-AUTH-18 | 409 | "Số điện thoại không dùng được." |
| E-AUTH-19 | 404 | "Chưa bật đăng nhập bằng Google." |
| E-AUTH-20 | 401 | "Không đăng nhập được bằng Google. Vui lòng thử lại." (token sai, hoặc tài khoản Google của Admin/nhân viên) |
| E-AUTH-21 | 503 | "Chưa kết nối được Google. Vui lòng thử lại sau." |
| E-AUTH-22 | 409 | "Số điện thoại đã được sử dụng." (đăng ký) |
| E-AUTH-23 | 503 | "Chức năng quên mật khẩu đang tạm ngưng. Vui lòng liên hệ chủ sân." |
| E-AUTH-24 | 503 | "Chức năng xác minh số điện thoại đang tạm ngưng. Vui lòng liên hệ chủ sân." (`/auth/phone/request` khi không có kênh OTP; quên mật khẩu dùng `E-AUTH-23`) |
| E-STAFF-1 | 404 | "Không tìm thấy nhân viên." (id không phải nhân viên cũng báo vậy) |
| E-STAFF-2 | 404 | "Không tìm thấy phiên đăng nhập." |
| E-WEB-8 | 403 | "Vui lòng xác minh số điện thoại trước khi đặt sân." (mục 10.2) |

Mật khẩu yếu → 422 `weak_password` với đúng câu "Mật khẩu cần … ." (không có tiền tố "Value error"; dạng `detail` mảng mặc định của FastAPI). Đăng ký hàng loạt: quá 10 lần/giờ/IP → `E-SEC-5`. `E-AUTH-3…6` để dành cho T-010; `E-AUTH-7` dùng ở T-012 (mục 10.7).

### 11.7 Nhật ký (T-013)

Dùng `audit_log` sẵn có. Action mới: `auth.login_success`, `auth.login_locked`, `auth.logout`, `auth.session_revoked`, `auth.password_reset_requested`, `auth.password_reset_done`, `auth.password_reset_cli`, `auth.phone_verified`, `auth.account_merged`, `staff.create`, `staff.update`, `staff.disable`, `staff.enable`, `staff.password_reset`. Mã OTP, token đặt lại, token phiên không bao giờ ở dạng rõ trong DB, log, nhật ký hay response (ngoại lệ duy nhất: mục 11.5).

### 11.8 Lệnh cứu Admin trên server

Khi Admin quên mật khẩu và chưa có Zalo, chạy trên VPS, trong thư mục compose của môi trường đó (`/opt/caulong-dev` hoặc `/opt/caulong`):

```bash
docker compose -p caulong-dev exec api python -m app.scripts.reset_admin_password   # link dev
docker compose -p caulong     exec api python -m app.scripts.reset_admin_password   # production
```

Lệnh hỏi mật khẩu mới hai lần bằng `getpass` (không hiện trên màn hình, **không** nhận qua tham số dòng lệnh), áp quy tắc mật khẩu ở mục 11.2. Có đúng một Admin thì dùng luôn; nhiều Admin thì hỏi SĐT. Sau đó `token_version += 1`, thu hồi mọi phiên, xóa khóa, ghi `auth.password_reset_cli` (`actor_type=system`). Lệnh in SĐT đã che, không bao giờ in mật khẩu. Chưa có Admin nào thì báo chạy `python -m app.scripts.seed` trước.

### 11.9 Chuyển dữ liệu khi lên T-013 (migration)

Một migration (`3c30569e12af`) nối sau `cc9af0a8c694`. Các bước, theo thứ tự:

1. Chuẩn hóa `users.phone` (không hợp lệ → NULL; trùng → giữ id nhỏ nhất, còn lại NULL).
2. Admin chưa có SĐT → gán `FIRST_ADMIN_PHONE`. Nếu SĐT đó đã thuộc **một Admin** (chạy lên lại sau downgrade) thì bỏ qua bước gán. **Thiếu biến, sai định dạng, hoặc SĐT thuộc người không phải Admin → migration dừng với thông báo nêu tên biến (không in giá trị), không đổi gì**, API không lên. Nhiều Admin chưa có SĐT: chỉ Admin id nhỏ nhất được gán.
3. Khách không có SĐT được sinh `username`.
4. Nhân viên hiện có nhận `staff_code` `NV001`…; "Tài khoản tại máy" hiện tại thành **`NV001` / `nv001`**, mật khẩu giữ nguyên.
5. `users.email` thành nullable, **giữ dữ liệu, không xóa cột**.
6. `phone_verified_at` để NULL cho SĐT đã có của khách (Admin/nhân viên coi như đã xác minh).

Mật khẩu và SĐT đã có của Admin **không bao giờ bị ghi đè** bởi migration hay seed. Downgrade xóa bảng/cột mới và trả `email` NOT NULL (dòng thiếu email → `user{id}@khong-co-email.invalid`).

## 12. Hội viên, tài khoản hội viên, khu hội viên (T-015, T-016)

> **Nguồn:** phần quản trị và tài khoản hội viên lấy từ code `dev` (PR #21, merge `c288d08`). Người dùng chốt 30/10: "cứ bám theo PR mới" – ARCHITECT ADR-009 mục "Sửa đổi 30/10". Mục 12.6 (khu hội viên, T-016) đối chiếu với `be/T-016-khu-hoi-vien` @ `fd8db2f` (cục bộ, **chưa vào `dev`**; giao diện chưa đối chiếu). Nếu code lệch tài liệu này, code đúng.
> Chỗ PR #21 khác SRS Hội viên v0.2 được liệt kê ở `board/ref/lech-SRS-hoi-vien.md` (để BA sửa SRS), không sửa code.

### 12.1 Khái niệm

| Khái niệm | Nghĩa trong code |
|---|---|
| Hồ sơ khách (`customer`) | Một bảng, hai loại (`kind`): `member` (hội viên, có Mã HV) và `temp` (hồ sơ tạm). SĐT duy nhất trong cả bảng |
| Mã HV | `HV` + 4 số (`HV0031`), tuần tự, không dùng lại. Quá `HV9999` → 409 `E-MEM-4` |
| Hồ sơ tạm | Họ tên, giới tính, SĐT. Sửa được **họ tên và giới tính**; SĐT và các ô khác không |
| Hạng (= Trình độ) | 8 bậc, thấp → cao: `Yếu · Trung bình yếu · Trung bình - · Trung bình · Trung bình + · Khá · Bán chuyên · Chuyên nghiệp`. Có thể **chưa xếp hạng** (`null`) |
| Trạng thái | `Hoạt động` / `Ngừng`. Ngừng **khóa tài khoản web** cùng SĐT (xem 12.5) và hội viên Ngừng **không chọn được khi đặt sân tại quầy** (409 `E-MEM-2`) |
| Vợt đang dùng | **Chuỗi** (tên vợt), không phải khóa ngoại. Lấy từ danh mục vợt (12.4); tên chưa có thì tự thêm vào danh mục |
| `ref` | Mã định danh hồ sơ trong URL: Mã HV với hội viên, mã UUID (`public_id`) với hồ sơ tạm. Không lộ `id` nội bộ |
| Số lần đặt | Số **booking** (quầy + online, mọi trạng thái thanh toán, kể cả Không thu được) của hồ sơ. **Chưa tính vé sự kiện.** Booking online đặt trước khi có hồ sơ lưu theo `phone:<SĐT>` và vẫn được tính |

### 12.2 Quyền

| Quyền | Admin | Nhân viên | Dùng cho |
|---|:-:|:-:|---|
| `member.search` (`Perm.MEMBER_SEARCH`) | ✔ | ✔ | `GET /members/search` (ô Chọn hội viên khi đặt quầy) |
| `member.manage` (`Perm.MEMBER_MANAGE`) | ✔ | ✔ | Màn Hội viên: xem danh sách, chi tiết, thêm, sửa, tạo hồ sơ tạm, nâng hồ sơ tạm; đọc danh mục vợt |
| `member.status` (`Perm.MEMBER_STATUS`) | ✔ | | Đổi **Trạng thái** Hoạt động / Ngừng |
| `racket.manage` (`Perm.RACKET_MANAGE`) | ✔ | | Thêm, sửa tên, ẩn / hiện, xóa vợt trong danh mục |

- Nhân viên đổi Trạng thái → 403 `E-AUTH-2`. (Trong code **chỉ Trạng thái bị khóa với nhân viên; Hạng thì nhân viên vẫn sửa được** – lệch spec T-015, xem `board/ref/lech-SRS-hoi-vien.md`.)
- Khách hoặc chưa đăng nhập → 401 `E-AUTH-1` / 403 `E-AUTH-2`.

### 12.3 API quản trị – tiền tố `/api/v1/members`

Lệnh ghi cần `Origin` đúng và `Idempotency-Key` (mục 1). Lỗi dạng `{detail:{code, message, ...}}`. **SĐT trả đầy đủ** (`phone`), không che.

| Method | Đường dẫn | Quyền | Ghi chú |
|---|---|---|---|
| GET | `/members/search?q=` | `member.search` | Tối đa 20 hội viên `{ref, member_code, name, phone, tier, is_active}`; `q` 1–50 ký tự, tìm theo mã / tên / SĐT (≥ 3 chữ số), gồm cả Ngừng. Rate limit 60/phút/người |
| GET | `/members?q=&kind=&status=&tier=&racket=&sort=&page=1&size=20` | `member.manage` | Danh sách |
| GET | `/members/next-code` | `member.manage` | `{member_code}` Mã HV dự kiến (chỉ để hiển thị; mã thật cấp lúc lưu) |
| POST | `/members` → 201 | `member.manage` | Thêm hội viên (hoặc nâng hồ sơ tạm) |
| POST | `/members/temp` → 201 | `member.manage` | Tạo hồ sơ tạm |
| GET | `/members/{ref}` | `member.manage` | Chi tiết; **ghi nhật ký `member.view`** mỗi lần xem |
| PATCH | `/members/{ref}` | `member.manage` | Sửa hội viên hoặc hồ sơ tạm |

**Danh sách** `GET /members`:

- `kind`: `member` \| `temp` (bỏ trống = cả hai). `status`: `active` \| `inactive`. `tier`: một trong 8 bậc, hoặc `none` (= chưa xếp hạng). `racket`: tên vợt (không phân biệt hoa thường). `q` tối đa 50 ký tự.
- `sort`: bỏ trống = **hồ sơ thêm mới nhất trước** (hội viên và hồ sơ tạm xếp chung; hồ sơ tạm được nâng giữ ngày tạo gốc). `bookings` hoặc `bookings_desc` = Số lần đặt giảm dần; `bookings_asc` = tăng dần; bằng nhau thì theo thứ tự mặc định.
- `size` 1–100 (mặc định 20).
- Trả `{items[], total, page, size, counts:{all, member, temp}, can:{edit_status, manage_rackets}}`. `counts` áp **mọi bộ lọc trừ `kind`**; `total` theo `kind`. `can` cho giao diện khóa ô theo quyền.
- Mỗi `items[]`: `{ref, kind, member_code, full_name, phone, gender: "male"|"female"|null, tier, racket, is_active, bookings, created_at}`. Hồ sơ tạm: `member_code`, `tier`, `racket` là `null`.

**Chi tiết** `GET /members/{ref}`: như một dòng, thêm `note`, `total_minutes` (tổng **phút** đã đặt), `recent_bookings[]` (5 booking gần nhất theo giờ chơi: `{code, play_date, start_time, end_time, resource_name, amount}`) và `can`. Không tìm thấy → 404 `E-NOT-FOUND`.

**Thêm** `POST /members` body `{full_name, phone, gender?, tier?, racket?, upgrade_temp?}`:

- `tier` bỏ trống = chưa xếp hạng. `racket` là tên vợt.
- Hội viên mới ở trạng thái Hoạt động; **tạo luôn tài khoản web** cho SĐT đó nếu chưa có (12.5).
- SĐT đã thuộc hội viên → 409 `E-018`.
- SĐT đang là hồ sơ tạm: không có `upgrade_temp` → 409 `E-MEM-1` (kèm `ref`, `full_name`, `bookings`, `next_code` để giao diện hỏi "Nâng hồ sơ tạm thành hội viên?"); gửi `upgrade_temp: true` → **nâng chính hồ sơ đó** thành hội viên (cùng dòng, giữ lịch sử, ghi `member.promote`). Nếu hồ sơ vừa thành hội viên ở máy khác → 409 `E-MEM-3`.

**Sửa** `PATCH /members/{ref}`: chỉ gửi ô muốn đổi, trong `full_name, gender, tier, racket, is_active`. **Không đổi được SĐT.** `tier: null` = bỏ xếp hạng. Hồ sơ tạm chỉ nhận `full_name`, `gender` (ô khác → 422 `E-MEM-6`). Đổi `is_active` khi không có `member.status` → 403 `E-AUTH-2`. Hội viên Ngừng → khóa tài khoản web; Hoạt động lại → mở.
Không có khóa lạc quan (`version`) ở lệnh sửa của quầy: hai máy cùng sửa thì máy lưu sau thắng.

**Hồ sơ tạm** `POST /members/temp` body `{full_name, phone, gender?}`. SĐT trùng hội viên → 409 `E-018`; trùng hồ sơ tạm → 409 `E-MEM-1`.

Kiểm đầu vào: Họ tên 1–100 ký tự (gộp khoảng trắng), thiếu → 422 `E-001`; SĐT sai → 422 `E-002`. Hai máy lưu cùng lúc đụng ràng buộc → 409 `E-012`.

### 12.4 Danh mục vợt – tiền tố `/api/v1/rackets`

| Method | Đường dẫn | Quyền | Ghi chú |
|---|---|---|---|
| GET | `/rackets?all=` | `member.manage` (**T-016:** thêm hội viên có hồ sơ) | Danh sách **phẳng** `{id, name, is_active, sort_order, member_count}`, theo `sort_order` rồi tên. Mặc định chỉ vợt đang dùng; `all=1` (chỉ Admin) gồm cả vợt ẩn |
| POST | `/rackets` → 201 | `racket.manage` | Body `{name, sort_order?}`. Trùng tên (không phân biệt hoa thường, gộp khoảng trắng) → 409 `E-MEM-5`. Ghi `racket.create` |
| PATCH | `/rackets/{id}` | `racket.manage` | Sửa `name`, `is_active` (ẩn / hiện), `sort_order`. Hồ sơ đang dùng vợt giữ tên cũ. Ghi `racket.update` |
| DELETE | `/rackets/{id}` → 204 | `racket.manage` | Xóa hẳn; hồ sơ đang ghi vợt này giữ nguyên tên |

Lưu hội viên với một tên vợt chưa có trong danh mục thì tên đó **tự thêm vào danh mục**. Không gom theo hãng.

### 12.5 Tài khoản hội viên do sân tạo

Thêm hội viên (hoặc nâng hồ sơ tạm) thì hệ thống tạo luôn **tài khoản web** vai `member` cho SĐT đó, nếu SĐT chưa có tài khoản (đã có thì **không đụng**, không đổi mật khẩu).

| | |
|---|---|
| Vai | `member` (trước là `customer`). Tên cũ vẫn được ghi ở `audit_log.actor_type` (`customer`) để giữ dữ liệu nhật ký |
| Đăng nhập | SĐT + mật khẩu ban đầu **= chính SĐT** |
| Bắt đổi mật khẩu | Cờ `must_change_password`. Trước khi đổi, mọi API khách trả 403 `E-AUTH-25`; chỉ `GET /auth/me` và `POST /auth/password/change` dùng được. Giao diện chuyển sang `/doi-mat-khau` |
| Hạn | `MEMBER_INITIAL_PASSWORD_DAYS` (mặc định **3 ngày**) từ lúc sân tạo tài khoản. Quá hạn mà chưa đổi → đăng nhập đúng mật khẩu vẫn **không** cấp phiên, 403 `E-AUTH-30`; phải bấm Quên mật khẩu (OTP). Đặt lại xong thì bỏ cờ |
| Ngừng | Hội viên Ngừng → tài khoản bị khóa và JWT cũ hết hiệu lực; Hoạt động lại → mở |

`POST /auth/password/change` (khách đăng nhập, cần Origin): body `{new_password, current_password?}`. Đang bị bắt đổi lần đầu thì **không cần** `current_password`. Xong: bỏ cờ, JWT cũ hết hiệu lực, cấp cookie mới. Lỗi: 400 `E-AUTH-28` (mật khẩu hiện tại sai), 422 `weak_password`, 422 `E-AUTH-26` (mật khẩu trùng SĐT; chỉ mật khẩu ban đầu mới được trùng SĐT).

Khác với T-013: `POST /auth/register` và `E-AUTH-22` giờ dùng chung một lỗi cho **mọi** SĐT đã có tài khoản (kể cả tài khoản hội viên sân tạo), kèm `phone` để điền link Quên mật khẩu.
`UserOut` thêm `must_change_password`; `kind` của kết quả đăng nhập khách là `"member"` (không còn `"customer"`).

**Thẻ hội viên của chính khách:** `GET /me/member` (SĐT lấy từ tài khoản, không nhận tham số) → `{member_code, full_name, tier, is_active, gender, racket, created_at, bookings, total_minutes}`; `GET /me/member/bookings?page=` → `{items[], total, page, size:10}`, mới nhất trước. Lỗi: 401, 403 `E-AUTH-25`, 403 `E-AUTH-29` (SĐT chưa xác minh OTP), 404 (không có hồ sơ **hội viên** cùng SĐT; hồ sơ tạm không tính).
Điều kiện xem (`can_view_member_card`): tài khoản do sân tạo, **hoặc** SĐT đã xác minh bằng OTP. Tài khoản tự đăng ký (`/auth/register`, không OTP) bằng SĐT của hội viên phải xác minh SĐT trước. Gọi `POST /auth/phone/verify` đúng SĐT đang gắn vào tài khoản (chưa xác minh) thì xác minh tại chỗ.

### 12.6 Khu hội viên trên web – `/api/v1/member-area` (T-016, chưa vào `dev`)

Dành cho khách đã đăng nhập **và là hội viên**: hồ sơ của tài khoản là hồ sơ `kind=member` **cùng SĐT**, với điều kiện `can_view_member_card` (12.5). Không có cột liên kết riêng. Mọi API lấy hồ sơ **theo phiên**, không nhận id trên URL (trừ ảnh). Phiên Admin / nhân viên → 401 `E-AUTH-1`. `GET /auth/me` và các kết quả đăng nhập thêm `is_member: bool`.

| Method | Đường dẫn | Ghi chú |
|---|---|---|
| GET | `/member-area/me` | Hồ sơ của tôi. `Cache-Control: no-store` |
| PUT | `/member-area/me` | Lưu thay đổi. Cần Origin. Trả như GET |
| PUT | `/member-area/me/avatar` | Multipart: `file` (JPG / PNG / WebP ≤ `AVATAR_MAX_BYTES`), `crop_x`, `crop_y`, `crop_size` → `{avatar_url}`. 20 lần/phút/người. **Không** tăng `version` |
| DELETE | `/member-area/me/avatar` → 204 | Chưa có ảnh vẫn 204 |
| GET | `/member-area/avatars/{customer_id}?v=` | Ảnh, công khai. `image/webp`, `ETag`, `Cache-Control: public, max-age=31536000, immutable`, `nosniff`, CSP `default-src 'none'; sandbox`; 304 theo `If-None-Match` |

`GET /member-area/me` → `{member_code, full_name, short_name, nickname, email, phone, joined_at, tier, racket, show_on_records, avatar_url, record_kmh, version}`:

- `phone` và `email` đầy đủ (chỉ chính chủ thấy). `short_name` = từ cuối của Họ tên. `joined_at` = ngày tạo hồ sơ hội viên (giờ VN).
- `tier`: một trong 8 bậc hoặc `null` (chưa xếp hạng). `racket`: tên vợt hoặc `null`. `avatar_url` đã có `?v=`, `null` nếu chưa có ảnh. `record_kmh` luôn `null` ở đợt 1.

`PUT /member-area/me` body `{full_name, nickname, email, tier, racket, show_on_records, version}` (chuỗi rỗng = `null`; trường lạ → 422):

| Ô | Quy tắc |
|---|---|
| `full_name` | 1–100 ký tự (E-HV-1) |
| `nickname` | ≤ 20 ký tự (E-HV-1). Được trùng người khác |
| `email` | Tùy chọn, đúng định dạng (E-HV-10), không trùng hội viên khác, không phân biệt hoa thường (E-HV-11). Chỉ để liên hệ: **không** dùng để đăng nhập, quên mật khẩu hay khớp Google; không gửi mail xác minh |
| `tier` | Bắt buộc là một trong 8 bậc (E-HV-1). Đang `null` thì được gửi `null` để giữ; đã có hạng thì **không** đổi về `null` |
| `racket` | Tên vợt; chưa có trong danh mục thì tự thêm; rỗng = bỏ chọn. Lỗi tên vợt nằm trong `fields` |
| `show_on_records` | Mặc định `false` với hội viên mới |
| `version` | Lấy từ GET, gửi lại. Hồ sơ đã được sửa nơi khác → 409 `E-HV-12`, không ghi đè |

Lỗi nhiều ô cùng lúc → 422 với `detail.fields[{field, code, message}]` (`field` ∈ `full_name | nickname | email | tier | racket`); có lỗi thì **không lưu ô nào**. Không đổi gì → trả hồ sơ, không ghi, không tăng `version`.
Chỉ hội viên **tự sửa** mới tăng `version`; lệnh sửa của quầy (12.3) thì không, nên quầy sửa xong hội viên không nhận `E-HV-12`.

Đổi **Họ tên** còn: cập nhật `users.full_name`, và đổi tên khách trên booking, vé, lượt thanh toán của hồ sơ (kể cả booking cũ); snapshot hạng lúc đặt giữ nguyên.

Lỗi chung: 401 `E-AUTH-1` · 403 `E-AUTH-25` (chưa đổi mật khẩu ban đầu) · 403 `E-AUTH-30` (mật khẩu ban đầu hết hạn) · 403 `E-HV-8` "Bạn chưa là hội viên." (không có hồ sơ hội viên cùng SĐT, hoặc SĐT chưa xác minh) · 413 `E-SEC-6` (thân gửi lên vượt khoảng 5 MB + 64 KB).

**Ảnh đại diện (xử lý ở server).** Kiểm magic bytes (chỉ JPEG, PNG, WebP); Pillow giải mã; **xoay theo EXIF trước khi cắt** (`crop_*` tính theo pixel của ảnh đã xoay, đúng như trình duyệt hiển thị); cắt vuông, thu về tối đa 512 px, mã hóa lại WebP chất lượng 85, không còn metadata; ảnh lớn hơn 40 MP bị từ chối. Sai định dạng, quá dung lượng, quá cỡ hoặc vùng cắt vượt ảnh → 422 `E-HV-13`. Ảnh lưu trong Postgres (bảng `customer_avatar`).

### 12.7 Mã lỗi

| Mã | HTTP | Khi nào |
|---|---|---|
| `E-001` | 422 | Thiếu hoặc quá dài (Họ tên, SĐT, tên vợt) |
| `E-002` | 422 | SĐT sai định dạng |
| `E-018` | 409 | SĐT đã là của hội viên |
| `E-MEM-1` | 409 | SĐT đã có hồ sơ tạm (kèm dữ liệu để hỏi nâng) |
| `E-MEM-2` | 409 | Hội viên Ngừng, không chọn khi đặt quầy |
| `E-MEM-3` | 409 | Nâng hồ sơ tạm nhưng hồ sơ vừa thành hội viên |
| `E-MEM-4` | 409 | Hết Mã HV (`HV9999`) |
| `E-MEM-5` | 409 | Tên vợt trùng trong danh mục |
| `E-MEM-6` | 422 | Hồ sơ tạm chỉ sửa họ tên, giới tính |
| `E-012` | 409 | Dữ liệu vừa được cập nhật ở máy khác (đụng ràng buộc duy nhất) |
| `E-NOT-FOUND` | 404 | Không có hồ sơ hoặc vợt |
| `E-AUTH-25` | 403 | Chưa đổi mật khẩu ban đầu |
| `E-AUTH-26` | 422 | Mật khẩu mới trùng SĐT |
| `E-AUTH-28` | 400 | Mật khẩu hiện tại sai |
| `E-AUTH-29` | 403 | Cần xác minh SĐT để xem thẻ hội viên |
| `E-AUTH-30` | 403 | Mật khẩu ban đầu hết hạn (phải Quên mật khẩu) |
| `E-HV-1` | 422 | (T-016) Họ tên, biệt danh, trình độ thiếu hoặc quá dài |
| `E-HV-8` | 403 | (T-016) Chưa là hội viên |
| `E-HV-10` | 422 | (T-016) "Email không hợp lệ." |
| `E-HV-11` | 422 | (T-016) "Email đã được sử dụng." |
| `E-HV-12` | 409 | (T-016) Hồ sơ vừa được sửa ở nơi khác (khóa lạc quan `version`) |
| `E-HV-13` | 422 | (T-016) Ảnh sai định dạng, quá dung lượng, quá cỡ, vùng cắt sai |

Mã `E-HV-2…7, 9` của spec T-015 **không có trong code** (PR #21 dùng `E-MEM-*`, `E-001`, `E-002`, `E-018`); `E-HV-7` (SĐT gắn tài khoản khác) đã bỏ cùng quy tắc "quầy đổi SĐT".

### 12.8 Nhật ký thao tác

| `action` | Khi nào |
|---|---|
| `member.create` | Thêm hội viên (`detail.tier`) |
| `member.promote` | Nâng hồ sơ tạm thành hội viên (`tier`, `bookings`, `ref`) |
| `member.update` / `member.temp.update` | Sửa hội viên / hồ sơ tạm (`detail.fields` = các ô đã đổi, kèm `tier`, `is_active` nếu đổi) |
| `member.temp.create` | Tạo hồ sơ tạm (cả khi đặt quầy kèm hồ sơ tạm mới) |
| `member.view` | Xem chi tiết (ghi cả khi chỉ xem) |
| `racket.create` / `racket.update` | Thêm / sửa vợt trong danh mục |
| `member.self_update` (T-016) | Hội viên tự sửa: `detail.changes = {ô: [trước, sau]}` (email che dạng `m***@domain`), `renamed_items` khi đổi tên. Người làm: "Hội viên (tự sửa) · HV…". Không đổi gì thì không ghi |
| `member.avatar_update` / `member.avatar_delete` (T-016) | Đổi / xóa ảnh |
| `auth.password_changed` | Đổi mật khẩu |

### 12.9 Biến môi trường và gói mới

| Biến | Mặc định | Ghi chú |
|---|---|---|
| `MEMBER_INITIAL_PASSWORD_DAYS` | `3` | Hạn đổi mật khẩu ban đầu của tài khoản hội viên sân tạo |
| `AVATAR_MAX_BYTES` (T-016) | `5242880` (5 MB) | Dung lượng tối đa tệp ảnh đại diện. Đường tải nhận thân tới khoảng 5,06 MB, nên Caddy / Next rewrite phía trước không được chặn cỡ này |

T-016 thêm gói Python `pillow` và `python-multipart`: phải **build lại image** backend.

### 12.10 Chuyển dữ liệu (migration)

- `a3d81f5c2b6e` (PR #21, trên `dev`): đổi vai `customer` → `member` trong `users`; thêm `must_change_password`, `member_account_at`; bảng `racket`; cột `customer.gender`, `racket` (chuỗi), `public_id`; hạng 8 bậc: hạng ưu đãi cũ Vàng / Bạc / Đồng đổi hết thành `NULL` (chưa xếp hạng); cột `member_tier` ở các bảng ảnh chụp của booking engine nới 20 ký tự; index đếm lượt theo `customer_ref`. Script `python -m app.scripts.backfill_member_accounts` tạo tài khoản cho hội viên đã có.
- `dad220bfc992` (T-016, chưa vào `dev`): `customer.nickname` (≤ 20), `email` (≤ 254, duy nhất theo `lower(email)`), `show_on_records` (mặc định `false`), `version`; bảng `customer_avatar`. Đảo ngược được.
