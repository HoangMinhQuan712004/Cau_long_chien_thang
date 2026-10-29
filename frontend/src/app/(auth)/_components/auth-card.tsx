import Link from "next/link";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";

type AuthCardProps = {
  title?: string;
  description?: React.ReactNode;
  children: React.ReactNode;
};

/** Thẻ của màn đăng nhập / quên mật khẩu; không có `title` ⇒ khung giữ chỗ (đang đọc ngôn ngữ). */
export function AuthCard({ title, description, children }: AuthCardProps) {
  return (
    <Card className="flex w-full max-w-auth flex-col gap-4 p-6">
      {title ? (
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-bold">{title}</h1>
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
      className={cn("-my-3 self-start py-3 text-ui text-muted focus-ring hover:text-primary")}
    >
      {children}
    </Link>
  );
}
