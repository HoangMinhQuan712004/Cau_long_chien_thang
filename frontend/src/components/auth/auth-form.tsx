"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, errorMessage } from "@/lib/api/client";
import { safeNext } from "@/lib/safe-next";

const input = "w-full rounded-md border border-border bg-surface px-3 py-2";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const next = safeNext(useSearchParams().get("next"));
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // Access token hết hạn nhưng refresh token còn -> khôi phục phiên, quay lại trang cũ
  useEffect(() => {
    if (mode !== "login") return;
    fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include" })
      .then((r) => r.ok && (window.location.href = next))
      .catch(() => {});
  }, [mode, next]);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const email = String(f.get("email"));
    const password = String(f.get("password"));
    setPending(true);
    setError(null);
    try {
      const { error } =
        mode === "login"
          ? await api.POST("/api/v1/auth/login", { body: { email, password } })
          : await api.POST("/api/v1/auth/register", {
              body: {
                email,
                password,
                full_name: String(f.get("full_name")),
                phone: String(f.get("phone") || "") || null,
              },
            });
      if (error) return setError(errorMessage(error));
      window.location.href = next;
    } catch {
      setError("Không kết nối được máy chủ, vui lòng thử lại");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {mode === "register" && (
        <>
          <label className="block space-y-1">
            <span className="text-sm font-medium">Họ tên</span>
            <input name="full_name" required autoComplete="name" className={input} />
          </label>
          <label className="block space-y-1">
            <span className="text-sm font-medium">Số điện thoại</span>
            <input name="phone" type="tel" autoComplete="tel" className={input} />
          </label>
        </>
      )}
      <label className="block space-y-1">
        <span className="text-sm font-medium">Email</span>
        <input name="email" type="email" required autoComplete="email" className={input} />
      </label>
      <label className="block space-y-1">
        <span className="text-sm font-medium">Mật khẩu</span>
        <input
          name="password"
          type="password"
          required
          minLength={mode === "register" ? 8 : undefined}
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          className={input}
        />
      </label>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <button
        disabled={pending}
        className="w-full rounded-md bg-primary py-2.5 font-medium text-white disabled:opacity-50"
      >
        {pending ? "Đang xử lý…" : mode === "login" ? "Đăng nhập" : "Tạo tài khoản"}
      </button>
      <p className="text-center text-sm text-muted">
        {mode === "login" ? (
          <>
            Chưa có tài khoản?{" "}
            <Link href={`/dang-ky?next=${encodeURIComponent(next)}`} className="text-primary">
              Đăng ký
            </Link>
          </>
        ) : (
          <>
            Đã có tài khoản?{" "}
            <Link href={`/dang-nhap?next=${encodeURIComponent(next)}`} className="text-primary">
              Đăng nhập
            </Link>
          </>
        )}
      </p>
    </form>
  );
}
