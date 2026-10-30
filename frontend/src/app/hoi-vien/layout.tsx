import type { Metadata } from "next";
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { FeedbackHost } from "@/components/feedback/feedback-host";
import { MemberShell } from "@/components/member-area/member-shell";
import { getMemberMe, readCurrentUser } from "@/lib/api/server";
import { safeNext } from "@/lib/safe-next";

export const metadata: Metadata = {
  title: { default: "Khu hội viên", template: "%s | Khu hội viên" },
  robots: { index: false, follow: false },
};

export default function MemberAreaLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-full flex-1 flex-col bg-background">
      <Suspense fallback={<p className="p-8 text-center text-muted">Đang tải…</p>}>
        <Gate>{children}</Gate>
      </Suspense>
      <FeedbackHost />
    </div>
  );
}

/** Chỉ khách đã đăng nhập VÀ đã liên kết hồ sơ hội viên (ADR-009). Backend vẫn kiểm trên từng API. */
async function Gate({ children }: { children: React.ReactNode }) {
  // Phiên Admin/nhân viên không vào khu hội viên
  if ((await cookies()).has("admin_session")) redirect("/admin");

  // Tài khoản do sân tạo còn mật khẩu ban đầu (= SĐT) ⇒ đổi mật khẩu trước khi vào khu hội viên
  const { user, expired } = await readCurrentUser();
  if (expired) redirect("/quen-mat-khau");
  if (user?.must_change_password) redirect("/doi-mat-khau");

  const res = await getMemberMe();
  if (!res.ok) {
    // Đường dẫn đang mở do proxy.ts ghi vào header
    const path = safeNext((await headers()).get("x-pathname"), "/hoi-vien/ho-so");
    if (res.status === 401) redirect(`/dang-nhap?next=${encodeURIComponent(path)}&ly-do=het-han`);
    if (res.code === "E-AUTH-25") redirect("/doi-mat-khau");
    if (res.code === "E-AUTH-30") redirect("/quen-mat-khau");
    if (res.status === 403) redirect("/tai-khoan");
    return (
      <div className="mx-auto max-w-md p-8 text-center" role="alert">
        <p className="font-semibold">Không tải được hồ sơ. Vui lòng thử lại.</p>
        <a href={path} className="mt-4 inline-block rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-surface">
          Thử lại
        </a>
      </div>
    );
  }
  return <MemberShell initial={res.data}>{children}</MemberShell>;
}
