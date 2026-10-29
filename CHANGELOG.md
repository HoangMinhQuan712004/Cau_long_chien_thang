# Nhật ký thay đổi

Ghi các thay đổi người dùng hoặc người vận hành nhìn thấy được. Mới nhất ở trên.

## Chưa phát hành

Các mục T-005, T-006, T-008, T-012 đã có ở link dev; T-013 mới làm cục bộ, chưa lên dev. Tất cả chưa lên production (cần người dùng duyệt).

- **Đăng nhập mới, nhiều nhân viên, OTP (T-013, chưa lên dev):**
  - Một trang `/dang-nhap`: Admin đăng nhập bằng **số điện thoại**, nhân viên bằng **tên đăng nhập**, khách bằng SĐT/tên đăng nhập hoặc **Google**. Sai mật khẩu 5 lần khóa 15 phút.
  - **Mỗi nhân viên một tài khoản** thay cho "Tài khoản tại máy" dùng chung. Chủ sân thêm, khóa, đặt lại mật khẩu và đăng xuất từ xa tại `/admin/nhan-vien`. "Tài khoản tại máy" hiện tại thành `NV001` / `nv001`, giữ mật khẩu. Phiên Admin/nhân viên là phiên phía server, 12 giờ.
  - Quên mật khẩu bằng OTP (`/quen-mat-khau`). Khách tự đăng ký (`/dang-ky`), có trang `/tai-khoan` và xác minh SĐT; header hiện lại Đăng nhập/Đăng ký.
  - **Đặt online phải xác minh SĐT bằng OTP** trước khi giữ chỗ (đặt tại quầy và tra cứu không đổi). Gửi mã qua Zalo chưa làm: link dev dùng `OTP_TEST_MODE` (mã hiện trên màn hình); **production tạm chưa đặt online và chưa quên mật khẩu được** cho tới khi có Zalo.
  - Lệnh cứu Admin trên server: `python -m app.scripts.reset_admin_password`.
  - Giao diện toàn site chuyển sang bộ thiết kế mới (màu `#1a7354`, bỏ chế độ tối).
  - **Phá vỡ tương thích:** `/auth/login` → `/auth/sign-in`, `/admin/users` → `/admin/staff`, Admin/nhân viên không còn JWT.
  - **Vận hành:** phải có `FIRST_ADMIN_PHONE` trong `.env` server trước khi deploy (thiếu → migration dừng); biến mới `OTP_TEST_MODE`, `GOOGLE_CLIENT_ID`, `ZALO_*`. Xem README mục "Đăng nhập, nhân viên và OTP".
- **Khách đặt sân online (T-008):** trang `/dat-san` chọn nhiều ô, nhiều sân trong một ngày (tối đa 16 khung/lần, đặt trước không giới hạn ngày); thanh toán QR chuyển khoản qua SePay tại `/thanh-toan/…` với đếm ngược giữ chỗ 5 phút, tự chuyển sang "Đặt sân thành công" khi tiền về; trang `/tra-cuu` tra booking bằng mã + số điện thoại. Header: Đặt sân · Tra cứu booking · Hotline (ẩn Đăng nhập/Đăng ký). Chưa có tài khoản SePay thì khách vẫn xem lịch, nút đặt khóa và hiện "gọi hotline".
- **Chủ sân tự cài thanh toán online (T-012):** trang `/admin/cai-dat/thanh-toan` (chỉ Admin) nhập ngân hàng, số tài khoản, tên chủ, khóa webhook SePay và bật/tắt Nhận đặt online; không cần sửa server. Mỗi lần lưu phải nhập lại mật khẩu, ghi nhật ký, chặn đổi tài khoản khi còn lượt chờ thanh toán. Biến `.env` `SEPAY_*` chỉ còn là dự phòng. Server mới cần `PAYMENTS_ENCRYPTION_KEY` (bắt buộc ở link dev và production).
- **Tiền về cần xử lý (T-008, Admin):** trang `/admin/tien-ve` liệt kê tiền không khớp mã, tiền về sau khi hết hạn, trả thừa; Admin ghi chú rồi bấm Đã xử lý. Booking online hiện trên lịch quầy và Lịch sử giao dịch như booking quầy.
- **Lịch quầy (T-008):** xem được mọi ngày; Admin tạo sự kiện cho ngày xa không còn bị giới hạn "hết tháng sau". Đặt quầy booking thường vẫn chỉ trong hôm nay.
- **Quầy và quản trị (T-006):** lịch theo ngày (Trắng = Trống, Đỏ = Đã đặt, Vàng = Chưa thanh toán, Tím = Sự kiện, Xám = ngoài giờ mở cửa), đặt sân tại quầy chơi trước trả sau, tìm theo mã, sự kiện và vé, thu tiền mặt, đánh dấu Không thu được, Lịch sử giao dịch (Admin). Mã `BK-YYYYMMDD-NNN`. Trang chủ và `/bang-gia` lấy bảng giá từ cấu hình.
- **Luồng đặt sân cũ đã gỡ (T-006):** các route cũ (`/bookings`, `/courts`, `/price-rules`…) trả 404; bảng cũ đổi tên `legacy_*`, không xóa dữ liệu. Production vẫn chạy luồng cũ cho tới khi phát hành. Trước đó cần đếm đơn cũ còn hiệu lực và backup DB.
- **Cấu hình sân và bảng giá (T-005):** giờ mở cửa và khung cao điểm theo từng sân (đổi giờ có hiệu lực từ ngày mai), bảng giá theo loại sân × loại ngày × thấp/cao điểm, danh mục Lễ/Tết.
- **Bảo mật nền tảng (T-005):** chặn request ghi sai `Origin`, rate limit, `Idempotency-Key` cho lệnh ghi của booking engine, nhật ký thao tác chỉ thêm, số điện thoại luôn che ở API.
- Vận hành: thêm nhánh `dev` và môi trường dev https://chienthang-dev.superbai.vip (dữ liệu thử, không mật khẩu, `noindex`). Push `dev` tự deploy lên đây; `main` chỉ deploy production khi chủ dự án duyệt. Xem mục "Môi trường" trong README.
- Vận hành: CI chạy cho cả `main` và `dev`; CD chọn môi trường theo nhánh (`dev` → `/opt/caulong-dev`, `main` → `/opt/caulong`).
