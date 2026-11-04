"""Danh mục loại thao tác hiện ở màn Lịch sử thao tác (SRS Lịch sử thao tác BR-005).

Chỉ loại có trong danh mục mới hiện và lọc được; ``audit_log`` vẫn ghi các mã khác
(vd ``member.view``) nhưng màn không hiện (BR-002). Chức năng mới có ghi lịch sử ⇒ thêm loại
vào đây, bộ lọc tự có theo.

Đủ bảng BR-005, nhưng "Chặn đăng nhập", "Đổi mật khẩu Tài khoản tại máy", "Đặt máy quầy" chưa
có chức năng ghi (chọn thì danh sách trống); khi làm Chặn đăng nhập / Đổi MK / Máy quầy thì ghi
đúng mã ở đây.

Lệch docs (người dùng duyệt 2026-10-30):
- Người làm "Nhân viên" = vai ``staff`` (docs ghi "Tài khoản tại máy" – 1 tài khoản dùng chung;
  code có tài khoản riêng từng NV, người dùng đổi tên 2026-10-30).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionType:
    key: str  # mã lọc gửi từ màn hình (= mã chính trong audit_log)
    label: str
    actions: tuple[str, ...]  # mọi mã ``audit_log.action`` hiện dưới tên này


@dataclass(frozen=True)
class ActionGroup:
    label: str
    types: tuple[ActionType, ...]


def _t(key: str, label: str, *aliases: str) -> ActionType:
    return ActionType(key=key, label=label, actions=(key, *aliases))


GROUPS: tuple[ActionGroup, ...] = (
    ActionGroup(
        "Đăng nhập, đăng xuất",
        (
            _t("auth.login_success", "Đăng nhập thành công"),
            _t("auth.login_locked", "Tạm khóa đăng nhập"),
            _t("auth.login_blocked", "Chặn đăng nhập"),
            _t("auth.logout", "Đăng xuất"),
            _t("auth.logout_password_changed", "Đăng xuất do đổi mật khẩu"),
        ),
    ),
    ActionGroup(
        "Tài khoản",
        (
            _t("account.counter_password_change", "Đổi mật khẩu Tài khoản tại máy"),
            _t("account.counter_device_set", "Đặt máy quầy"),
            # T-021 AC3: người xác minh OTP lấy SĐT khỏi tài khoản chưa xác minh (Hệ thống làm)
            _t("auth.phone_released", "Gỡ SĐT khỏi tài khoản chưa xác minh"),
        ),
    ),
    ActionGroup(
        "Sân & bảng giá",
        (
            _t("config.resource.create", "Thêm sân"),
            _t("config.resource.update", "Sửa sân"),
            _t("config.price.update", "Lưu bảng giá"),
        ),
    ),
    ActionGroup(
        "Hội viên",
        (
            # Chuyển hồ sơ tạm thành hội viên cũng là thêm hội viên (cấp mã HV)
            _t("member.create", "Thêm hội viên", "member.promote"),
            _t("member.update", "Sửa hội viên"),
            _t("member.temp.create", "Tạo hồ sơ tạm"),
            # T-021 R1: chủ SĐT xác minh OTP -> Hệ thống nâng hồ sơ tạm (hội viên tự đăng ký mới
            # ``member.self_register`` do khách làm, không hiện – như quy ước PR #22)
            _t("member.auto_upgrade_temp", "Tự nâng hồ sơ tạm thành hội viên"),
        ),
    ),
    ActionGroup(
        "Đặt sân & thanh toán",
        (
            _t("booking.counter.create", "Đặt sân tại quầy"),
            _t("booking.recurring.create", "Đặt sân định kỳ"),  # T-035, chỉ Admin
            _t("session.create", "Đặt sự kiện"),
            _t("session.delete", "Xóa buổi"),
            _t("ticket.create", "Đăng ký vé"),
            # Thu tiền QR: tiền về xác nhận qua bên thứ 3, người làm là Hệ thống (BR-009)
            # T-023: tiền về cho lượt mua vé online cũng là Thu tiền QR (Hệ thống)
            _t("payment.collect", "Thu tiền", "booking.online.paid", "ticket.online.paid"),
            _t("payment.uncollectible", "Không thu được"),
        ),
    ),
    ActionGroup(
        "Kỷ lục",
        (
            # T-046: Admin gắn / gỡ link video cho số đo tốc độ
            _t("record.video_set", "Gắn video kỷ lục"),
            _t("record.video_removed", "Gỡ video kỷ lục"),
        ),
    ),
)

# Người làm lọc được (BR-013): mã ``audit_log.actor_type`` -> nhãn
ACTORS: dict[str, str] = {"admin": "Admin", "staff": "Nhân viên", "system": "Hệ thống"}

TYPES: dict[str, ActionType] = {t.key: t for g in GROUPS for t in g.types}
# Mã audit_log.action -> loại hiển thị
BY_ACTION: dict[str, ActionType] = {a: t for t in TYPES.values() for a in t.actions}


def actions_for(key: str | None) -> tuple[str, ...]:
    """Mã ``audit_log.action`` cần lọc: một loại, hoặc cả danh mục khi chọn "Tất cả"."""
    if key is None:
        return tuple(BY_ACTION)
    return TYPES[key].actions
