import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { type Column, DataTable, type SortDir } from "@/components/ui/data-table";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import type { AuditActorKind, AuditEntry } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { AuditChanges } from "./audit-changes";

type Props = {
  rows: readonly AuditEntry[];
  /** Chiều cột Thời điểm; bấm tiêu đề cột ⇒ `onSort` (mới trước ⇔ cũ trước). */
  sort: SortDir;
  onSort: () => void;
  empty: React.ReactNode;
  t: Dictionary["auditLog"];
};

// Người làm: Admin xanh lá, Nhân viên xanh dương, Hệ thống xám (SRS mục I.5, trường 8)
const ACTOR_BADGE: Record<AuditActorKind, "success" | "info" | "neutral"> = {
  admin: "success",
  staff: "info",
  system: "neutral",
};

/** Đối tượng 2 dòng: mã (hoặc tên) đậm, dòng dưới là tên kèm theo – chụp lúc làm (BR-008). */
function Target({ target, none }: { target: AuditEntry["target"]; none: string }) {
  const first = target.code ?? target.name;
  const second = target.code ? target.name : null;
  if (!first) return <span className="text-muted">{none}</span>;
  return (
    <div className="flex min-w-0 flex-col">
      <span className="font-medium wrap-break-word">{first}</span>
      {second ? <span className="text-xs wrap-break-word text-muted sm:text-ui">{second}</span> : null}
    </div>
  );
}

/** Nhân viên làm: "NV002 · Trần Văn Nam" chữ phụ; có mã ⇒ link sang đúng dòng ở trang Nhân viên (tài khoản đã xóa ⇒ chỉ tên). */
function StaffActor({ row, viewLabel }: { row: AuditEntry; viewLabel: string }) {
  const text = [row.actor_code, row.actor_name].filter(Boolean).join(" · ");
  if (row.actor !== "staff" || !text) return null;
  const style = "text-xs text-muted sm:text-ui";
  if (!row.actor_code) return <span className={style}>{text}</span>;
  return (
    <Link
      href={`/admin/nhan-vien?ma=${encodeURIComponent(row.actor_code)}`}
      title={viewLabel.replace("{code}", row.actor_code)}
      // Vùng chạm cao thêm vô hình (≥ 44px) mà không làm dòng cao lên
      className={cn(style, `
        relative rounded-sm underline decoration-border underline-offset-2 focus-ring
        transition-colors
        before:absolute before:inset-x-0 before:-inset-y-3
        hover:text-primary hover:decoration-primary
      `)}
    >
      {text}
    </Link>
  );
}

/** Bảng Lịch sử thao tác (Figma 642:14580): chỉ xem, không nút sửa / xóa (BR-010). */
export function AuditTable({ rows, sort, onSort, empty, t }: Props) {
  const c = t.columns;
  const columns: Column<AuditEntry>[] = [
    {
      key: "at",
      header: c.at,
      className: "w-36 whitespace-nowrap tabular-nums",
      sortable: true,
      card: "subtitle",
      cell: (r) => formatDateTime(r.at),
    },
    {
      key: "actor",
      header: c.actor,
      className: "w-40",
      card: "badge",
      // Bảng: badge rồi dòng dưới là mã + tên NV
      cell: (r) => (
        <div className="flex flex-col items-start gap-1">
          <Badge variant={ACTOR_BADGE[r.actor]}>{r.actor_label}</Badge>
          <StaffActor row={r} viewLabel={t.viewStaff} />
        </div>
      ),
      // Thẻ: badge cạnh tên thao tác, mã + tên NV theo sau cùng hàng (hết chỗ thì xuống dòng)
      cardCell: (r) => (
        <>
          <Badge variant={ACTOR_BADGE[r.actor]}>{r.actor_label}</Badge>
          <StaffActor row={r} viewLabel={t.viewStaff} />
        </>
      ),
    },
    { key: "action", header: c.action, className: "w-44 font-medium", card: "title", cell: (r) => r.action_label },
    {
      key: "target",
      header: c.target,
      className: "w-48",
      card: "meta",
      cell: (r) => <Target target={r.target} none={t.noValue} />,
      // Thẻ: "Đối tượng: HV0031 · Nguyễn Văn An" một dòng
      cardCell: (r) => [r.target.code, r.target.name].filter(Boolean).join(" · ") || null,
    },
    {
      key: "changes",
      header: c.changes,
      card: "body",
      cell: (r) => <AuditChanges changes={r.changes} t={t} />,
    },
  ];

  return (
    <DataTable
      caption={t.title}
      columns={columns}
      rows={rows}
      rowKey={(r) => String(r.id)}
      sort={{ key: "at", dir: sort }}
      onSort={onSort}
      empty={empty}
    />
  );
}
