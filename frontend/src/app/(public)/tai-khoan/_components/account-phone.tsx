"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { PhoneVerify } from "@/components/booking/phone-verify";
import { Alert } from "@/components/ui/alert";
import type { Dictionary } from "@/i18n/dictionaries";

// Tài khoản chưa có SĐT (đăng nhập Google): xác minh SĐT bằng OTP; trùng SĐT khách khác ⇒ gộp tài khoản (T-013 AC22)
export function AccountPhone({ t }: { t: Dictionary["phoneVerify"] }) {
  const router = useRouter();
  const [result, setResult] = useState<{ merged: boolean; passwordCleared: boolean } | null>(null);

  if (result) {
    const [before, after] = t.passwordCleared.split("{link}");
    return (
      <div className="flex max-w-xl flex-col gap-3">
        <Alert variant="info">
          {result.merged ? t.merged : t.verified}
        </Alert>
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

  return (
    <PhoneVerify
      t={t}
      onVerified={(merged, passwordCleared) => {
        setResult({ merged, passwordCleared: Boolean(passwordCleared) });
        router.refresh();
      }}
    />
  );
}
