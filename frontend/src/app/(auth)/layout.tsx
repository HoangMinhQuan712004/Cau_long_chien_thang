import { Suspense } from "react";
import { SiteLogo } from "@/components/site-logo";
import { getBranding } from "@/lib/api/server";
import { cn } from "@/lib/cn";

// Khung các màn đăng nhập / quên mật khẩu: logo + thẻ canh giữa, không header/footer
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main
      className={cn(
        "flex min-h-dvh flex-1 flex-col items-center justify-center-safe gap-6 px-4 py-safe",
      )}
    >
      <Suspense
        fallback={
          <div
            aria-hidden
            className="h-7.5 w-40 animate-pulse rounded-lg bg-background motion-reduce:animate-none"
          />
        }
      >
        <Brand />
      </Suspense>
      {children}
    </main>
  );
}

// Logo + tên sân
async function Brand() {
  const { name, logo_url: logoUrl } = await getBranding();
  return (
    <div className="flex max-w-full items-center gap-2.5 text-ui font-extrabold tracking-wide">
      <SiteLogo url={logoUrl} className="size-7.5" />
      <span className="truncate" title={name}>{name.toLocaleUpperCase("vi")}</span>
    </div>
  );
}
