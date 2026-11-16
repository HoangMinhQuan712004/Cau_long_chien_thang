import { NetMesh } from "@/components/net-mesh";
import { cn } from "@/lib/cn";

/** Banner xanh đậm đầu trang khu hội viên (tiêu đề + dòng phụ + vùng bên phải), nền mắt lưới mờ như banner Tổng quan.
 *  `flushOnMobile`: dưới lg hàng tiêu đề không có gì hiện (tiêu đề ở app bar, `aside` ẩn) ⇒ bỏ padding, `children` sát trên. */
export function PageBanner({ title, subtitle, aside, children, desktopOnly = false, flushOnMobile = false, mobileTitle = false }: { title: React.ReactNode; subtitle?: React.ReactNode; aside?: React.ReactNode; children?: React.ReactNode; desktopOnly?: boolean; flushOnMobile?: boolean; /** Hiện tiêu đề cả trên điện thoại (trang công khai không có app bar ghi tiêu đề). */ mobileTitle?: boolean }) {
  return (
    // Dưới lg tiêu đề do app bar của khung hiển thị (T-028 AC3); không có điều khiển nào thì ẩn cả banner
    <section className={cn("relative isolate overflow-hidden bg-appbar text-surface", !(aside || children) && "max-lg:hidden", desktopOnly && "max-lg:hidden")}>
      <NetMesh />
      <div className={cn("relative mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-4 sm:py-8", flushOnMobile && "max-lg:py-2!")}>
        <div className={cn("min-w-0", !mobileTitle && "max-lg:sr-only")}>
          <h1 className="text-xl font-extrabold tracking-tight break-words sm:text-3xl">{title}</h1>
          {subtitle ? <p className="mt-1 text-xs text-surface/80 sm:text-sm">{subtitle}</p> : null}
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}
