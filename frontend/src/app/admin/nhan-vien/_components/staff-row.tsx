import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import type { Staff } from "@/lib/api/server";
import { cn } from "@/lib/cn";
import { formatDate, formatTime } from "@/lib/format";
import { type StaffTexts, useStaffSubmit } from "./staff-form-kit";
import { RenameForm, ResetPasswordForm } from "./staff-forms";
import { StaffSessions } from "./staff-sessions";

type OpenPanel = "name" | "password" | "sessions";

type Props = {
  t: StaffTexts;
  staff: Staff;
  /** Dòng được mở từ link `?ma=`: tô nổi + aria-current. */
  isFocused?: boolean;
  onChanged: () => void;
  onNotice: (text: string) => void;
};

// Hết 5 giây không bấm lần hai thì nút "Khóa" trở lại như cũ
const LOCK_CONFIRM_MS = 5000;
// Cột của dòng, dùng chung với hàng tiêu đề bảng
export const STAFF_COLUMNS =
  "md:grid-cols-[minmax(0,0.6fr)_minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)]";

export function StaffRow({ t, staff, isFocused = false, onChanged, onNotice }: Props) {
  const [panel, setPanel] = useState<OpenPanel | null>(null);
  const [isLockArmed, setIsLockArmed] = useState(false);
  const { isPending, error, setError, submit } = useStaffSubmit(t);

  useEffect(() => {
    if (!isLockArmed) return;
    const timer = setTimeout(() => setIsLockArmed(false), LOCK_CONFIRM_MS);
    return () => clearTimeout(timer);
  }, [isLockArmed]);

  const toggle = (next: OpenPanel) => {
    setPanel((current) => (current === next ? null : next));
    setError(null);
  };

  async function setActive(isActive: boolean) {
    // Khóa: xác nhận 2 bước tại nút (không dùng window.confirm vì chạy trong webview)
    if (!isActive && !isLockArmed) return setIsLockArmed(true);
    setIsLockArmed(false);
    const path = { staff_id: staff.id };
    const ok = await submit(() =>
      api.PATCH("/api/v1/admin/staff/{staff_id}", { params: { path }, body: { is_active: isActive } }),
    );
    if (ok) onChanged();
  }

  const panelLabels: Record<OpenPanel, string> = {
    name: t.editName,
    password: t.resetPassword,
    sessions: t.sessions.replace("{n}", String(staff.active_sessions)),
  };

  const done = () => {
    setPanel(null);
    onChanged();
  };

  return (
    <li
      id={`nhan-vien-${staff.staff_code}`}
      tabIndex={isFocused ? -1 : undefined}
      aria-current={isFocused ? "true" : undefined}
      className={cn(
        "flex flex-col gap-3 p-4 outline-none",
        // Viền trái primary + nền nhạt: chỉ dòng được mở từ link
        isFocused && "border-l-4 border-l-primary bg-primary-softer",
      )}
    >
      <div className={cn("grid grid-cols-2 gap-3 md:items-center md:gap-4", STAFF_COLUMNS)}>
        <Cell label={t.colCode}>
          <span className="font-semibold tabular-nums">{staff.staff_code}</span>
        </Cell>
        {/* Điện thoại: tên lên đầu thẻ; máy tính: sau cột Mã */}
        <div className="order-first col-span-2 min-w-0 md:order-none md:col-span-1">
          <p className="truncate font-semibold">{staff.full_name}</p>
          <p className="truncate text-ui text-muted">
            {staff.username} · {t.createdAt.replace("{date}", formatDate(staff.created_at))}
          </p>
        </div>
        <Cell label={t.colStatus}>
          <span className={cn("font-semibold", staff.is_active ? "text-primary" : "text-danger")}>
            {staff.is_active ? t.active : t.disabled}
          </span>
        </Cell>
        <Cell label={t.colLastLogin}>
          <span className="tabular-nums">
            {staff.last_login_at
              ? `${formatTime(staff.last_login_at)} ${formatDate(staff.last_login_at)}`
              : t.never}
          </span>
        </Cell>
        <Cell label={t.colSessions}>
          <span className="tabular-nums">{staff.active_sessions}</span>
        </Cell>
      </div>

      <div className="flex flex-wrap gap-2">
        {(Object.keys(panelLabels) as OpenPanel[]).map((p) => (
          <Button
            key={p}
            type="button"
            variant="secondary"
            aria-expanded={panel === p}
            onClick={() => toggle(p)}
            className={cn(panel === p && "bg-primary-softer")}
          >
            {panelLabels[p]}
          </Button>
        ))}
        <Button
          type="button"
          variant="secondary"
          loading={isPending}
          onClick={() => setActive(!staff.is_active)}
          className={cn(
            staff.is_active && "border-danger text-danger",
            isLockArmed && "bg-danger-soft",
          )}
        >
          {staff.is_active ? (isLockArmed ? t.lockConfirm : t.lock) : t.unlock}
        </Button>
      </div>

      {error && <Alert variant="error">{error}</Alert>}

      {panel === "name" && (
        <RenameForm
          t={t}
          staffId={staff.id}
          initialName={staff.full_name}
          onCancel={() => setPanel(null)}
          onDone={done}
        />
      )}
      {panel === "password" && (
        <ResetPasswordForm
          t={t}
          staffId={staff.id}
          onCancel={() => setPanel(null)}
          onDone={() => {
            done();
            onNotice(t.resetDone);
          }}
        />
      )}
      {panel === "sessions" && <StaffSessions t={t} staffId={staff.id} onChanged={onChanged} />}
    </li>
  );
}

// Ô thông tin của dòng: nhãn hiện trên điện thoại, máy tính dùng hàng tiêu đề bảng
function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col text-ui">
      <span className="text-label text-muted md:sr-only">{label}</span>
      {children}
    </div>
  );
}
