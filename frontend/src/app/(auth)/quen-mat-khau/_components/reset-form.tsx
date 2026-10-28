"use client";

import { useState } from "react";
import {
  isPasswordValid,
  PASSWORD_MAX,
  PasswordRules,
  type PasswordRulesTexts,
} from "@/components/auth/password-rules";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { AlertCircleIcon, CheckCircleIcon } from "@/components/ui/icons";
import { PasswordInput } from "@/components/ui/password-input";
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
import { cn } from "@/lib/cn";
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

  // So khớp nguyên văn, không trim
  const isMatch = confirm !== "" && confirm === password;
  const isMismatch = confirm !== "" && !isMatch;

  const fieldProps = {
    readOnly: isPending,
    disabled: token === undefined,
    showLabel: t.reset.showPassword,
    hideLabel: t.reset.hidePassword,
    autoComplete: "new-password",
    maxLength: PASSWORD_MAX,
    required: true,
  };

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {error && <Alert variant="error">{error}</Alert>}
      <Field label={t.reset.passwordLabel} htmlFor="new-password">
        <PasswordInput
          id="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-describedby="new-password-rules"
          {...fieldProps}
        />
        <PasswordRules id="new-password-rules" password={password} t={rules} />
      </Field>
      <Field label={t.reset.confirmLabel} htmlFor="confirm-password">
        <PasswordInput
          id="confirm-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          aria-invalid={isMismatch || undefined}
          aria-describedby="confirm-password-status"
          {...fieldProps}
        />
        <p
          id="confirm-password-status"
          aria-live="polite"
          className={cn("flex items-center gap-2 text-ui", isMatch ? "text-primary" : "text-danger")}
        >
          {isMatch && <CheckCircleIcon size={16} className="shrink-0" />}
          {isMismatch && <AlertCircleIcon size={16} className="shrink-0" />}
          {isMatch ? t.reset.passwordMatch : isMismatch ? t.errors.passwordMismatch : null}
        </p>
      </Field>
      <Button type="submit" block loading={isPending} disabled={!isPasswordValid(password) || !isMatch}>
        {isPending ? t.reset.submitting : t.reset.submit}
      </Button>
      <AuthTextLink href="/dang-nhap">{t.backToLogin}</AuthTextLink>
    </form>
  );
}

// Vòng tròn + dấu tick vẽ ra, báo đổi mật khẩu thành công
function SuccessCheck({ label }: { label: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-col items-center gap-3 py-6 text-primary"
    >
      <svg aria-hidden viewBox="0 0 52 52" className="size-16" fill="none" stroke="currentColor">
        <circle
          cx="26"
          cy="26"
          r="23"
          strokeWidth="3"
          strokeLinecap="round"
          pathLength="1"
          transform="rotate(-90 26 26)"
          className="animate-draw"
        />
        <path
          d="M15 27l7.5 7.5L37.5 19"
          strokeWidth="4"
          strokeLinecap="round"
          strokeLinejoin="round"
          pathLength="1"
          style={{ animationDelay: "350ms" }}
          className="animate-draw"
        />
      </svg>
      <p className="font-semibold text-foreground">{label}</p>
    </div>
  );
}
