"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { GoogleSignIn } from "@/app/(auth)/dang-nhap/_components/google-sign-in";
import type { Dictionary } from "@/i18n/dictionaries";
import { googleSignIn } from "@/lib/api/auth";
import { api, errorDetail, errorMessage } from "@/lib/api/client";
import { destination, safeNext } from "@/lib/safe-next";
import { isPasswordValid, PASSWORD_MAX, PasswordRules, type PasswordRulesTexts } from "./password-rules";

const input = "w-full rounded-md border border-border bg-surface px-3 py-2";

/** Đăng ký tài khoản khách (đăng nhập dùng màn chung /dang-nhap). */
export function AuthForm({ rules, login }: { rules: PasswordRulesTexts; login: Dictionary["login"] }) {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [password, setPassword] = useState("");
  const [isGoogleOff, setIsGoogleOff] = useState(false);
  // E-AUTH-22: SĐT đã có tài khoản ⇒ câu của BE + link Đăng nhập / Quên mật khẩu
  const [taken, setTaken] = useState<{ message: string; phone: string } | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setPending(true);
    setError(null);
    setTaken(null);
    try {
      const { error } = await api.POST("/api/v1/auth/register", {
        body: {
          phone: String(f.get("phone")).trim(),
          password,
          full_name: String(f.get("full_name")),
        },
      });
      if (error) {
        const detail = errorDetail(error) as { code?: string; phone?: string };
        if (detail.code === "E-AUTH-22") {
          return setTaken({ message: errorMessage(error), phone: detail.phone ?? String(f.get("phone")).trim() });
        }
        return setError(errorMessage(error));
      }
      // Khách mới không vào khu quản trị dù ?next=/admin…
      router.replace(destination("member", next));
      router.refresh();
    } catch {
      setError("Không kết nối được máy chủ, vui lòng thử lại");
    } finally {
      setPending(false);
    }
  }

  // Khách đăng ký/đăng nhập bằng Google (tạo tài khoản khách nếu chưa có)
  async function onGoogle(credential: string) {
    setPending(true);
    setError(null);
    const result = await googleSignIn(credential);
    if (result.ok) {
      router.replace(destination("member", next));
      router.refresh();
      return;
    }
    setPending(false);
    if (result.code === "google_disabled") return setIsGoogleOff(true);
    setError(login.errors[result.code as keyof typeof login.errors] ?? login.errors.unavailable);
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <label className="block space-y-1">
        <span className="text-sm font-medium">Họ tên</span>
        <input name="full_name" required autoComplete="name" className={input} />
      </label>
      <label className="block space-y-1">
        <span className="text-sm font-medium">Số điện thoại</span>
        <input name="phone" type="tel" required autoComplete="tel" className={input} />
      </label>
      <label className="block space-y-1">
        <span className="text-sm font-medium">Mật khẩu</span>
        <input
          name="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          maxLength={PASSWORD_MAX}
          autoComplete="new-password"
          aria-describedby="register-password-rules"
          className={input}
        />
      </label>
      <PasswordRules id="register-password-rules" password={password} t={rules} />
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      {taken && <PhoneTaken message={taken.message} phone={taken.phone} t={login.phoneTaken} />}
      <button
        disabled={pending || !isPasswordValid(password)}
        className="w-full rounded-md bg-primary py-2.5 font-medium text-surface disabled:opacity-50"
      >
        {pending ? "Đang xử lý…" : "Tạo tài khoản"}
      </button>
      <GoogleSignIn onCredential={onGoogle} disabled={pending} isServerDisabled={isGoogleOff} t={login.google} />
      <p className="text-center text-sm text-muted">
        Đã có tài khoản?{" "}
        <Link href={`/dang-nhap?next=${encodeURIComponent(next)}`} className="text-primary">
          Đăng nhập
        </Link>
      </p>
    </form>
  );
}

// SĐT đã có tài khoản (mọi loại – không lộ là hội viên hay không): câu của BE + Đăng nhập / Quên mật khẩu
function PhoneTaken({ message, phone, t }: { message: string; phone: string; t: Dictionary["login"]["phoneTaken"] }) {
  const query = phone ? `?sdt=${encodeURIComponent(phone)}` : "";
  return (
    <div role="alert" className="flex flex-col gap-2 rounded-lg border border-danger/30 bg-danger-soft p-3 text-sm">
      <p>{message}</p>
      <p className="flex flex-wrap gap-x-4 gap-y-1 font-semibold">
        <Link href="/dang-nhap" className="rounded-sm text-primary focus-ring hover:underline">
          {t.login}
        </Link>
        <Link href={`/quen-mat-khau${query}`} className="rounded-sm text-primary focus-ring hover:underline">
          {t.forgot}
        </Link>
      </p>
    </div>
  );
}
