import type { Metadata } from "next";
import { Suspense } from "react";
import { getDictionary } from "@/i18n/dictionaries";
import { AuthCard, AuthFormSkeleton, forgotSteps as steps } from "../_components/auth-card";
import { RequestForm } from "./_components/forgot-forms";

export async function generateMetadata(): Promise<Metadata> {
  const t = (await getDictionary()).forgot.request;
  return { title: t.metaTitle, robots: { index: false, follow: false } };
}

export default function ForgotPasswordPage() {
  return (
    <Suspense fallback={<AuthCard><AuthFormSkeleton /></AuthCard>}>
      <ForgotCard />
    </Suspense>
  );
}

async function ForgotCard() {
  const t = (await getDictionary()).forgot;
  return (
    <AuthCard steps={steps(t, 1)} title={t.request.title} description={t.request.description}>
      <RequestForm t={t} />
    </AuthCard>
  );
}
