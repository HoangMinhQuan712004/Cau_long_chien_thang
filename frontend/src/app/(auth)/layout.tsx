import { Suspense } from "react";
import { getDictionary } from "@/i18n/dictionaries";
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

// Logo "CL" + tên hệ thống (chữ theo ngôn ngữ trong cookie)
async function Brand() {
  const label = (await getDictionary()).auth.brand;
  return (
    <div className="flex items-center gap-2.5 text-ui font-extrabold tracking-wide">
      <span
        aria-hidden
        className={cn(
          "grid size-7.5 shrink-0 place-items-center rounded-lg bg-primary text-xs font-extrabold",
          "text-surface",
        )}
      >
        CL
      </span>
      {label}
    </div>
  );
}
