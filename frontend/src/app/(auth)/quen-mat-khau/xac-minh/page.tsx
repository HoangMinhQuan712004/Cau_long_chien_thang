import type { Metadata } from "next";
import { Suspense } from "react";
import { getDictionary } from "@/i18n/dictionaries";
import { AuthCard, AuthFormSkeleton, forgotSteps as steps } from "../../_components/auth-card";
import { VerifyForm } from "../_components/forgot-forms";

export async function generateMetadata(): Promise<Metadata> {
  const t = (await getDictionary()).forgot.verify;
  return { title: t.metaTitle, robots: { index: false, follow: false } };
}

export default function VerifyPage() {
  return (
    <Suspense fallback={<AuthCard><AuthFormSkeleton /></AuthCard>}>
      <VerifyCard />
    </Suspense>
  );
}

async function VerifyCard() {
  const t = (await getDictionary()).forgot;
  return (
    <AuthCard steps={steps(t, 2)} title={t.verify.title}>
      <VerifyForm t={t} />
    </AuthCard>
  );
}
