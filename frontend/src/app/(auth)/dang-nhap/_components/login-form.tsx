"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { useResetOnHide } from "@/hooks/use-reset-on-hide";
import type { Dictionary } from "@/i18n/dictionaries";
import { memberDestination, googleSignIn, signIn } from "@/lib/api/auth";
import { destination, safeNext } from "@/lib/safe-next";
import { AuthTextLink } from "../../_components/auth-card";
import { GoogleSignIn } from "./google-sign-in";
import { LockedAlert, useLoginLock } from "./login-lock";

const REFRESH_TRIED_KEY = "login-refresh-at";

// Form đăng nhập chung Admin/nhân viên/khách, xong thì đi theo quyền
export function LoginForm({ t, canRestore }: { t: Dictionary["login"]; canRestore: boolean }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = safeNext(searchParams.get("next"), "");

  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Đổi key mỗi lần lỗi ⇒ trình đọc màn hình đọc lại dù câu trùng
  const [attempt, setAttempt] = useState(0);
  // ?ly-do=… ⇒ câu báo; tham số lạ bị bỏ qua
  const [notice, setNotice] = useState(() => {
    const reason = searchParams.get("ly-do") ?? "";
    return Object.hasOwn(t.reasons, reason) ? t.reasons[reason as keyof typeof t.reasons] : null;
  });
  // Backend chưa bật Google ⇒ nút thay thế báo "đang cấu hình"
  const [isGoogleOff, setIsGoogleOff] = useState(false);
  // Mật khẩu ban đầu hết hạn ⇒ link Quên mật khẩu điền sẵn SĐT vừa nhập
  const [expiredLogin, setExpiredLogin] = useState<string | null>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  useResetOnHide(() => {
    setIsPending(false);
    setLogin("");
    setPassword("");
    setError(null);
  });

  // Khách còn refresh token ⇒ khôi phục phiên, quay lại trang cũ
  // Chỉ thử một lần mỗi 30 giây: nếu trang đích lại đẩy về đây (phiên không dùng được) thì không lặp vô hạn.
  useEffect(() => {
    if (!canRestore) return;
    try {
      const last = Number(sessionStorage.getItem(REFRESH_TRIED_KEY) ?? 0);
      if (Date.now() - last < 30_000) return;
      sessionStorage.setItem(REFRESH_TRIED_KEY, String(Date.now()));
    } catch {
      // Trình duyệt chặn bộ nhớ ⇒ vẫn thử một lần
    }
    fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include" })
      .then(async (r) => r.ok && router.replace(await memberDestination(next)))
      .catch(() => {});
  }, [canRestore, next, router]);

  const { lock, remaining, start: startLock } = useLoginLock(() => {
    setError(null);
    // Đợi form mở khóa rồi mới focus
    setTimeout(() => passwordRef.current?.focus(), 0);
  });
  const isLocked = lock !== null;
  const trimmedLogin = login.trim();
  const canSubmit = trimmedLogin !== "" && password !== "" && !isPending && !isLocked;

  function handleResult(result: Awaited<ReturnType<typeof signIn>>) {
    if (result.ok) {
      const go = (to: string) => {
        router.replace(to);
        router.refresh();
      };
      // Hội viên đăng nhập lần đầu bằng mật khẩu = SĐT ⇒ bắt đổi mật khẩu trước
      if (result.mustChangePassword) go(next ? `/doi-mat-khau?next=${encodeURIComponent(next)}` : "/doi-mat-khau");
      else if (result.kind === "member") void memberDestination(next).then(go);
      else go(destination(result.kind, next));
      return;
    }
    setIsPending(false);
    if (result.code === "google_disabled") return setIsGoogleOff(true);
    setError(t.errors[result.code]);
    setExpiredLogin(result.code === "initial_expired" ? trimmedLogin : null);
    setAttempt((n) => n + 1);
    setNotice(null);
    setPassword("");
    if ((result.code === "E-002" || result.code === "E-008") && result.retryAfter) {
      startLock(result.retryAfter, result.code === "E-008" ? t.ipLockedCountdown : t.lockedCountdown);
      return;
    }
    passwordRef.current?.focus();
  }

  async function onSubmit(e: React.SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!canSubmit) return;
    setIsPending(true);
    setError(null);
    handleResult(await signIn({ login: trimmedLogin, password }));
  }

  async function onGoogle(credential: string) {
    setIsPending(true);
    setError(null);
    handleResult(await googleSignIn(credential));
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {lock ? (
        <LockedAlert key={attempt} lock={lock} seconds={remaining} minutesText={t.lockedMinutes} />
      ) : (
        error && (
          <Alert key={attempt} variant="error">
            {error}
            {expiredLogin !== null && (
              <>
                {" "}
                <Link
                  href={`/quen-mat-khau?sdt=${encodeURIComponent(expiredLogin)}`}
                  className="font-semibold underline focus-ring"
                >
                  {t.forgotPassword}
                </Link>
              </>
            )}
          </Alert>
        )
      )}
      {notice && <Alert variant="info">{notice}</Alert>}

      <Field label={t.loginLabel} htmlFor="login">
        <Input
          id="login"
          name="login"
          value={login}
          onChange={(e) => setLogin(e.target.value)}
          readOnly={isPending}
          disabled={isLocked}
          placeholder={t.loginPlaceholder}
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          required
        />
      </Field>

      <Field label={t.passwordLabel} htmlFor="password">
        <PasswordInput
          ref={passwordRef}
          id="password"
          name="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          readOnly={isPending}
          disabled={isLocked}
          placeholder={t.passwordPlaceholder}
          showLabel={t.showPassword}
          hideLabel={t.hidePassword}
          autoComplete="current-password"
          required
        />
      </Field>

      <Button type="submit" block loading={isPending} disabled={!canSubmit}>
        {isPending ? t.submitting : t.submit}
      </Button>

      <AuthTextLink href="/quen-mat-khau">{t.forgotPassword}</AuthTextLink>

      <GoogleSignIn
        onCredential={onGoogle}
        disabled={isPending || isLocked}
        isServerDisabled={isGoogleOff}
        t={t.google}
      />

      <p className="text-ui text-muted">
        {t.noAccount}{" "}
        <Link
          href={next ? `/dang-ky?next=${encodeURIComponent(next)}` : "/dang-ky"}
          className="font-semibold text-primary focus-ring hover:underline"
        >
          {t.register}
        </Link>
      </p>
    </form>
  );
}
