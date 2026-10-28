# Nhật ký thay đổi

Ghi các thay đổi người dùng hoặc người vận hành nhìn thấy được. Mới nhất ở trên.

## Chưa phát hành

Các mục T-005, T-006 đã có ở link dev; T-008 mới làm cục bộ, chưa lên dev. Cả ba chưa lên production (cần người dùng duyệt).

- **Khách đặt sân online (T-008):** trang `/dat-san` chọn nhiều ô, nhiều sân trong một ngày (tối đa 16 khung/lần, đặt trước không giới hạn ngày); thanh toán QR chuyển khoản qua SePay tại `/thanh-toan/…` với đếm ngược giữ chỗ 5 phút, tự chuyển sang "Đặt sân thành công" khi tiền về; trang `/tra-cuu` tra booking bằng mã + số điện thoại. Header: Đặt sân · Tra cứu booking · Hotline (ẩn Đăng nhập/Đăng ký). Chưa có tài khoản SePay thì khách vẫn xem lịch, nút đặt khóa và hiện "gọi hotline".
- **Tiền về cần xử lý (T-008, Admin):** trang `/admin/tien-ve` liệt kê tiền không khớp mã, tiền về sau khi hết hạn, trả thừa; Admin ghi chú rồi bấm Đã xử lý. Booking online hiện trên lịch quầy và Lịch sử giao dịch như booking quầy.
- **Lịch quầy (T-008):** xem được mọi ngày; Admin đặt quầy ngày sau và tạo sự kiện không còn bị giới hạn "hết tháng sau".
- **Quầy và quản trị (T-006):** lịch theo ngày (Trắng = Trống, Đỏ = Đã đặt, Vàng = Chưa thanh toán, Tím = Sự kiện, Xám = ngoài giờ mở cửa), đặt sân tại quầy chơi trước trả sau, tìm theo mã, sự kiện và vé, thu tiền mặt, đánh dấu Không thu được, Lịch sử giao dịch (Admin). Mã `BK-YYYYMMDD-NNN`. Trang chủ và `/bang-gia` lấy bảng giá từ cấu hình.
- **Luồng đặt sân cũ đã gỡ (T-006):** các route cũ (`/bookings`, `/courts`, `/price-rules`…) trả 404; bảng cũ đổi tên `legacy_*`, không xóa dữ liệu. Production vẫn chạy luồng cũ cho tới khi phát hành. Trước đó cần đếm đơn cũ còn hiệu lực và backup DB.
- **Cấu hình sân và bảng giá (T-005):** giờ mở cửa và khung cao điểm theo từng sân (đổi giờ có hiệu lực từ ngày mai), bảng giá theo loại sân × loại ngày × thấp/cao điểm, danh mục Lễ/Tết.
- **Bảo mật nền tảng (T-005):** chặn request ghi sai `Origin`, rate limit, `Idempotency-Key` cho lệnh ghi của booking engine, nhật ký thao tác chỉ thêm, số điện thoại luôn che ở API.
- Vận hành: thêm nhánh `dev` và môi trường dev https://chienthang-dev.superbai.vip (dữ liệu thử, không mật khẩu, `noindex`). Push `dev` tự deploy lên đây; `main` chỉ deploy production khi chủ dự án duyệt. Xem mục "Môi trường" trong README.
- Vận hành: CI chạy cho cả `main` và `dev`; CD chọn môi trường theo nhánh (`dev` → `/opt/caulong-dev`, `main` → `/opt/caulong`).
