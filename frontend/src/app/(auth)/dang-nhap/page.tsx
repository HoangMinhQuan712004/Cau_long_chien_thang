import type { Metadata } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { getDictionary } from "@/i18n/dictionaries";
import { getAdminSession, readCurrentUser } from "@/lib/api/server";
import { destination, safeNext } from "@/lib/safe-next";
import { AuthCard, AuthFormSkeleton } from "../_components/auth-card";
import { LoginForm } from "./_components/login-form";

export async function generateMetadata(): Promise<Metadata> {
  const t = (await getDictionary()).login;
  return { title: t.metaTitle, robots: { index: false, follow: false } };
}

/** Một màn đăng nhập cho Admin, nhân viên và khách; đăng nhập xong đi theo quyền. */
export default function LoginPage({ searchParams }: PageProps<"/dang-nhap">) {
  const skeleton = <AuthFormSkeleton fields={2} />;
  return (
    <>
      <Suspense fallback={<AuthCard>{skeleton}</AuthCard>}>
        <LoginCard skeleton={skeleton} />
      </Suspense>
      <Suspense>
        <RedirectIfSignedIn searchParams={searchParams} />
      </Suspense>
    </>
  );
}

async function LoginCard({ skeleton }: { skeleton: React.ReactNode }) {
  const t = (await getDictionary()).login;
  // Chỉ thử khôi phục phiên khi trình duyệt còn refresh token (tránh 401 thừa trong console khi chưa đăng nhập)
  const canRestore = (await cookies()).has("refresh_token");
  return (
    <AuthCard title={t.title}>
      {/* Form đọc query (?next, ?ly-do) ⇒ cần Suspense riêng */}
      <Suspense fallback={skeleton}>
        <LoginForm t={t} canRestore={canRestore} />
      </Suspense>
    </AuthCard>
  );
}

/** Máy còn phiên thì vào thẳng khu tương ứng, không qua màn đăng nhập (SRS AF-3). */
async function RedirectIfSignedIn({ searchParams }: Pick<PageProps<"/dang-nhap">, "searchParams">) {
  const raw = (await searchParams).next;
  const next = safeNext(typeof raw === "string" ? raw : null, "");
  // Máy chủ không phản hồi thì vẫn hiện form, người dùng thử đăng nhập sau
  const admin = await getAdminSession().catch(() => null);
  if (admin?.ok) redirect(destination("admin", next));
  const { user } = await readCurrentUser();
  if (user) redirect(destination("member", next));
  return null;
}
