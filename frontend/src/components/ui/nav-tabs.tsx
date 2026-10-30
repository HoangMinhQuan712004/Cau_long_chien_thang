import Link from "next/link";
import { cn } from "@/lib/cn";

type NavTabItem = {
  id: string;
  href: string;
  label: string;
  /** Số đếm cạnh chữ (vd số hồ sơ mỗi loại). */
  count?: number;
};

type NavTabsProps = {
  /** Tên nhóm tab cho trình đọc màn hình. */
  label: string;
  items: readonly NavTabItem[];
  active: string;
  /** false ⇒ đổi tab không cuộn lên đầu (tab chỉ đổi tham số URL trên cùng trang). */
  scroll?: boolean;
  /** Nội dung cuối hàng, canh phải (vd nút thao tác của màn). */
  end?: React.ReactNode;
};

/** Tab gạch chân, mỗi tab là một đường dẫn (mở thẳng, Back được); điện thoại cuộn ngang trong hàng. */
export function NavTabs({ label, items, active, scroll = true, end }: NavTabsProps) {
  return (
    // Hàng ngoài giữ gạch chân; chỉ phần tab cuộn ngang, nội dung cuối hàng (end) đứng yên
    <div className="flex items-center border-b">
      <nav aria-label={label} className="flex min-w-0 flex-1 scrollbar-none overflow-x-auto">
        {items.map((item) => {
          const isActive = item.id === active;
          return (
            <Link
              key={item.id}
              href={item.href}
              scroll={scroll}
              aria-current={isActive ? "page" : undefined}
              className={cn(
                // Vòng focus vẽ vào trong: hàng cuộn ngang cắt mất vòng ngoài. Điện thoại: chữ 13px, cao 40px cho gọn
                `
                  group inline-flex min-h-10 shrink-0 items-center gap-1 rounded-t-md border-b-2
                  px-2 text-ui font-medium whitespace-nowrap focus-ring-inset transition-colors
                  duration-150
                  sm:min-h-11 sm:gap-2 sm:px-4 sm:text-sm
                `,
                // Tab chưa chọn khi rê: chữ xanh, gạch chân mờ, nền nhạt
                isActive ? "border-primary text-primary" : `
                  border-transparent text-muted
                  hover:border-primary/30 hover:bg-primary-softer hover:text-primary
                `,
              )}
            >
              {item.label}
              {item.count !== undefined ? (
                <span
                  className={cn(
                    `
                      min-w-4.5 rounded-full px-1 text-center text-[0.6875rem]/4 font-semibold
                      tabular-nums transition-colors duration-150
                      sm:min-w-6 sm:px-1.5 sm:text-label/normal
                    `,
                    // Chưa chọn: viên xám rõ trên nền trang; rê tab ⇒ chuyển xanh như tab đang chọn
                    isActive ? "bg-primary-soft text-primary" : `
                      bg-border/70 text-muted
                      group-hover:bg-primary-soft group-hover:text-primary
                    `,
                  )}
                >
                  {item.count}
                </span>
              ) : null}
            </Link>
          );
        })}
      </nav>
      {end ? <div className="flex shrink-0 items-center pl-3">{end}</div> : null}
    </div>
  );
}
