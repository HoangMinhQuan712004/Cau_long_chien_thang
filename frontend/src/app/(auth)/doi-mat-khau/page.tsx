import type { Metadata } from "next";
import { Suspense } from "react";
import { getDictionary } from "@/i18n/dictionaries";
import { getCurrentUser } from "@/lib/api/server";
import { AuthCard, AuthFormSkeleton } from "../_components/auth-card";
import { ChangePasswordForm } from "./_components/change-password-form";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDictionary()).changePassword.metaTitle, robots: { index: false, follow: false } };
}

// Khách phải đổi mật khẩu lần đầu; thiếu phiên thì proxy đã đưa về /dang-nhap
export default function ChangePasswordPage() {
  return (
    <Suspense fallback={<AuthCard><AuthFormSkeleton fields={2} /></AuthCard>}>
      <ChangePasswordCard />
    </Suspense>
  );
}

async function ChangePasswordCard() {
  const [dictionary, user] = await Promise.all([getDictionary(), getCurrentUser()]);
  const t = dictionary.changePassword;
  return (
    <AuthCard title={t.title} description={t.description}>
      <ChangePasswordForm t={t} rules={dictionary.passwordRules} phone={user?.phone ?? null} />
    </AuthCard>
  );
}
