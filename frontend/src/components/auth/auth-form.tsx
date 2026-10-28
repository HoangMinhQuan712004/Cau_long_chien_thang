"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { api, errorMessage } from "@/lib/api/client";
import { destination, safeNext } from "@/lib/safe-next";
import { isPasswordValid, PASSWORD_MAX, PasswordRules, type PasswordRulesTexts } from "./password-rules";

const input = "w-full rounded-md border border-border bg-surface px-3 py-2";

/** Đăng ký tài khoản khách (đăng nhập dùng màn chung /dang-nhap). */
export function AuthForm({ rules }: { rules: PasswordRulesTexts }) {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [password, setPassword] = useState("");

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setPending(true);
    setError(null);
    try {
      const { error } = await api.POST("/api/v1/auth/register", {
        body: {
          phone: String(f.get("phone")).trim(),
          password,
          full_name: String(f.get("full_name")),
        },
      });
      if (error) return setError(errorMessage(error));
      // Khách mới không vào khu quản trị dù ?next=/admin…
      router.replace(destination("customer", next));
      router.refresh();
    } catch {
      setError("Không kết nối được máy chủ, vui lòng thử lại");
    } finally {
      setPending(false);
    }
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
      <button
        disabled={pending || !isPasswordValid(password)}
        className="w-full rounded-md bg-primary py-2.5 font-medium text-surface disabled:opacity-50"
      >
        {pending ? "Đang xử lý…" : "Tạo tài khoản"}
      </button>
      <p className="text-center text-sm text-muted">
        Đã có tài khoản?{" "}
        <Link href={`/dang-nhap?next=${encodeURIComponent(next)}`} className="text-primary">
          Đăng nhập
        </Link>
      </p>
    </form>
  );
}
