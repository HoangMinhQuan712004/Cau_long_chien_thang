# Nhật ký thay đổi

Ghi các thay đổi người dùng hoặc người vận hành nhìn thấy được. Mới nhất ở trên.

## Chưa phát hành

Các mục T-005, T-006, T-008, T-012 đã có ở link dev; T-013, T-015 (PR #21), và T-016, T-019, T-020 (PR #23) cũng đã lên dev; T-021 mới làm cục bộ. Tất cả chưa lên production (cần người dùng duyệt).

- **Đăng ký là thành hội viên (T-021, chưa lên dev):**
  - Khách đăng ký ở `/dang-ky` theo **hai bước**: nhập họ tên, SĐT, mật khẩu → nhập mã OTP. Mã đúng thì tạo tài khoản **và** hội viên (Mã HV, chưa xếp hạng), đăng nhập luôn. SĐT đã có hồ sơ tạm thì hồ sơ đó được nâng lên hội viên, giữ lịch sử đặt sân.
  - Tài khoản web có SĐT **đã xác minh OTP** là hội viên, dù xác minh khi đăng ký, ở `/tai-khoan`, khi đặt online hay khi Quên mật khẩu. Hội viên Ngừng thì tài khoản bị khóa. Màn Hội viên ghi nguồn "Tự đăng ký online".
  - Tài khoản đời cũ đăng ký không OTP: người xác minh OTP số đó thắng, tài khoản cũ bị gỡ SĐT. Đặt online bằng tài khoản Google chưa có SĐT thì SĐT được gắn vào tài khoản.
  - **Phá vỡ tương thích:** `POST /auth/register` trả 410 (`E-AUTH-32`); thay bằng `/auth/register/request` + `/auth/register/verify`. Ảnh đại diện quá 5 MB nay trả 413 `E-HV-13` (JSON) thay vì ngắt kết nối. Mã lỗi mới `E-AUTH-31`.
  - **Vận hành:** migration `9738bbfe2eb7` **tự backfill** hội viên cho tài khoản đã xác minh SĐT; không có biến hay gói mới. Production chưa có Zalo nên `/dang-ky` hiện "Đăng ký tài khoản đang tạm ngưng" cho tới khi có kênh OTP.
- **Chỉnh màn Hội viên theo quyết định 31/10 (T-020):** SĐT đã có hồ sơ tạm thì **không thêm hội viên được** (báo "Số điện thoại đã có hồ sơ tạm: … (tạo dd/mm/yyyy)"; bỏ nút "Nâng thành hội viên"). Hội viên Ngừng **đặt được** sân tại quầy (có nhãn "Ngừng"). Bấm Thêm hội viên hai lần không tạo trùng. Hai máy cùng sửa một hội viên: máy lưu sau nhận lỗi và nút **Tải lại**. **Phá vỡ tương thích:** `POST /members`, `/members/temp` cần `Idempotency-Key`; `PATCH /members/{ref}` cần `version`; bỏ `upgrade_temp`.
- **Một lượt đặt một mã (T-019):** mỗi lần đặt (online hoặc quầy) có **một mã đơn** `BK-YYYYMMDD-NNN`; từng khối sân × giờ trong đơn mang mã con `{mã đơn}-01`…. Khách chỉ thấy mã đơn; quầy thấy mã đơn trên lịch, mã con trong chi tiết. Đặt quầy chọn được nhiều khối một lần (trùng một khối thì không khối nào được tạo). Thu tiền theo từng khối, thêm **Thu cả đơn**. Tìm mã và tra cứu nhận cả hai loại mã; tra cứu hiện cả đơn. **Đổi contract API** (BE và FE lên cùng đợt). Nội dung chuyển khoản (`BK` + 11 số) không đổi. Migration `5b98d354dd77`: booking cũ thành đơn một khối (`-01`), lượt thanh toán đang chờ bị cho hết hạn.
- **Khu hội viên trên web, đợt 1 "Hồ sơ của tôi" (T-016):**
  - Khu `/hoi-vien` cho khách là hội viên (tài khoản có SĐT trùng hội viên, do sân tạo hoặc đã xác minh OTP). Hội viên tự sửa Họ tên, Biệt danh, Email (không bắt buộc), Trình độ (= Hạng), Vợt, công tắc "Hiện trên Video & kỷ lục", đổi và xóa ảnh đại diện. Các mục khác của khu hiện là "Sắp ra mắt".
  - Đổi Họ tên thì tên trên booking, vé, lượt thanh toán đổi theo. Hai tab sửa cùng lúc: tab lưu sau nhận lỗi, không ghi đè.
  - **Vận hành:** biến `AVATAR_MAX_BYTES` (mặc định 5 MB), gói mới `pillow`, `python-multipart` (**build lại image backend**); proxy phải cho thân request tới khoảng 5,06 MB. Migration `dad220bfc992`.
- **Quản lý hội viên và tài khoản hội viên (T-015, PR #21):**
  - Màn `/admin/hoi-vien` (Admin và nhân viên): danh sách hội viên và hồ sơ tạm, tìm, lọc theo Loại / Trạng thái / Hạng / Vợt, sắp theo Số lần đặt, xem chi tiết (tổng giờ, 5 lần đặt gần nhất), thêm / sửa hội viên, tạo hồ sơ tạm, danh mục vợt (chỉ Admin).
  - **Hạng đổi sang 8 bậc** (Yếu … Chuyên nghiệp), có thể "Chưa xếp hạng"; hạng ưu đãi cũ Vàng/Bạc/Đồng của dữ liệu thử thành "Chưa xếp hạng". Chỉ Admin đổi Trạng thái (nhân viên đổi được Hạng); hội viên Ngừng bị khóa tài khoản web.
  - **Thêm hội viên tạo luôn tài khoản web:** đăng nhập bằng SĐT, mật khẩu ban đầu là chính SĐT, phải đổi ở `/doi-mat-khau` trong 3 ngày. Vai `customer` đổi tên thành `member`. Khách xem thẻ hội viên và lịch sử đặt sân ở `/tai-khoan`.
  - Màn quản trị và API quản trị hiện SĐT **đầy đủ** (trước đây che). Số lần đặt chưa tính vé sự kiện. Quầy không đổi được SĐT hồ sơ.
  - **Vận hành:** migration `a3d81f5c2b6e`. Hội viên đã có từ trước chưa có tài khoản web cho tới khi chạy `python -m app.scripts.backfill_member_accounts` (không tự chạy khi deploy). Biến `MEMBER_INITIAL_PASSWORD_DAYS` (mặc định 3).
- **Đăng nhập mới, nhiều nhân viên, OTP (T-013):**
  - Một trang `/dang-nhap`: Admin đăng nhập bằng **số điện thoại**, nhân viên bằng **tên đăng nhập**, khách bằng SĐT/tên đăng nhập hoặc **Google**. Sai mật khẩu 5 lần khóa 15 phút.
  - **Mỗi nhân viên một tài khoản** thay cho "Tài khoản tại máy" dùng chung. Chủ sân thêm, khóa, đặt lại mật khẩu và đăng xuất từ xa tại `/admin/nhan-vien`. "Tài khoản tại máy" hiện tại thành `NV001` / `nv001`, giữ mật khẩu. Phiên Admin/nhân viên là phiên phía server, 12 giờ.
  - Quên mật khẩu bằng OTP (`/quen-mat-khau`). Khách tự đăng ký (`/dang-ky`), có trang `/tai-khoan` và xác minh SĐT; header hiện lại Đăng nhập/Đăng ký.
  - **Đặt online phải xác minh SĐT bằng OTP** trước khi giữ chỗ (đặt tại quầy và tra cứu không đổi). Gửi mã qua Zalo chưa làm: link dev dùng `OTP_TEST_MODE` (mã hiện trên màn hình); **production tạm chưa đặt online và chưa quên mật khẩu được** cho tới khi có Zalo.
  - Khách đăng xuất về trang chủ (Admin/nhân viên về `/dang-nhap`). Ở `/dat-san` bước 2, khách chưa đăng nhập thấy khối "Bạn là hội viên?" (Đăng nhập / Đăng ký hội viên) và quay lại đúng bước sau khi đăng nhập. Khách đã xác minh SĐT một lần thì các lần đặt sau không phải nhập OTP.
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
