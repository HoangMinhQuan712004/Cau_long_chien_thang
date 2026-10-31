"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { PhoneVerify } from "@/components/booking/phone-verify";
import { Alert } from "@/components/ui/alert";
import { toast } from "@/lib/feedback";
import type { Dictionary } from "@/i18n/dictionaries";

// Luôn được dựng trên trang: sau khi xác minh server render lại với hasPhone=true nhưng state thông báo vẫn còn
// Tài khoản chưa có SĐT (đăng nhập Google): xác minh SĐT bằng OTP; trùng SĐT khách khác ⇒ gộp tài khoản (T-013 AC22)
export function AccountPhone({ t, hasPhone }: { t: Dictionary["phoneVerify"]; hasPhone: boolean }) {
  const router = useRouter();
  const [result, setResult] = useState<{ merged: boolean; passwordCleared: boolean; memberCode: string | null } | null>(null);

  if (result) {
    const [before, after] = t.passwordCleared.split("{link}");
    return (
      <div className="flex max-w-xl flex-col gap-3">
        <Alert variant="info">
          {result.merged ? t.merged : t.verified}
        </Alert>
        {result.memberCode && (
          <Alert variant="info">
            Bạn đã là hội viên {result.memberCode}.{" "}
            <Link href="/hoi-vien/ho-so" className="font-semibold underline">
              Vào khu hội viên
            </Link>
          </Alert>
        )}
        {result.passwordCleared && (
          <Alert variant="info">
            {before}
            <Link href="/quen-mat-khau" className="font-semibold underline">
              {t.forgotPassword}
            </Link>
            {after}
          </Alert>
        )}
      </div>
    );
  }

  if (hasPhone) return null;

  return (
    <PhoneVerify
      t={t}
      onVerified={(merged, passwordCleared, memberCode) => {
        if (memberCode) toast(`Bạn đã là hội viên ${memberCode}`);
        setResult({ merged, passwordCleared: Boolean(passwordCleared), memberCode: memberCode ?? null });
        router.refresh();
      }}
    />
  );
}
