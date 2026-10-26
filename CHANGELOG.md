# Nhật ký thay đổi

Ghi các thay đổi người dùng hoặc người vận hành nhìn thấy được. Mới nhất ở trên.

## Chưa phát hành

- Vận hành: thêm nhánh `dev` và môi trường dev https://chienthang-dev.superbai.vip (dữ liệu thử, không mật khẩu, `noindex`). Push `dev` tự deploy lên đây; `main` chỉ deploy production khi chủ dự án duyệt. Xem mục "Môi trường" trong README.
- Vận hành: CI chạy cho cả `main` và `dev`; CD chọn môi trường theo nhánh (`dev` → `/opt/caulong-dev`, `main` → `/opt/caulong`).
