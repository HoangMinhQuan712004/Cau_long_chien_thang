# Hướng dẫn chủ sân: bật thông báo trên điện thoại

Tài liệu này dùng để bật thông báo của web Sân cầu lông Chiến Thắng trên màn hình khóa điện thoại của bạn và nhân viên. Làm một lần cho mỗi điện thoại.

> **Trạng thái:** tính năng thông báo đẩy (T-076) **chưa lên link dev**. Tên nút và chữ trên màn hình lấy từ mô tả của nhóm làm giao diện, **chưa được kiểm trên điện thoại thật**. Sai khác thì báo lại để sửa tài liệu.

## Bạn sẽ nhận được gì

| Người | Thông báo |
|---|---|
| Admin, nhân viên (tùy quyền) | **Đặt online mới** · **Đã nhận tiền QR** tại quầy · **Tiền về cần xử lý** (chuyển thiếu, thừa hoặc không khớp mã) |
| Hội viên có tài khoản | **Sắp đến giờ chơi** (khoảng 1 giờ trước) · buổi chơi **được đổi** hoặc **bị hủy** · **đã ghi nhận thanh toán** · có người xin vào phòng chơi, yêu cầu của mình được duyệt hay bị từ chối |

- Nhân viên nhận loại nào **tùy quyền** Admin cấp ở tab Phân quyền (đặt online: xem lịch; tiền QR: thu tiền; tiền về cần xử lý: xem Lịch sử giao dịch). Tài khoản bị khóa không nhận gì.
- Thu **tiền mặt** không gửi thông báo cho nhân viên.
- Màn hình khóa **không hiện SĐT hay họ tên khách**, chỉ mã đơn, sân, giờ, số tiền.
- Khách không có tài khoản (chỉ đặt online bằng SĐT) **chưa nhận được thông báo**.

## Trước khi bắt đầu

1. Bạn phải **đăng nhập** (Admin hoặc nhân viên ở trang quản trị; hội viên ở khu hội viên).
2. Chủ hệ thống (người cài server) phải bật tính năng bằng khóa `VAPID_*` (xem README mục "Thông báo đẩy"). Chưa bật thì **sẽ không thấy nút "Bật thông báo" ở đâu cả**: bình thường, không phải lỗi máy bạn.

## iPhone (iOS 16.4 trở lên)

iPhone **chỉ nhận thông báo khi web đã được thêm vào Màn hình chính** và mở từ biểu tượng đó. Mở bằng Safari thường sẽ không nhận được.

1. Mở web bằng **Safari**.
2. Bấm nút **Chia sẻ** (hình vuông có mũi tên lên).
3. Chọn **Thêm vào Màn hình chính** → **Thêm**.
4. Mở app **Chiến Thắng** từ Màn hình chính, **đăng nhập**.
5. Vào khu hội viên (thẻ "Thông báo trên điện thoại" ở Tổng quan, hoặc menu tài khoản) hoặc menu tài khoản của trang quản trị, bấm **Bật thông báo trên máy này**.
6. iPhone hỏi quyền: chọn **Cho phép**.
7. Bấm **Gửi thử**: trong khoảng 1 phút điện thoại hiện "Thông báo đã được bật trên thiết bị này".

Nếu thấy dòng "Để nhận thông báo trên iPhone: bấm Chia sẻ → Thêm vào MH chính, rồi mở app Chiến Thắng", nghĩa là bạn chưa mở từ app trên Màn hình chính, hoặc iPhone dưới iOS 16.4 (cập nhật iOS rồi làm lại).

## Android (Chrome)

1. Mở web bằng **Chrome**, đăng nhập.
2. (Nên làm) Menu ⋮ → **Cài đặt ứng dụng** để có app riêng như iPhone. Không bắt buộc để nhận thông báo.
3. Vào khu hội viên hoặc menu tài khoản của trang quản trị, bấm **Bật thông báo trên máy này**.
4. Chrome hỏi quyền: chọn **Cho phép**.
5. Bấm **Gửi thử** để kiểm tra.

## Máy tính

Chrome hoặc Edge: làm như Android từ bước 3. Thường cần để trình duyệt đang chạy (có thể thu nhỏ) thì mới nhận được.

## Tắt thông báo, đổi người dùng chung một máy

- **Tắt:** bấm **Tắt** cạnh "Đã bật" trong cùng mục.
- **Đăng xuất** cũng **tắt thông báo của tài khoản đó trên máy này**. Người khác đăng nhập trên cùng máy muốn nhận thì bấm **Bật** lại.
- Mỗi tài khoản có tối đa **10 điện thoại**; thêm máy thứ 11 thì máy cũ nhất bị bỏ.

## Không nhận được thông báo?

| Dấu hiệu | Cách xử lý |
|---|---|
| Không có nút **Bật thông báo** | Chưa bật `VAPID_*` trên server, hoặc chưa đăng nhập, hoặc iPhone chưa mở từ Màn hình chính |
| "Bạn đã chặn thông báo cho trang này…" | Vào **Cài đặt** của điện thoại hoặc trình duyệt → Thông báo → cho phép trang này, rồi bấm Bật lại |
| Bấm **Gửi thử** nhưng không thấy gì | Kiểm tra chế độ **Không làm phiền / Tập trung** của điện thoại; kiểm tra mạng; thử **Tắt** rồi **Bật** lại |
| "Bạn đã gửi thử nhiều lần…" | Chờ vài phút (tối đa 5 lần gửi thử trong 10 phút) |
| Đang nhận bình thường rồi bỗng ngừng sau khi chủ hệ thống đổi khóa | Đổi khóa `VAPID_*` thì **mọi thiết bị phải bật lại**: **Tắt** rồi **Bật** |
| Đã đủ điều kiện nhưng nhân viên không nhận "Tiền về cần xử lý" | Admin kiểm tab Phân quyền: nhân viên cần quyền xem Lịch sử giao dịch |
