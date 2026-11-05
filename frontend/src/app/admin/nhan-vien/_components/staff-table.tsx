"use client";

import { ActionMenu, type MenuAction } from "@/components/ui/action-menu";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { type Column, DataTable } from "@/components/ui/data-table";
import { CopyIcon, HistoryIcon, LogOutIcon, PencilIcon, ResetIcon, SettingsIcon } from "@/components/ui/icons";
import type { Staff } from "@/lib/api/server";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";
import { formatDateTime, formatDayMonthYear, vnDate } from "@/lib/format";
import type { StaffTexts } from "./staff-form-kit";

// Bảng nhân viên (đồng bộ màn Hội viên): STT | Mã | Tên | Tên đăng nhập | Trạng thái | Đăng nhập gần nhất | Đang đăng nhập | ⋯;
// điện thoại là thẻ gọn (DataTable tự lo).
// Thao tác của từng người gom vào menu ⋯; bấm dòng / tên ⇒ ngăn chi tiết.

export type StaffAction = "detail" | "sessions" | "rename" | "password" | "lock" | "unlock";

type Props = {
  rows: readonly Staff[];
  /** Số dòng của các trang trước (STT trang 2 bắt đầu từ 21). */
  indexOffset: number;
  /** Mốc "bây giờ" (ms) để tính "x phút trước"; nơi gọi giữ trong state (không gọi Date.now khi render). */
  now: number;
  /** Mã NV mở từ link `?ma=`: tô nổi dòng đó. */
  focusCode: string | null;
  empty: React.ReactNode;
  onAction: (action: StaffAction, staff: Staff) => void;
  t: StaffTexts;
};

/** "03/11/2026" (ngày VN). */
export const shortDate = (iso: string) => formatDayMonthYear(vnDate(iso));

/** "vừa xong" / "5 phút trước" / "3 giờ trước" / "2 ngày trước"; quá 30 ngày ⇒ ngày đầy đủ. */
export function relativeTime(iso: string, now: number, t: StaffTexts): string {
  const minutes = Math.max(0, Math.floor((now - Date.parse(iso)) / 60_000));
  if (minutes < 1) return t.justNow;
  if (minutes < 60) return t.minutesAgo.replace("{n}", String(minutes));
  if (minutes < 60 * 24) return t.hoursAgo.replace("{n}", String(Math.floor(minutes / 60)));
  if (minutes < 60 * 24 * 30) return t.daysAgo.replace("{n}", String(Math.floor(minutes / 1440)));
  return shortDate(iso);
}

/** Các mục menu ⋯ (dùng chung cho bảng và ngăn chi tiết). */
export function staffMenu(s: Staff, onAction: Props["onAction"], t: StaffTexts): MenuAction[] {
  return [
    { label: t.editName, icon: <PencilIcon />, onClick: () => onAction("rename", s) },
    { label: t.resetPassword, icon: <ResetIcon />, onClick: () => onAction("password", s) },
    // Nhãn gọn để menu không xuống dòng trên điện thoại
    { label: t.devicesMenu.replace("{n}", String(s.active_sessions)), icon: <HistoryIcon />, onClick: () => onAction("sessions", s) },
    s.is_active
      ? { label: t.lock, icon: <LogOutIcon />, danger: true, onClick: () => onAction("lock", s) }
      : { label: t.unlock, icon: <SettingsIcon />, onClick: () => onAction("unlock", s) },
  ];
}

/** Chép vào bộ nhớ tạm + báo toast (dùng chung cho tên đăng nhập và màn kết quả tạo / đặt lại mật khẩu). */
export async function copyText(text: string, t: StaffTexts) {
  try {
    await navigator.clipboard.writeText(text);
    toast(t.copied, undefined, "info");
  } catch {
    toast(t.copyFailed, undefined, "error");
  }
}

/** Nút chép nhỏ (⧉) đứng sau một giá trị; `label` là tên giá trị ("tên đăng nhập", "mật khẩu"…). */
export function CopyButton({ value, label, t }: { value: string; label: string; t: StaffTexts }) {
  const text = t.copyValue.replace("{label}", label.toLowerCase());
  return (
    <button
      type="button"
      onClick={() => void copyText(value, t)}
      title={text}
      aria-label={`${text}: ${value}`}
      className="grid size-7 shrink-0 place-items-center rounded-md text-muted hover:bg-primary-softer hover:text-primary focus-ring [&>svg]:size-3.5"
    >
      <CopyIcon />
    </button>
  );
}

/** Tên đăng nhập: luôn đầy đủ, to, rõ, màu xanh (mono); thiếu chỗ thì cả cụm xuống dòng (chỉ ngắt giữa chữ khi dài hơn cả dòng), không cắt "…"; kèm nút chép. */
export function Username({ value, t }: { value: string; t: StaffTexts }) {
  return (
    <span className="inline-flex max-w-full items-center gap-0.5">
      <span className="font-mono text-sm font-semibold wrap-break-word text-primary">{value}</span>
      <CopyButton value={value} label={t.usernameLabel} t={t} />
    </span>
  );
}

/** Tài khoản đã khóa: nội dung mờ 50% (trạng thái "Đã khóa" và nút ⋯ giữ rõ để Mở khóa); hover thì rõ lại để đọc. */
const DIM = "opacity-50 transition-opacity group-hover/row:opacity-90 motion-reduce:transition-none";
const dim = (s: Staff) => (s.is_active ? undefined : DIM);

const NAME = "rounded-sm text-left font-semibold focus-ring hover:text-primary hover:underline";

export function StaffTable({ rows, indexOffset, now, focusCode, empty, onAction, t }: Props) {
  const lastLogin = (s: Staff) => (s.last_login_at ? relativeTime(s.last_login_at, now, t) : t.never);
  const nameButton = (s: Staff) => (
    // Tên là nút mở chi tiết (cho bàn phím); chuột / chạm thì bấm đâu trên dòng cũng được
    <button type="button" data-staff={s.staff_code} className={NAME} onClick={() => onAction("detail", s)}>
      {s.full_name}
    </button>
  );

  const columns: Column<Staff>[] = [
    {
      key: "index",
      header: t.colIndex,
      align: "right",
      className: "w-12 text-muted tabular-nums",
      // Khung ~1024 (sidebar mở) thiếu chỗ ⇒ ẩn STT, ưu tiên tên / tên đăng nhập hiện đủ
      hideBelow: "xl",
      // STT theo danh sách đang hiện (sau tìm / lọc); thẻ điện thoại không cần
      cell: (s) => <span className={dim(s)}>{indexOffset + rows.indexOf(s) + 1}</span>,
      cardCell: () => null,
    },
    {
      key: "code",
      header: t.colCode,
      className: "w-24 whitespace-nowrap tabular-nums",
      cell: (s) => <span className={dim(s)}>{s.staff_code}</span>,
      cardCell: () => null,
    },
    {
      key: "name",
      header: t.colName,
      card: "body",
      cell: (s) => (
        <span className={cn("flex min-w-0 items-center gap-2.5", dim(s))}>
          <Avatar name={s.full_name} size="sm" />
          {nameButton(s)}
        </span>
      ),
      // Thẻ điện thoại 3 dòng (theo ảnh mẫu), lưới 2 cột cố định ⇒ trạng thái và ⋯ thẳng hàng mọi thẻ:
      //   Tên (semibold)                 ● Trạng thái
      //   NV002 (xs, muted)                        ⋯ (hàng 2–3, giữa dọc)
      //   tên đăng nhập xanh ⧉ (đầy đủ)
      // Thời gian đăng nhập không hiện trên thẻ (xem trong ngăn chi tiết).
      cardCell: (s) => (
        <span className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3">
          <span className={cn("min-w-0 text-sm [&>button]:block [&>button]:max-w-full [&>button]:truncate", dim(s))}>{nameButton(s)}</span>
          <span className={cn("inline-flex items-center justify-end gap-1 text-xs font-medium whitespace-nowrap", s.is_active ? "text-primary" : "text-muted")}>
            <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-current" />
            {s.is_active ? t.activeShort : t.disabled}
          </span>
          <span className={cn("col-start-1 text-xs text-muted tabular-nums", dim(s))}>{s.staff_code}</span>
          <span className="col-start-2 row-span-2 row-start-2 flex items-center justify-end">
            <ActionMenu label={`${t.moreActions}: ${s.full_name}`} items={staffMenu(s, onAction, t)} />
          </span>
          <span className={cn("col-start-1 min-w-0", dim(s))}>
            <Username value={s.username} t={t} />
          </span>
        </span>
      ),
    },
    {
      key: "username",
      header: t.colUsername,
      cell: (s) => (
        <span className={dim(s)}>
          <Username value={s.username} t={t} />
        </span>
      ),
      // Thẻ điện thoại: tên đăng nhập là dòng riêng dưới tên (xem cột "name")
      cardCell: () => null,
    },
    {
      key: "status",
      header: t.colStatus,
      className: "w-32",
      cell: (s) => <Badge variant={s.is_active ? "success" : "neutral"}>{s.is_active ? t.active : t.disabled}</Badge>,
      cardCell: () => null,
    },
    {
      key: "lastLogin",
      header: t.colLastLogin,
      className: "w-40 whitespace-nowrap tabular-nums",
      // Khung ~1024 (sidebar mở) không đủ 8 cột ⇒ ẩn cột này, vẫn xem ở ngăn chi tiết / thẻ điện thoại
      hideBelow: "xl",
      cell: (s) => (
        <span title={s.last_login_at ? formatDateTime(s.last_login_at) : undefined} className={dim(s)}>
          {lastLogin(s)}
        </span>
      ),
      // Thẻ điện thoại: đã gộp vào dòng 2 của cột "name"
      cardCell: () => null,
    },
    {
      key: "sessions",
      header: t.colSessions,
      align: "center",
      className: "w-28 tabular-nums",
      // ~1024 (sidebar mở) không đủ chỗ khi tên đăng nhập dài ⇒ ẩn (số thiết bị xem ở ngăn / menu ⋯)
      hideBelow: "xl",
      // Số thiết bị bấm được ⇒ ngăn chi tiết, cuộn tới mục thiết bị
      cell: (s) => (
        <button type="button" onClick={() => onAction("sessions", s)} aria-label={`${t.sessionsTitle}: ${s.active_sessions}`} className={cn("min-w-8 rounded-md px-2 py-1 font-semibold text-primary hover:bg-primary-softer focus-ring", dim(s))}>
          {s.active_sessions}
        </button>
      ),
      cardCell: () => null,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      className: "w-14",
      // Thẻ điện thoại: ⋯ nằm trong lưới của cột "name"
      cardCell: () => null,
      cell: (s) => <ActionMenu label={`${t.moreActions}: ${s.full_name}`} items={staffMenu(s, onAction, t)} />,
    },
  ];

  return (
    <DataTable
      caption={t.title}
      columns={columns}
      rows={rows}
      rowKey={(s) => String(s.id)}
      // Đã khóa: nền xám nhạt + nội dung mờ (xem DIM); dòng mở từ link `?ma=`: nền xanh nhạt
      rowClassName={(s) => cn("group/row", !s.is_active && "bg-background", s.staff_code === focusCode && "bg-primary-softer") || undefined}
      onRowClick={(s) => onAction("detail", s)}
      // Tiêu đề bảng dính dưới header admin khi cuộn (như Hội viên; bảng không cuộn ngang, cột phụ ẩn bằng hideBelow)
      stickyHeader
      empty={empty}
    />
  );
}
