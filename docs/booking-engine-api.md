# API booking engine và nền bảo mật (T-005, T-006)

Tài liệu này dành cho người viết code gọi API đặt sân: cần gửi gì, nhận lỗi gì, ai được gọi gì.
Nguồn: code nhánh `be/T-005-nen-tang` (đã vào `dev`) và `be/T-006-dat-san`; ADR-003, ADR-004; spec T-005, T-006.
Nếu code và tài liệu lệch nhau, code đúng – báo DOCS-STEWARD sửa. OpenAPI sống: `/docs` của API (tắt ở production).

> Phạm vi: cấu hình sân và bảng giá (T-005); lịch, đặt sân tại quầy, sự kiện và vé, thu tiền mặt, Không thu được, Lịch sử giao dịch (T-006).
> **Chưa có:** thu tiền chuyển khoản QR tại quầy (T-007), khách đặt online và giữ chỗ (T-008), đăng nhập mới, báo cáo, màn Hội viên đầy đủ.
> **Luồng đặt sân cũ đã bị gỡ** trong T-006, xem mục 8.

## 1. Quy tắc chung cho mọi request ghi

| Quy tắc | Chi tiết |
|---|---|
| Xác thực | Cookie phiên như các API cũ (đăng nhập qua `POST /api/v1/auth/login`) |
| `Origin` | Request `POST/PUT/PATCH/DELETE` mang cookie phải có `Origin` (hoặc `Referer`) thuộc `ALLOWED_ORIGINS`, nếu không → 403 `E-SEC-1`. Thiếu cả hai cũng bị chặn. Trình duyệt tự gửi; code phía server Next gọi API phải tự thêm header `Origin` |
| Body | JSON, tối đa 64 KB (`MAX_BODY_BYTES`) → quá thì 413 `E-SEC-6`. Trường lạ bị từ chối (422): server tự tính giá, tiền, mã, trạng thái thanh toán, tên khách, người thao tác, nên **đừng gửi** `amount`, `price`, `code`, `payment_status`, `customer_name`, `created_by` |
| `Idempotency-Key` | Bắt buộc cho mọi `POST/PUT/PATCH/DELETE` của booking engine và `/front-desk/**`, **trừ `POST /booking/quote`** |
| Rate limit | Toàn API `RATE_LIMIT_PER_MINUTE` (mặc định 120) lượt/phút/IP. Riêng 60 lượt/phút/người cho `POST /booking/quote`, `GET /booking/search`, `GET /members/search`. Vượt → 429 `E-SEC-5` + header `Retry-After` (giây) |
| Nhật ký | Mọi lệnh ghi thành công ghi đúng 1 dòng `audit_log` (chỉ thêm, không sửa; xóa chỉ dòng quá 12 tháng). Ngoại lệ: đặt quầy kèm hồ sơ tạm **mới** ghi 2 dòng (`member.temp.create` và `booking.counter.create`). Thao tác bị chặn không ghi |
| Dữ liệu cá nhân | Không response nào trả SĐT đầy đủ, `id` nội bộ hay `customer_ref`. SĐT luôn che dạng `0987 xxx 321` (`phone_masked`) |

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
| E-AUTH-1 | 401 | Chưa đăng nhập |
| E-AUTH-2 | 403 | Đăng nhập rồi nhưng thiếu quyền. Cũng dùng khi đặt tại quầy cho ngày khác hôm nay (kể cả Admin: ngày sau chỉ Đặt sự kiện) |
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
| E-BOOK-1 | 422 | Ngày sau "hết tháng sau" (lịch, sự kiện) |
| E-BOOK-2 | 422 | Sân của sự kiện không liền nhau |
| E-PAY-0 | 422 | Thu chuyển khoản tại quầy – chưa hỗ trợ (chờ T-007) |
| E-PAY-1 | 422 | Đánh dấu Không thu được với booking online, hoặc chưa tới giờ chơi |

Thông báo thành công (E-005, E-006, E-008, E-011, E-022, E-026) không có trong API: giao diện tự dựng từ response.

## 3. Quyền

Quyền khai báo tập trung ở `backend/app/core/permissions.py`. Router dùng `Depends(require(Perm.X))`,
**không so vai trực tiếp**. Vai hiện có: `admin` = Admin (chủ sân, có mọi quyền), `staff` = Tài khoản tại máy, `customer` = khách (chưa có quyền booking nào).

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
| GET | `/api/v1/members/search?q=` | Tối đa 20 hội viên `{ref, member_code, name, phone_masked, tier, is_active}`; tìm theo mã, tên hoặc SĐT (≥ 3 chữ số), gồm cả hội viên Ngừng |
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
  booking → `payment_status, customer_name, phone_masked, source`; sự kiện → `name, taken, capacity, is_full, unpaid_tickets`; giữ chỗ → `expires_at` (`code` là `null`).
- `unpaid_count`: số booking + vé Chưa thanh toán của **ngày đang xem**.
- `can`: `{counter_book, create_session}` – theo quyền của người đang đăng nhập.
- Xem được ngày đã qua (chỉ xem) đến hết tháng sau; xa hơn → 422 `E-BOOK-1`.

### Booking và vé (`ItemOut`)

`{kind: booking|ticket, code, version, source, customer, schedule, payment, note?, created_by, created_at, actions[], price_breakdown[]}`:

- `customer`: `{name, phone_masked, profile_label, kind, member_code, tier}`.
- `schedule`: `{resource_codes[], resource_names[], play_date, start_time, end_time, session?}`.
- `payment`: `{amount, payment_status, payment_method?, paid_at?, collected_by?, uncollectible_reason?, marked_by?, marked_at?}`.
- `payment_status`: `unpaid` → `paid` hoặc `unpaid` → `uncollectible`. Hai trạng thái cuối **không đổi** (không hủy, không hoàn tiền).
- `actions[]`: chỉ gồm thao tác được phép **lúc này** và người đang đăng nhập có quyền (`collect`, `uncollectible`).
- `price_breakdown[]`: `{start_time, end_time, band, label, price}` – giá từng khung chốt lúc đặt (vé: mảng rỗng).
- Gửi `collect`/`uncollectible` với `version` cũ hoặc khi đã đổi trạng thái → 409 `E-012`, không ghi đè.

### Sự kiện (`SessionOut`)

`{code, name, play_date, start_time, end_time, resources[], ticket_price, capacity, taken, is_full, status, created_by, created_at, version, tickets[], active_holds[], can}`:

- `tickets[]` (mới nhất trước): `{code, customer_name, phone_masked, source, payment_status, amount, created_at}`. Mã vé `{mã sự kiện}-Vnn`.
- `taken` = số vé (mọi trạng thái) + chỗ giữ online còn hạn. Đăng ký vé khóa dòng sự kiện nên 20 request tranh chỗ cuối chỉ 1 thành công, còn lại `E-024`.
- `active_holds[]`: `{seats, expires_at}`. `can`: `{register, delete}`.
- Xóa sự kiện chỉ khi chưa có vé và chưa có chỗ giữ (xóa mềm, nhả khung); ngược lại 409 `E-023`.

### Quy tắc cần nhớ

- Đặt tại quầy: **một sân, hôm nay**; ngày khác hoặc nhiều sân → 403/422 ngay cả khi giao diện bị sửa. Ngày sau và nhiều sân chỉ qua "Tạo sự kiện" (Admin).
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

Rate limit dùng Redis. Redis lỗi thì cho qua và ghi log (không chặn người dùng).

**Đã bỏ** (T-006): `OPEN_TIME`, `CLOSE_TIME`, `SLOT_MINUTES`, `MIN_BOOKING_MINUTES`, `MAX_ADVANCE_DAYS`, `HOLD_MINUTES`.
Giờ mở cửa, cao điểm, giá theo từng sân trong booking engine; thời gian giữ chỗ nằm trong `tenant.settings`. Còn dòng cũ trong `.env` thì vô hại (bị bỏ qua).

## 7. Worker (ARQ)

Chạy bằng `arq app.workers.worker.WorkerSettings`.

| Job | Chu kỳ | Việc |
|---|---|---|
| `publish_booking_outbox` | mỗi 2 giây | Đọc outbox của engine, phát sự kiện nội bộ (vd. `booking.created`) |
| `expire_holds` | mỗi 30 giây | Giữ chỗ quá `expires_at` → hết hạn, nhả khung. Giữ chỗ quá hạn không hiện trên lịch và không chặn đặt dù job chưa chạy |
| `purge_audit_log` | hằng ngày 03:15 | Xóa dòng nhật ký quá 12 tháng |
| `purge_idempotency_keys` | mỗi giờ (phút 5) | Xóa key quá 24 giờ |

Job `expire_pending_bookings` của luồng cũ đã bỏ.

## 8. Luồng đặt sân cũ đã gỡ (T-006)

Các route sau **trả 404**: `/bookings*`, `/admin/bookings*` (kể cả `/payments`), `/courts`, `/admin/courts*`, `/venue/config`, `/price-rules`, `/admin/price-rules*`.
Module `bookings`, `courts`, `payments` đã xóa khỏi code. Còn giữ: `auth`, `content`, `notifications`.

- Bảng cũ `courts`, `price_rules`, `bookings`, `booking_slots`, `payments` được **đổi tên** thành `legacy_*` bằng migration (**không xóa dữ liệu**, downgrade đổi lại). `alembic check` bỏ qua các bảng `legacy_*`. Xóa hẳn ở một task sau khi người dùng xác nhận.
- Trước khi lên production cần đếm đơn cũ còn hiệu lực (RELEASE báo người dùng).
- `GET /admin/users` trả `phone_masked` (ví dụ `0911 xxx 333`) **thay cho** `phone`.
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
