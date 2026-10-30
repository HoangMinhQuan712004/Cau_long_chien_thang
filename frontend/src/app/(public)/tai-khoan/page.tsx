import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { LogoutButton } from "@/components/logout-button";
import { Alert } from "@/components/ui/alert";
import { getDictionary } from "@/i18n/dictionaries";
import { getCurrentUser } from "@/lib/api/server";
import { phoneHref, site } from "@/lib/site";
import { AccountPhone } from "./_components/account-phone";

export const metadata: Metadata = {
  title: "Tài khoản của tôi",
  robots: { index: false, follow: false },
};

export default function AccountPage() {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <Account />
    </Suspense>
  );
}

async function Account() {
  const user = await getCurrentUser();
  if (!user) redirect("/dang-nhap?next=/tai-khoan");
  const dictionary = await getDictionary();
  const t = dictionary.account;
  // `is_member`: tài khoản đã liên kết hồ sơ hội viên (T-016); bản API cũ chưa có trường này ⇒ không hiện gì
  const isMember = (user as { is_member?: boolean }).is_member;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Xin chào, {user.full_name}</h1>
          <dl className="mt-2 space-y-1 text-sm text-muted">
            <div>
              <dt className="sr-only">Số điện thoại</dt>
              <dd>
                {user.phone ? (
                  <>
                    {user.phone}{" "}
                    <span className={user.phone_verified ? "font-medium text-primary" : "font-medium text-foreground"}>
                      · {user.phone_verified ? t.phoneVerified : t.phoneUnverified}
                    </span>
                  </>
                ) : (
                  t.noPhone
                )}
              </dd>
            </div>
            {user.username && (
              <div>
                <dt className="sr-only">Tên đăng nhập</dt>
                <dd>{t.username.replace("{username}", user.username)}</dd>
              </div>
            )}
            {user.google_email && (
              <div>
                <dt className="sr-only">Google</dt>
                <dd>{t.googleEmail.replace("{email}", user.google_email)}</dd>
              </div>
            )}
          </dl>
          {user.phone && !user.phone_verified && <p className="mt-2 max-w-prose text-sm text-muted">{t.phoneUnverifiedHint}</p>}
        </div>
        <LogoutButton />
      </div>

      <AccountPhone t={dictionary.phoneVerify} hasPhone={Boolean(user.phone)} />

      {isMember === true ? (
        <Alert variant="info">
          Bạn là hội viên.{" "}
          <Link href="/hoi-vien/ho-so" className="font-semibold underline">
            Vào khu hội viên
          </Link>
        </Alert>
      ) : isMember === false ? (
        <Alert variant="info">Bạn chưa là hội viên. Đăng ký hội viên tại quầy để dùng khu hội viên.</Alert>
      ) : null}

      <section className="rounded-card bg-surface p-4 shadow-card sm:p-6">
        <h2 className="text-lg font-semibold">Đặt sân</h2>
        <p className="mt-1 text-sm text-muted">
          Đặt sân online tại{" "}
          <Link href="/dat-san" className="font-medium text-primary">
            trang Đặt sân
          </Link>
          , tra cứu bằng mã booking và số điện thoại ở mục{" "}
          <Link href="/tra-cuu" className="font-medium text-primary">
            Tra cứu booking
          </Link>
          . Cần hỗ trợ, gọi{" "}
          <a href={phoneHref} className="font-medium text-primary">
            {site.phone}
          </a>
          .
        </p>
      </section>
    </div>
  );
}
