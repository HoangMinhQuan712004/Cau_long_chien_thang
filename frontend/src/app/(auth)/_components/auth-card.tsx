import Link from "next/link";
import { Card } from "@/components/ui/card";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";

type AuthCardProps = {
  title?: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  /** Thanh tiến trình nhiều bước (quên mật khẩu): `current` tính từ 1. */
  steps?: { labels: string[]; current: number; caption: string };
};

/** Thẻ của màn đăng nhập / đăng ký / quên mật khẩu (nổi trên dải hero xanh ở điện thoại); không có `title` ⇒ khung giữ
 *  chỗ (đang đọc ngôn ngữ). */
export function AuthCard({ title, description, steps, children }: AuthCardProps) {
  return (
    <Card
      className="flex w-full max-w-auth flex-col gap-5 p-5 shadow-auth sm:max-w-md sm:p-8"
    >
      {steps ? <StepBar {...steps} /> : null}
      {title ? (
        <div className="flex flex-col gap-1.5">
          <h1 className="text-xl font-bold tracking-tight sm:text-2xl">{title}</h1>
          {description && <p className="text-ui text-muted">{description}</p>}
        </div>
      ) : (
        <div
          aria-hidden
          className="h-8 w-40 animate-pulse rounded-sm bg-background motion-reduce:animate-none"
        />
      )}
      {children}
    </Card>
  );
}

/** "Bước 2/3" (trái) – tên bước (phải) + 3 vạch: bước đã qua / đang ở tô xanh. */
function StepBar({ labels, current, caption }: NonNullable<AuthCardProps["steps"]>) {
  return (
    <div className="flex flex-col gap-2">
      <p className="flex justify-between gap-3 text-label font-semibold">
        <span className="text-primary">{caption}</span>
        <span className="text-muted">{labels[current - 1]}</span>
      </p>
      <ol className="flex gap-1.5" aria-label={caption}>
        {labels.map((label, i) => (
          <li
            key={label}
            aria-current={i + 1 === current ? "step" : undefined}
            className={cn("h-1.5 flex-1 rounded-full", i < current ? "bg-primary" : "bg-border")}
          >
            <span className="sr-only">{label}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Khung giữ chỗ cho form: các ô nhập + nút, cùng chiều cao thật để không nhảy layout. */
export function AuthFormSkeleton({ fields = 1 }: { fields?: number }) {
  return (
    <div aria-hidden className="flex animate-pulse flex-col gap-4 motion-reduce:animate-none">
      {Array.from({ length: fields }, (_, i) => (
        <div key={i} className="flex flex-col gap-1.5">
          <div className="h-4 w-40 rounded-sm bg-background" />
          <div className="h-11 rounded-lg bg-background sm:h-9.5" />
        </div>
      ))}
      <div className="h-11 rounded-lg bg-background sm:h-10.5" />
      <div className="h-5 w-28 rounded-sm bg-background" />
    </div>
  );
}

/** Link phụ dưới form (Quên mật khẩu, Về đăng nhập, Đổi số…): vùng chạm 44px, nhìn như chữ. */
export function AuthTextLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className={cn("-my-3 py-3 text-ui text-muted focus-ring hover:text-primary")}
    >
      {children}
    </Link>
  );
}

/** Thanh 3 bước của quên mật khẩu (nhập SĐT → mã xác minh → mật khẩu mới). */
export const forgotSteps = (t: Dictionary["forgot"], current: number) => ({
  labels: t.steps,
  current,
  caption: t.stepOf.replace("{n}", String(current)).replace("{total}", String(t.steps.length)),
});
