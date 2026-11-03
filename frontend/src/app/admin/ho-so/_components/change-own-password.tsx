"use client";

import { useState } from "react";
import { isConfirmed, NewPasswordFields } from "@/components/auth/new-password-fields";
import { isPasswordValid, PASSWORD_MAX, type PasswordRulesTexts } from "@/components/auth/password-rules";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, fieldErrorId } from "@/components/ui/field";
import { PasswordInput } from "@/components/ui/password-input";
import type { Dictionary } from "@/i18n/dictionaries";
import { api, errorDetail, errorMessage } from "@/lib/api/client";
import { toast } from "@/lib/feedback";
import { FORM_ACTIONS, useCloseSheet } from "./profile-sheet";

// Mật khẩu hiện tại sai
const WRONG_CURRENT = "E-AUTH-28";

/** Bảng "Đổi mật khẩu": mật khẩu hiện tại + mới (quy tắc như màn khách). Xong ⇒ toast + đóng bảng; Hủy ⇒ đóng bảng. */
export function ChangeOwnPassword({ t, rules }: { t: Dictionary["adminProfile"]; rules: PasswordRulesTexts }) {
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentError, setCurrentError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const close = useCloseSheet();
  const canSubmit = current !== "" && isPasswordValid(password) && isConfirmed(password, confirm) && !isPending;

  async function onSubmit(e: React.SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!canSubmit) return;
    setIsPending(true);
    setError(null);
    setCurrentError(null);
    setPasswordError(null);
    try {
      const { error: err, response } = await api.POST("/api/v1/admin/account/password", {
        body: { current_password: current, new_password: password },
      });
      if (response.ok) {
        toast(t.done, t.doneSub);
        close();
        return;
      }
      // 401 hết phiên: middleware của client đã chuyển về màn đăng nhập
      if (response.status === 400 && errorDetail(err).code === WRONG_CURRENT) setCurrentError(errorMessage(err, t.currentWrong));
      else if (response.status === 422) setPasswordError(errorMessage(err, t.unavailable));
      else if (response.status !== 401) setError(errorMessage(err, t.unavailable));
    } catch {
      setError(t.network);
    } finally {
      setIsPending(false);
    }
  }

  // Bảng đóng ⇒ form bị gỡ khỏi DOM nên mở lại luôn trống
  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {error ? <Alert variant="error">{error}</Alert> : null}
          <Field label={t.currentLabel} htmlFor="current-password" error={currentError}>
            <PasswordInput
              id="current-password"
              value={current}
              onChange={(e) => {
                setCurrent(e.target.value);
                setCurrentError(null);
              }}
              readOnly={isPending}
              showLabel={t.showPassword}
              hideLabel={t.hidePassword}
              autoComplete="current-password"
              maxLength={PASSWORD_MAX}
              required
              autoFocus
              aria-invalid={currentError ? true : undefined}
              aria-describedby={currentError ? fieldErrorId("current-password") : undefined}
            />
          </Field>
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
          <div className={FORM_ACTIONS}>
            <Button type="submit" loading={isPending} disabled={!canSubmit}>{isPending ? t.submitting : t.submit}</Button>
            <Button type="button" variant="secondary" onClick={close} disabled={isPending}>{t.cancel}</Button>
          </div>
    </form>
  );
}
