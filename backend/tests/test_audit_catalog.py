"""Danh mục loại thao tác + nội dung dòng chuẩn (SRS Lịch sử thao tác BR-005, BR-006, BR-008)."""

from app.core.audit import ACTOR_TYPES, audit_change, audit_changes, audit_detail
from app.modules.audit_log import catalog


def test_each_audit_action_maps_to_one_type():
    actions = [a for t in catalog.TYPES.values() for a in t.actions]
    assert len(actions) == len(set(actions)), "một mã action chỉ thuộc một loại"
    assert len(catalog.TYPES) == sum(len(g.types) for g in catalog.GROUPS), "key không trùng"


def test_catalog_follows_srs_groups():
    assert [g.label for g in catalog.GROUPS] == [
        "Đăng nhập, đăng xuất",
        "Tài khoản",
        "Sân & bảng giá",
        "Hội viên",
        "Đặt sân & thanh toán",
        "Kỷ lục",  # T-046: gắn / gỡ video kỷ lục
    ]
    assert [t.label for t in catalog.GROUPS[0].types] == [
        "Đăng nhập thành công",
        "Tạm khóa đăng nhập",
        "Chặn đăng nhập",
        "Đăng xuất",
        "Đăng xuất do đổi mật khẩu",
    ]
    assert [t.label for t in catalog.GROUPS[1].types] == [
        "Đổi mật khẩu",
        "Sửa hồ sơ",
        "Sửa phân quyền",
        "Sắp xếp menu",
        "Đổi mật khẩu Tài khoản tại máy",
        "Đặt máy quầy",
        "Gỡ SĐT khỏi tài khoản chưa xác minh",
    ]
    # Xem hồ sơ không hiện ở màn này (BR-002)
    assert "member.view" not in catalog.BY_ACTION


def test_actor_filter_uses_known_actor_types():
    assert set(catalog.ACTORS) <= set(ACTOR_TYPES)
    assert catalog.ACTORS["staff"] == "Nhân viên"


def test_actions_for_all_and_one_type():
    assert set(catalog.actions_for(None)) == set(catalog.BY_ACTION)
    assert catalog.actions_for("payment.collect") == (
        "payment.collect",
        "booking.online.paid",
        "ticket.online.paid",  # T-023: tiền về cho vé mua online
    )


def test_changes_keep_label_order_and_skip_unchanged():
    labels = {"full_name": "Họ tên", "phone": "SĐT", "tier": "Trình độ"}
    before = {"full_name": "An", "phone": "0901234567", "tier": "Khá"}
    after = {"full_name": "Bình", "phone": "0901234567", "tier": "Giỏi"}
    assert audit_changes(labels, before, after) == [
        audit_change("Họ tên", "An", "Bình"),
        audit_change("Trình độ", "Khá", "Giỏi"),
    ]


def test_create_has_empty_before():
    changes = audit_changes({"name": "Tên sân"}, {}, {"name": "Sân 1"})
    assert changes == [{"field": "Tên sân", "before": None, "after": "Sân 1"}]


def test_detail_snapshots_target_name():
    assert audit_detail("HV0001", "Nguyễn Văn An", [], kind="member") == {
        "target": {"code": "HV0001", "name": "Nguyễn Văn An"},
        "changes": [],
        "kind": "member",
    }
