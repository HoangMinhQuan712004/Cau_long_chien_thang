# Ghi chú cập nhật SRS v0.2 sau T-013

Tài liệu này liệt kê chỗ SRS v0.2 (26/10/2026) phải sửa khi T-013 (đăng nhập, nhiều nhân viên, OTP) lên `dev`, để người giữ SRS cập nhật theo. Nguồn quyết định: ADR-008 và spec T-013 (`T-013-dang-nhap-nhan-vien.md`) trong thư mục `board/` của nhóm. Đây là ghi chú theo spec; xác nhận lại với code khi T-013 đã vào `dev`.

## Những chỗ cần sửa

| Mục SRS | SRS v0.2 đang ghi | Sửa thành |
|---|---|---|
| Vai người dùng | **Tài khoản tại máy** = 1 tài khoản dùng chung ở quầy | **Nhân viên** = mỗi người một tài khoản (mã `NV001`…, không dùng lại), đăng nhập ở máy nào cũng được. Quyền **giữ nguyên** như "Tài khoản tại máy" cũ: không tạo/xóa sự kiện, không xem Lịch sử giao dịch; thêm: không vào Nhân viên, không vào Cài đặt thanh toán |
| Vai Admin | Chủ sân, làm mọi thao tác | Thêm: **quản lý nhân viên** (thêm, sửa tên, khóa/mở khóa, đặt lại mật khẩu, xem và đăng xuất từ xa các phiên đang mở) |
| Nhãn người thao tác | "Tài khoản tại máy" | `NV007 · Nguyễn Văn An`. Bản ghi cũ giữ nhãn "Tài khoản tại máy" |
| Đăng nhập | (chưa chi tiết / email + mật khẩu ở bản cũ) | Admin bằng **số điện thoại**, nhân viên bằng **tên đăng nhập**, khách bằng SĐT hoặc tên đăng nhập hoặc **Google**. Một trang `/dang-nhap` |
| Phiên | JWT | Admin/nhân viên: phiên phía server, **12 giờ cứng**, thu hồi được (đổi mật khẩu, khóa tài khoản, đăng xuất từ xa). Khách: JWT, đổi mật khẩu thì JWT cũ hết hiệu lực |
| Bảo vệ tài khoản | – | Sai mật khẩu 5 lần liên tiếp → khóa 15 phút; từ một IP sai 20 lần/15 phút → tạm chặn IP |
| Mật khẩu | – | ≥ 8 ký tự, có 1 chữ in hoa và 1 chữ số hoặc ký tự đặc biệt (mật khẩu cũ yếu vẫn đăng nhập được) |
| Quên mật khẩu | – | Qua **OTP** gửi vào số điện thoại; mã 6 số, hạn 5 phút, sai 5 lần thì hủy, gửi lại sau 60 giây. Tạm ngưng trên production cho tới khi có Zalo |
| Đặt online | Giữ chỗ 7 phút; booking chỉ được tạo khi tiền về | (Đã sửa ở T-008: giữ chỗ **5 phút**.) Thêm: khách phải **xác minh SĐT bằng OTP** trước khi giữ chỗ. Khách đã đăng nhập với SĐT đã xác minh thì bỏ qua |
| Đặt tại quầy | Chơi trước, trả sau | **Không đổi, không cần OTP** (khách có mặt) |
| Tra cứu booking | Mã + SĐT | **Không đổi**, không cần OTP |
| Tài khoản khách | – | Đăng ký bằng họ tên + SĐT + mật khẩu (không còn email); trang `/tai-khoan`; xác minh SĐT; gộp tài khoản Google với tài khoản SĐT khi cùng chủ |
| Kênh gửi OTP | – | Zalo ZNS, **làm sau**. Tới lúc đó: link dev dùng `OTP_TEST_MODE` (mã hiện trên màn hình), production **chưa bật đặt online** và chưa quên mật khẩu được |
| Cứu Admin | – | Lệnh trên server `python -m app.scripts.reset_admin_password` |
| Giao diện | – | Bộ thiết kế mới (màu chính `#1a7354`, bỏ chế độ tối) cho toàn site |

## Không thuộc T-013 (đừng ghi vào SRS như đã có)

- Gửi OTP qua Zalo thật; OTP khi đặt tại quầy; lịch sử đặt sân trong `/tai-khoan`; đổi mật khẩu khi đang đăng nhập (T-010, hoãn); đăng nhập hội viên theo Figma; vé sự kiện online.
