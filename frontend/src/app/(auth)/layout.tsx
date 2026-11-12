import { Suspense } from "react";
import { FeedbackHost } from "@/components/feedback/feedback-host";
import { NetMesh } from "@/components/net-mesh";
import { cn } from "@/lib/cn";
import { BrandPanel } from "./_components/brand-panel";

// Khung các màn đăng nhập / đăng ký / quên mật khẩu / OTP / đặt lại – đổi mật khẩu (không header / footer), mọi khổ màn
// cùng kiểu: cả trang nền xanh thương hiệu, logo + tên app trên cùng, thẻ form trắng canh giữa bên dưới.
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main data-fluid-text className="
      relative isolate flex min-h-dvh flex-1 flex-col overflow-hidden bg-appbar
    ">
      {/* Nền mắt lưới cầu lông mờ 2 đầu – giống banner khu hội viên (người dùng 12/11) */}
      <NetMesh />
      <Suspense fallback={<div aria-hidden className="h-44 sm:h-52" />}>
        <BrandPanel />
      </Suspense>
      <div
        className={cn(
          "flex flex-1 items-start justify-center px-4",
          "pb-[calc(env(safe-area-inset-bottom)+1.5rem)] sm:pb-12",
        )}
      >
        {children}
      </div>
      <FeedbackHost />
    </main>
  );
}
