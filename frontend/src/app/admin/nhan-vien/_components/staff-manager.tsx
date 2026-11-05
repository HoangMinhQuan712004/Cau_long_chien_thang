"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { Staff } from "@/lib/api/server";
import { cn } from "@/lib/cn";
import type { StaffTexts } from "./staff-form-kit";
import { StaffCreateForm } from "./staff-forms";
import { STAFF_COLUMNS, StaffRow } from "./staff-row";

type Props = {
  staff: Staff[];
  /** Mã NV trên URL (`?ma=`): cuộn tới, tô nổi và focus dòng đó. */
  focusCode: string | null;
  t: StaffTexts;
};

// Trang quản lý nhân viên; ghi xong thì refresh để lấy lại danh sách
export function StaffManager({ staff, focusCode, t }: Props) {
  const router = useRouter();
  const [isCreating, setIsCreating] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // Vừa tạo ⇒ khối sao chép tên đăng nhập (+ mật khẩu ngẫu nhiên), chỉ giữ trong bộ nhớ trang
  const [created, setCreated] = useState<{ staff: Staff; password: string | null } | null>(null);
  const focusId = staff.some((s) => s.staff_code === focusCode) ? `nhan-vien-${focusCode}` : null;

  // Mở từ link ⇒ đưa dòng ra giữa màn (tránh header dính) và focus để bàn phím / trình đọc màn hình bắt đầu từ đó
  useEffect(() => {
    const row = focusId ? document.getElementById(focusId) : null;
    row?.scrollIntoView({ block: "center" });
    row?.focus({ preventScroll: true });
  }, [focusId]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-bold sm:text-2xl">{t.title}</h1>
          <p className="max-w-prose text-ui text-muted">{t.intro}</p>
        </div>
        {!isCreating && (
          <Button
            type="button"
            onClick={() => {
              setIsCreating(true);
              setNotice(null);
              setCreated(null);
            }}
          >
            {t.add}
          </Button>
        )}
      </div>

      {notice && <Alert variant="info">{notice}</Alert>}
      {created && (
        <StaffCreated
          t={t}
          staff={created.staff}
          password={created.password}
          onClose={() => setCreated(null)}
        />
      )}

      {isCreating && (
        <Card className="p-4 sm:p-6">
          <StaffCreateForm
            t={t}
            onCancel={() => setIsCreating(false)}
            onDone={(staff, password) => {
              setIsCreating(false);
              setCreated({ staff, password });
              router.refresh();
            }}
          />
        </Card>
      )}

      {staff.length === 0 ? (
        <p className="text-muted">{t.empty}</p>
      ) : (
        <Card>
          <div
            aria-hidden
            className={cn(
              "hidden gap-4 border-b px-4 py-3 text-label font-semibold text-muted md:grid",
              STAFF_COLUMNS,
            )}
          >
            <span>{t.colCode}</span>
            <span>{t.colAccount}</span>
            <span>{t.colStatus}</span>
            <span>{t.colLastLogin}</span>
            <span>{t.colSessions}</span>
          </div>
          <ul className="flex flex-col divide-y">
            {staff.map((s) => (
              <StaffRow
                key={s.id}
                t={t}
                staff={s}
                isFocused={s.staff_code === focusCode}
                onChanged={() => router.refresh()}
                onNotice={setNotice}
              />
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

type StaffCreatedProps = {
  t: StaffTexts;
  staff: Staff;
  password: string | null;
  onClose: () => void;
};

// Khối sau khi tạo: mã + tên đăng nhập tự sinh để Admin sao chép gửi nhân viên
function StaffCreated({ t, staff, password, onClose }: StaffCreatedProps) {
  const [copyResult, setCopyResult] = useState<"copied" | "failed" | null>(null);

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopyResult("copied");
    } catch {
      setCopyResult("failed");
    }
  }

  return (
    <section
      aria-live="polite"
      className="flex flex-col gap-3 rounded-card border border-primary bg-primary-softer p-4"
    >
      <p className="font-semibold">
        {t.created.replace("{code}", staff.staff_code).replace("{username}", staff.username)}
      </p>
      <p className="text-ui text-muted">{t.createdHint}</p>
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        <Button type="button" onClick={() => copy(staff.username)}>
          {t.copy}
        </Button>
        {password && (
          <Button
            type="button"
            variant="secondary"
            onClick={() => copy(`${staff.username} / ${password}`)}
          >
            {t.copyWithPassword}
          </Button>
        )}
        <Button type="button" variant="secondary" onClick={onClose}>
          {t.close}
        </Button>
      </div>
      {copyResult && (
        <p role="status" className={copyResult === "copied" ? "text-ui text-primary" : "text-ui text-danger"}>
          {copyResult === "copied" ? t.copied : t.copyFailed}
        </p>
      )}
    </section>
  );
}
