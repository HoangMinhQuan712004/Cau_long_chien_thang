"use client";

import { useEffect, useRef } from "react";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SidePanel } from "@/components/ui/side-panel";
import type { Staff } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import type { StaffTexts } from "./staff-form-kit";
import { StaffDevices, StaffLoginHistory } from "./staff-sessions";
import { relativeTime, shortDate, type StaffAction, Username } from "./staff-table";

// Ngăn chi tiết nhân viên (như Hội viên / chi tiết sân): thông tin, thiết bị đang đăng nhập (đăng xuất từng thiết bị),
// lịch sử đăng nhập; chân: Sửa tên · Đặt lại mật khẩu · Khóa / Mở khóa. Thông tin lấy từ danh sách, thiết bị / lịch sử tải riêng.

type Props = {
  staff: Staff;
  now: number;
  /** Mở từ số phiên / mục "Phiên đang mở" ⇒ cuộn tới mục phiên. */
  focusSessions: boolean;
  onClose: () => void;
  onAction: (action: StaffAction, staff: Staff) => void;
  /** Đăng xuất một phiên xong: cha tải lại (số phiên trên bảng). */
  onChanged: () => void;
  t: StaffTexts;
};

export function StaffDrawer({ staff: s, now, focusSessions, onClose, onAction, onChanged, t }: Props) {
  const sessionsRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (focusSessions) sessionsRef.current?.scrollIntoView({ block: "start" });
  }, [focusSessions, s.id]);

  const rows: [string, React.ReactNode][] = [
    [t.codeLabel, <span key="c" className="tabular-nums">{s.staff_code}</span>],
    [t.usernameLabel, <Username key="u" value={s.username} t={t} />],
    [t.createdLabel, <span key="d" className="tabular-nums">{shortDate(s.created_at)}</span>],
    [
      t.colLastLogin,
      s.last_login_at ? (
        <span key="l" className="tabular-nums">
          {formatDateTime(s.last_login_at)}
          <span className="block text-ui text-muted">{relativeTime(s.last_login_at, now, t)}</span>
        </span>
      ) : (
        t.never
      ),
    ],
  ];

  return (
    <SidePanel
      title={t.detailTitle}
      closeLabel={t.detailClose}
      onClose={onClose}
      resizeLabel={t.detailResize}
      storageKey="nhan-vien.chi-tiet.rong"
      footer={
        // Điện thoại: "Đặt lại mật khẩu" một hàng riêng (chữ dài), dưới là Sửa tên | Khóa; từ sm: 3 nút một hàng
        <div className="grid w-full grid-cols-2 gap-2 sm:grid-cols-3">
          <Button type="button" variant="secondary" block className="col-span-2 sm:order-2 sm:col-span-1" onClick={() => onAction("password", s)}>
            {t.resetPassword}
          </Button>
          <Button type="button" variant="secondary" block className="sm:order-1" onClick={() => onAction("rename", s)}>
            {t.editName}
          </Button>
          {s.is_active ? (
            <Button type="button" variant="secondary" block className="border-danger text-danger sm:order-3" onClick={() => onAction("lock", s)}>
              {t.lock}
            </Button>
          ) : (
            <Button type="button" block className="sm:order-3" onClick={() => onAction("unlock", s)}>
              {t.unlock}
            </Button>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-5">
        <div className="flex items-center gap-3">
          <Avatar name={s.full_name} />
          <div className="min-w-0">
            <p className="text-lg font-bold break-words">{s.full_name}</p>
            <Badge variant={s.is_active ? "success" : "neutral"}>{s.is_active ? t.active : t.disabled}</Badge>
          </div>
        </div>

        <dl className="grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 sm:grid-cols-[9rem_minmax(0,1fr)] gap-y-2 text-sm">
          {rows.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-ui text-muted">{k}</dt>
              <dd className="min-w-0 break-words">{v}</dd>
            </div>
          ))}
        </dl>

        <section ref={sessionsRef} aria-label={t.sessionsTitle} className="flex scroll-mt-4 flex-col gap-2 border-t pt-4">
          <h3 className="text-sm font-semibold">
            {t.sessionsTitle} <span className="font-normal text-muted tabular-nums">({s.active_sessions})</span>
          </h3>
          <StaffDevices key={s.id} t={t} staffId={s.id} onChanged={onChanged} />
        </section>

        <section aria-label={t.historyTitle} className="flex flex-col gap-1 border-t pt-4">
          <h3 className="text-sm font-semibold">{t.historyTitle}</h3>
          <StaffLoginHistory key={s.id} t={t} staffId={s.id} />
        </section>
      </div>
    </SidePanel>
  );
}
