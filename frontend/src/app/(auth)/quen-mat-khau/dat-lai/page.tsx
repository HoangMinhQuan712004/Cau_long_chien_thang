import type { Metadata } from "next";
import { Suspense } from "react";
import { getDictionary } from "@/i18n/dictionaries";
import { AuthCard, AuthFormSkeleton } from "../../_components/auth-card";
import { ResetForm } from "../_components/reset-form";

export async function generateMetadata(): Promise<Metadata> {
  const t = (await getDictionary()).forgot.reset;
  return { title: t.metaTitle, robots: { index: false, follow: false } };
}

export default function ResetPage() {
  return (
    <Suspense fallback={<AuthCard><AuthFormSkeleton /></AuthCard>}>
      <ResetCard />
    </Suspense>
  );
}

async function ResetCard() {
  const dictionary = await getDictionary();
  const t = dictionary.forgot;
  return (
    <AuthCard title={t.reset.title} description={t.reset.description}>
      <ResetForm t={t} rules={dictionary.passwordRules} />
    </AuthCard>
  );
}
