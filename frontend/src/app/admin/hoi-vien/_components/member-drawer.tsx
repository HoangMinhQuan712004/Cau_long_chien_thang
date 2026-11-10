"use client";

import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CalendarIcon, CalendarPlusIcon, ClockIcon, IdCardIcon, InboxIcon, PencilIcon, PhoneIcon, RacketIcon, UserIcon } from "@/components/ui/icons";
import { SidePanel } from "@/components/ui/side-panel";
import { Skeleton } from "@/components/ui/skeleton";
import type { Dictionary } from "@/i18n/dictionaries";
import type { MemberDetail } from "@/lib/api/server";
import { cn } from "@/lib/cn";
import { formatDayMonthYear, formatNumber, vnDate } from "@/lib/format";
import { staggerStyle } from "@/lib/motion";
import { formatPhone } from "@/lib/phone";
import { MemberRecentBookings } from "./member-recent-bookings";
import { useMemberDetail } from "./use-member-detail";

type Props = {
  memberRef: string;
  onClose: () => void;
  /** "Sửa hội viên" ⇒ mở P5b với chi tiết đã tải (không gọi API lần nữa). */
  onEdit: (detail: MemberDetail) => void;
  t: Dictionary["members"];
};

/** Drawer chi tiết hội viên (Figma P5c): thông tin, 2 thẻ số, 5 lượt đặt gần nhất. Điện thoại: toàn màn. */
export function MemberDrawer({ memberRef, onClose, onEdit, t }: Props) {
  const d = t.drawer;
  const state = useMemberDetail(memberRef);
  const detail = state.status === "ok" ? state.detail : null;

  return (
    <SidePanel
      title={d.title}
      closeLabel={d.close}
      onClose={onClose}
      resizeLabel={d.resize}
      storageKey="hoi-vien.chi-tiet.rong"
      status={state.status}
      loadingLabel={t.form.loading}
      errorText={t.form.loadError}
      skeleton={<DetailSkeleton />}
      footer={
        detail ? (
          <Button onClick={() => onEdit(detail)}>
            <PencilIcon />
            {detail.kind === "member" ? d.edit : d.editTemp}
          </Button>
        ) : undefined
      }
    >
      {detail ? <DetailBody detail={detail} t={t} /> : null}
    </SidePanel>
  );
}

// Khung tải đúng hình phần chi tiết: tên + dòng hạng, các mục thông tin, 2 số liệu
function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-3">
        <Skeleton className="size-11 shrink-0 rounded-full sm:size-14" />
        <div className="flex flex-1 flex-col gap-2">
          <Skeleton className="h-7 w-48 max-w-full" />
          <Skeleton className="h-4 w-36" />
        </div>
      </div>
      <div className="flex flex-col gap-3">
        {["w-24", "w-32", "w-28", "w-20"].map((w) => (
          <div key={w} className="flex gap-4">
            <Skeleton className="h-4 w-24" />
            <Skeleton className={cn("h-4", w)} />
          </div>
        ))}
      </div>
      <div className={INFO_GRID}>
        {[0, 1].map((i) => (
          <div key={i} className="flex flex-col gap-1.5">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-7 w-12" />
          </div>
        ))}
      </div>
    </div>
  );
}

// Lưới nhãn | giá trị dùng chung cho thông tin và số liệu ⇒ các cột thẳng nhau
const INFO_GRID = "grid grid-cols-[minmax(0,8rem)_1fr] gap-x-4 sm:grid-cols-[minmax(0,9rem)_1fr]";

function DetailBody({ detail, t }: { detail: MemberDetail; t: Dictionary["members"] }) {
  const d = t.drawer;
  type Row = [string, string, React.ReactNode];
  const isMember = detail.kind === "member";
  const info: Row[] = [
    // Biệt danh / email hội viên tự nhập ở khu hội viên (chỉ xem); hồ sơ tạm không có tài khoản nên bỏ
    ...(isMember ? [[d.nickname, detail.nickname ?? "—", <IdCardIcon key="i" size={16} />] as Row] : []),
    // SĐT đầy đủ (người dùng chốt; mở drawer đã ghi nhật ký xem); bảng danh sách vẫn che
    [d.phone, formatPhone(detail.phone), <PhoneIcon key="i" size={16} />],
    ...(isMember ? [[d.email, detail.email ?? "—", <InboxIcon key="i" size={16} />] as Row] : []),
    [d.gender, detail.gender ? t.form.genders[detail.gender] : "—", <UserIcon key="i" size={16} />],
    // Hồ sơ tạm không có vợt / hạng / trạng thái
    ...(isMember ? [[d.racket, detail.racket ?? "—", <RacketIcon key="i" size={16} />] as Row] : []),
    [d.created, formatDayMonthYear(vnDate(detail.created_at)), <CalendarIcon key="i" size={16} />],
    // T-021: hội viên tự đăng ký trên web (AC9)
    ...(isMember
      ? [[d.createdBy, detail.source === "self_register" ? d.sourceSelf : d.sourceCounter, <UserIcon key="i" size={16} />] as Row]
      : []),
  ];
  const hours = Math.round((detail.total_minutes / 60) * 10) / 10;
  const stats: [string, string, React.ReactNode][] = [
    [d.bookings, formatNumber(detail.bookings), <CalendarPlusIcon key="i" size={16} />],
    [d.totalHours, d.hours.replace("{n}", formatNumber(hours)), <ClockIcon key="i" size={16} />],
  ];
  // Các khối hiện lần lượt
  const enter = (i: number) => ({ style: staggerStyle(i), className: "animate-slide-up stagger" });

  return (
    <div className="flex flex-col gap-4 sm:gap-5">
      <div {...enter(0)}>
        <div className="flex items-center gap-3">
          <Avatar name={detail.full_name} url={detail.avatar_url} />
          <div className="flex min-w-0 flex-col gap-0.5 sm:gap-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <p className="text-base font-bold wrap-break-word sm:text-xl">{detail.full_name}</p>
              {detail.kind === "member" ? (
                <Badge variant={detail.is_active ? "success" : "neutral"}>
                  {detail.is_active ? t.statuses.active : t.statuses.inactive}
                </Badge>
              ) : (
                <Badge variant="warning">{t.kinds.temp}</Badge>
              )}
            </div>
            {detail.member_code ? (
              <p className="text-xs text-muted sm:text-sm">
                {(detail.tier ? d.tierLine.replace("{tier}", detail.tier) : d.tierLineNone).replace("{code}", detail.member_code)}
              </p>
            ) : null}
          </div>
        </div>
      </div>

      {/* Thông tin: nhãn một bên, giá trị một bên (không khung) */}
      <div {...enter(1)}>
        <dl className={cn(INFO_GRID, "gap-y-2.5 text-ui sm:gap-y-3 sm:text-sm")}>
          {info.map(([label, value, icon]) => (
            <div key={label} className="contents">
              <dt className="flex items-center gap-2 text-muted">
                <span aria-hidden className="shrink-0 [&_svg]:size-3.5 sm:[&_svg]:size-4">
                  {icon}
                </span>
                {label}
              </dt>
              <dd className="min-w-0 font-medium wrap-break-word tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      </div>

      {/* Số liệu đứng cạnh nhau, cùng lưới cột với phần thông tin ⇒ "Tổng giờ" thẳng cột giá trị */}
      <div {...enter(2)}>
        <dl className={INFO_GRID}>
          {stats.map(([label, value, icon]) => (
            <div key={label} className="flex min-w-0 flex-col gap-0.5">
              <dt className="flex items-center gap-2 text-xs text-muted sm:text-ui">
                <span aria-hidden className="shrink-0 [&_svg]:size-3.5 sm:[&_svg]:size-4">
                  {icon}
                </span>
                {label}
              </dt>
              <dd className="text-xl font-bold tabular-nums sm:text-2xl">{value}</dd>
            </div>
          ))}
        </dl>
      </div>

      <div {...enter(3)}>
        <MemberRecentBookings bookings={detail.recent_bookings} t={d} />
      </div>
    </div>
  );
}
