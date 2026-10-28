import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthForm } from "@/components/auth/auth-form";
import { getDictionary } from "@/i18n/dictionaries";

export const metadata: Metadata = {
  title: "Đăng ký tài khoản",
  robots: { index: false },
};

export default function RegisterPage() {
  return (
    <div className="mx-auto max-w-sm space-y-6">
      <h1 className="text-2xl font-bold">Đăng ký tài khoản</h1>
      <Suspense>
        <RegisterForm />
      </Suspense>
    </div>
  );
}

async function RegisterForm() {
  const { passwordRules, login } = await getDictionary();
  return <AuthForm rules={passwordRules} login={login} />;
}
