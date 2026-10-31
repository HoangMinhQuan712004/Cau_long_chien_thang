import { Badge } from "@/components/ui/badge";
import { type Column, DataTable, type SortDir } from "@/components/ui/data-table";
import { IconButton } from "@/components/ui/icon-button";
import { EyeIcon, PencilIcon } from "@/components/ui/icons";
import type { Dictionary } from "@/i18n/dictionaries";
import type { MemberRow } from "@/lib/api/server";
import { formatPhone } from "@/lib/phone";

type MemberAction = "detail" | "edit";

type Props = {
  rows: readonly MemberRow[];
  /** Chiều sắp xếp "Số lần đặt"; null = mặc định. */
  sortDir: SortDir | null;
  onSort: () => void;
  onAction: (action: MemberAction, row: MemberRow) => void;
  empty: React.ReactNode;
  t: Dictionary["members"];
};

const NAME = "rounded-sm text-left font-medium focus-ring hover:text-primary hover:underline";

/** Bảng hội viên + hồ sơ tạm (Figma P5): dòng Ngừng mờ; hồ sơ tạm cũng có Chi tiết / Sửa. */
export function MemberTable({ rows, sortDir, onSort, onAction, empty, t }: Props) {
  const c = t.columns;
  const columns: Column<MemberRow>[] = [
    // Cột phụ ẩn khi chật (lg còn ~680px cho bảng sau sidebar); thẻ điện thoại vẫn có mã ở dòng phụ
    {
      key: "code",
      header: c.code,
      className: "w-24",
      hideBelow: "lg",
      card: "subtitle",
      cell: (r) => r.member_code ?? "—",
      cardCell: (r) => r.member_code,
    },
    {
      key: "name",
      header: c.name,
      className: "font-medium",
      card: "title",
      // Tên là nút mở Chi tiết (cho bàn phím); chuột / chạm thì bấm đâu trên dòng cũng được
      cell: (r) => (
        <button type="button" className={NAME} onClick={() => onAction("detail", r)}>
          {r.full_name}
          {r.kind === "member" && r.source === "self_register" ? (
            <span className="ml-2 align-middle text-xs font-normal text-muted">{t.drawer.sourceSelf}</span>
          ) : null}
        </button>
      ),
    },
    { key: "phone", header: c.phone, className: "whitespace-nowrap tabular-nums", card: "subtitle", cell: (r) => formatPhone(r.phone) },
    {
      key: "kind",
      header: c.kind,
      card: "badge",
      cell: (r) => <Badge variant={r.kind === "member" ? "info" : "warning"}>{t.kinds[r.kind]}</Badge>,
      // Thẻ: hội viên là mặc định (tab đã cho biết) ⇒ chỉ gắn nhãn hồ sơ tạm
      cardCell: (r) => (r.kind === "temp" ? <Badge variant="warning">{t.kinds.temp}</Badge> : null),
    },
    {
      key: "tier",
      header: c.tier,
      hideBelow: "xl",
      // Thẻ: "Hạng: Khá" có nhãn (nhãn trơn "Khá" người dùng không hiểu là gì)
      card: "meta",
      cell: (r) => r.tier ?? "—",
      cardCell: (r) => r.tier ?? t.tierNone,
    },
    {
      key: "bookings",
      header: c.bookings,
      align: "center",
      sortable: true,
      className: "tabular-nums",
      card: "meta",
      cell: (r) => r.bookings,
    },
    {
      key: "status",
      header: c.status,
      card: "badge",
      // Hồ sơ tạm không có trạng thái: bảng ghi "—", thẻ bỏ nhãn
      cardCell: (r) =>
        r.kind === "temp" ? null : (
          <Badge variant={r.is_active ? "success" : "neutral"}>{r.is_active ? t.statuses.active : t.statuses.inactive}</Badge>
        ),
      cell: (r) =>
        r.kind === "temp" ? "—" : (
          <Badge variant={r.is_active ? "success" : "neutral"}>{r.is_active ? t.statuses.active : t.statuses.inactive}</Badge>
        ),
    },
    {
      key: "actions",
      header: c.actions,
      align: "right",
      card: "actions",
      className: "whitespace-nowrap",
      // Hội viên và hồ sơ tạm cùng 2 nút: Xem chi tiết, Sửa (tên đầy đủ kèm tên người cho trình đọc màn hình)
      cell: (r) => (
        <span className="-my-1.5 inline-flex items-center gap-1">
          <IconButton
            icon={<EyeIcon />}
            label={t.detailLabel.replace("{name}", r.full_name)}
            tooltip={t.detail}
            onClick={() => onAction("detail", r)}
          />
          <IconButton
            icon={<PencilIcon />}
            label={t.editLabel.replace("{name}", r.full_name)}
            tooltip={t.edit}
            onClick={() => onAction("edit", r)}
          />
        </span>
      ),
    },
  ];

  return (
    <DataTable
      caption={t.title}
      columns={columns}
      rows={rows}
      rowKey={(r) => r.ref}
      rowClassName={(r) => (r.kind === "member" && !r.is_active ? "text-subtle" : undefined)}
      // Bấm cả dòng mở chi tiết; nút tên vẫn giữ cho bàn phím / trình đọc màn hình
      onRowClick={(r) => onAction("detail", r)}
      sort={sortDir ? { key: "bookings", dir: sortDir } : undefined}
      onSort={onSort}
      empty={empty}
      stickyHeader
    />
  );
}
