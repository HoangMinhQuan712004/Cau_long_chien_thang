import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthCard, AuthFormSkeleton } from "@/app/(auth)/_components/auth-card";
import { AuthForm } from "@/components/auth/auth-form";
import { getDictionary } from "@/i18n/dictionaries";

export const metadata: Metadata = {
  title: "Đăng ký tài khoản",
  robots: { index: false },
};

// Đăng ký trong khung chung các màn auth (hero xanh + thẻ nổi); URL /dang-ky giữ nguyên
export default function RegisterPage() {
  return (
    <AuthCard title="Đăng ký tài khoản" description="Tạo tài khoản để đặt sân nhanh và trở thành hội viên của sân.">
      <Suspense fallback={<AuthFormSkeleton fields={3} />}>
        <RegisterForm />
      </Suspense>
    </AuthCard>
  );
}

async function RegisterForm() {
  const { passwordRules, login, forgot } = await getDictionary();
  return <AuthForm rules={passwordRules} login={login} forgot={forgot} />;
}
