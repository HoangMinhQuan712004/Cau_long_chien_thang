"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { isConfirmed, NewPasswordFields } from "@/components/auth/new-password-fields";
import { isPasswordValid, type PasswordRulesTexts } from "@/components/auth/password-rules";
import { SuccessCheck } from "@/components/auth/success-check";
import { LogoutButton } from "@/components/logout-button";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { Dictionary } from "@/i18n/dictionaries";
import { INITIAL_PASSWORD_EXPIRED } from "@/lib/api/auth";
import { changeInitialPassword } from "@/lib/api/password-change";
import { cn } from "@/lib/cn";
import { destination, safeNext } from "@/lib/safe-next";

// Đợi tick vẽ xong rồi mới chuyển trang
const REDIRECT_DELAY_MS = 1200;

/** Đổi mật khẩu lần đầu (hội viên đăng nhập bằng mật khẩu = SĐT) ⇒ tick ⇒ về ?next (nếu có) hoặc khu hội viên. Đăng xuất vẫn được. */
export function ChangePasswordForm({
  t,
  rules,
  phone,
}: {
  t: Dictionary["changePassword"];
  rules: PasswordRulesTexts;
  /** SĐT tài khoản: mật khẩu ban đầu hết hạn ⇒ sang Quên mật khẩu điền sẵn số này. */
  phone: string | null;
}) {
  const next = safeNext(useSearchParams().get("next"), "");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Lỗi 422 (trùng SĐT, sai quy tắc) hiện ngay dưới ô mật khẩu mới
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [isDone, setIsDone] = useState(false);
  const canSubmit = isPasswordValid(password) && isConfirmed(password, confirm) && !isPending;

  async function onSubmit(e: React.SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!canSubmit) return;
    setIsPending(true);
    setError(null);
    setPasswordError(null);
    const result = await changeInitialPassword(password);
    if (result.ok) {
      setIsDone(true);
      // Điều hướng cứng: tải lại trang khách với phiên mới, không giữ trang bị chặn cũ
      setTimeout(() => window.location.replace(destination("member", next, "/hoi-vien")), REDIRECT_DELAY_MS);
      return;
    }
    setIsPending(false);
    if (result.status === 401) return window.location.replace("/dang-nhap?next=/doi-mat-khau");
    if (result.code === INITIAL_PASSWORD_EXPIRED) {
      return window.location.replace(phone ? `/quen-mat-khau?sdt=${encodeURIComponent(phone)}` : "/quen-mat-khau");
    }
    if (result.status === 422 && result.message) return setPasswordError(result.message);
    setError(result.status ? (result.message ?? t.errors.unavailable) : t.errors.network);
  }

  if (isDone) return <SuccessCheck label={t.done} />;

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {error && <Alert variant="error">{error}</Alert>}
      <NewPasswordFields
        password={password}
        confirm={confirm}
        onPassword={(value) => {
          setPassword(value);
          setPasswordError(null);
        }}
        onConfirm={setConfirm}
        isPending={isPending}
        passwordError={passwordError}
        t={t}
        rules={rules}
      />
      <Button type="submit" block loading={isPending} disabled={!canSubmit}>
        {isPending ? t.submitting : t.submit}
      </Button>
      <div className="flex justify-center">
        <LogoutButton className={cn(`
          -my-2 rounded-sm p-2 text-ui font-semibold text-muted focus-ring
          hover:text-danger
          disabled:opacity-50
        `)}>
          {t.logout}
        </LogoutButton>
      </div>
    </form>
  );
}
