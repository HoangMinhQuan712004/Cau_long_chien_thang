import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthForm } from "@/components/auth/auth-form";

export const metadata: Metadata = {
  title: "Đăng nhập",
  robots: { index: false },
};

export default function LoginPage() {
  return (
    <div className="mx-auto max-w-sm space-y-6">
      <h1 className="text-2xl font-bold">Đăng nhập</h1>
      <Suspense>
        <AuthForm mode="login" />
      </Suspense>
    </div>
  );
}
