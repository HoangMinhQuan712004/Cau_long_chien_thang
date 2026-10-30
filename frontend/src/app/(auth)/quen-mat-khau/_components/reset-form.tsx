"use client";

import { useState } from "react";
import { isConfirmed, NewPasswordFields } from "@/components/auth/new-password-fields";
import { isPasswordValid, type PasswordRulesTexts } from "@/components/auth/password-rules";
import { SuccessCheck } from "@/components/auth/success-check";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useResetOnHide } from "@/hooks/use-reset-on-hide";
import type { Dictionary } from "@/i18n/dictionaries";
import {
  confirmReset,
  otpErrorText,
  RESET_PHONE_KEY,
  RESET_RESEND_KEY,
  RESET_TOKEN_KEY,
  saveResetValue,
  useResetValue,
} from "@/lib/api/auth";
import { AuthTextLink } from "../../_components/auth-card";

// Đợi tick vẽ xong (~750ms) rồi mới chuyển trang
const REDIRECT_DELAY_MS = 1200;

// Màn 3: đặt mật khẩu mới bằng reset_token ⇒ tick "Đã đổi mật khẩu" ⇒ về màn đăng nhập trống
export function ResetForm({ t, rules }: { t: Dictionary["forgot"]; rules: PasswordRulesTexts }) {
  const token = useResetValue(RESET_TOKEN_KEY);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useResetOnHide(() => {
    setIsPending(false);
    setError(null);
    setPassword("");
    setConfirm("");
  });
  // Chưa qua màn 2 hoặc token hết hạn ⇒ làm lại từ đầu
  const [isExpired, setIsExpired] = useState(false);
  const isMissing = token === null || isExpired;
  const [isDone, setIsDone] = useState(false);

  async function onSubmit(e: React.SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!token) return;
    if (!isPasswordValid(password)) return setError(t.errors.passwordShort);
    if (password !== confirm) return setError(t.errors.passwordMismatch);
    setIsPending(true);
    setError(null);
    const result = await confirmReset(token, password);
    if (result.ok) {
      // Điều hướng cứng: không mang form đăng nhập cũ (Next giữ ẩn) quay lại
      setIsDone(true);
      [RESET_PHONE_KEY, RESET_TOKEN_KEY, RESET_RESEND_KEY].forEach((k) => saveResetValue(k, null));
      setTimeout(() => window.location.replace("/dang-nhap"), REDIRECT_DELAY_MS);
      return;
    }
    setIsPending(false);
    if (result.code === "reset_token_invalid") {
      saveResetValue(RESET_TOKEN_KEY, null);
      setIsExpired(true);
    }
    // 422 ở màn này là mật khẩu sai luật ⇒ câu của backend
    setError(
      result.code === "invalid" ? (result.message ?? t.errors.passwordInvalid) : otpErrorText(t.errors, result),
    );
  }

  // Trước `isMissing`: token vừa bị xóa khi thành công
  if (isDone) return <SuccessCheck label={t.reset.done} />;

  if (isMissing) {
    return (
      <div className="flex flex-col gap-4">
        <Alert variant="error">{error ?? t.errors.reset_token_invalid}</Alert>
        <AuthTextLink href="/quen-mat-khau">{t.reset.restart}</AuthTextLink>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {error && <Alert variant="error">{error}</Alert>}
      <NewPasswordFields
        password={password}
        confirm={confirm}
        onPassword={setPassword}
        onConfirm={setConfirm}
        isPending={isPending}
        disabled={token === undefined}
        t={{ ...t.reset, passwordMismatch: t.errors.passwordMismatch }}
        rules={rules}
      />
      <Button type="submit" block loading={isPending} disabled={!isPasswordValid(password) || !isConfirmed(password, confirm)}>
        {isPending ? t.reset.submitting : t.reset.submit}
      </Button>
      <AuthTextLink href="/dang-nhap">{t.backToLogin}</AuthTextLink>
    </form>
  );
}
