import Link from "next/link";
import { ArrowUpDownIcon, ChevronLeftIcon, ChevronRightIcon, InfoIcon, UsersIcon } from "@/components/ui/icons";
import { Skeleton } from "@/components/ui/skeleton";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { type AdminPerm, can } from "../../_components/forbidden";

// Điều hướng màn Cài đặt (một cấp duy nhất): máy tính cột trái là danh sách mục, cột phải là nội dung;
// điện thoại /admin/cai-dat là danh sách dòng "›", mở mục có nút quay lại. Mỗi mục một URL (F5 / Back đúng) và tự kiểm quyền.
// Không dùng layout để không bọc /admin/cai-dat/thanh-toan. Thêm mục: thêm một dòng vào SETTINGS_GROUPS + bọc trang bằng SettingsShell.
// Không "use client": server (trang) và client (menu tài khoản) đều import được.

type Texts = Dictionary["settingsPage"];

const SETTINGS_GROUPS = [
  {
    id: "access",
    items: [
      { id: "roles", href: "/admin/cai-dat/phan-quyen", perm: "roles.manage", icon: <UsersIcon size={16} /> },
      { id: "menu", href: "/admin/cai-dat/phan-quyen?tab=menu", perm: "settings.menu", icon: <ArrowUpDownIcon size={16} /> },
    ],
  },
  {
    id: "brand",
    items: [
      { id: "info", href: "/admin/cai-dat/thong-tin-web", perm: "settings.site", icon: <InfoIcon size={16} /> },
    ],
  },
] as const satisfies readonly { id: string; items: readonly { id: string; href: string; perm: AdminPerm; icon: React.ReactNode }[] }[];

type SettingsItem = (typeof SETTINGS_GROUPS)[number]["items"][number]["id"];

/** Mục đầu tiên tài khoản có quyền; không có mục nào ⇒ null (ẩn "Cài đặt" ở menu tài khoản). */
export const firstSettingsHref = (perms: readonly string[]) =>
  SETTINGS_GROUPS.flatMap((g) => [...g.items] as { href: string; perm: AdminPerm }[]).find((i) => can(perms, i.perm))?.href ?? null;

/** Danh sách mục theo nhóm (kiểu dòng của Hồ sơ của tôi); chỉ hiện mục có quyền, nhóm rỗng thì ẩn. */
function SettingsList({ perms, active, t }: { perms: readonly string[]; active?: SettingsItem; t: Texts }) {
  return (
    <div className="flex flex-col gap-5">
      {SETTINGS_GROUPS.map((group) => {
        const items = group.items.filter((i) => can(perms, i.perm));
        if (items.length === 0) return null;
        return (
          <section key={group.id} aria-labelledby={`settings-${group.id}`} className="flex flex-col gap-1">
            <h2 id={`settings-${group.id}`} className="px-2 text-label font-semibold tracking-wide text-muted uppercase">
              {t.groups[group.id]}
            </h2>
            {items.map((item) => (
              <Link
                key={item.id}
                href={item.href}
                aria-current={item.id === active ? "page" : undefined}
                className={cn(
                  "flex min-h-14 items-center gap-3 rounded-lg px-2 py-2.5 focus-ring transition-colors",
                  item.id === active ? "bg-primary-soft" : "hover:bg-primary-softer active:bg-primary-soft/60",
                )}
              >
                <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-full bg-primary-softer text-primary">
                  {item.icon}
                </span>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-sm font-semibold">{t.items[item.id].label}</span>
                  <span className="truncate text-ui text-muted">{t.items[item.id].description}</span>
                </span>
                <ChevronRightIcon size={18} className="shrink-0 text-muted lg:hidden" />
              </Link>
            ))}
          </section>
        );
      })}
    </div>
  );
}

const COLUMN = "mx-auto flex w-full max-w-5xl flex-col gap-4";
const GRID = "lg:grid lg:grid-cols-[16rem_minmax(0,1fr)] lg:items-start lg:gap-10";
// Danh sách dính khi nội dung dài (dưới header 56px + lề)
const NAV = "flex flex-col gap-4 lg:sticky lg:top-18";

type ShellProps = {
  perms: readonly string[];
  /** Mục đang mở; bỏ trống = màn đầu /admin/cai-dat (điện thoại: chỉ danh sách). */
  active?: SettingsItem;
  t: Texts;
  children?: React.ReactNode;
};

/** Khung màn Cài đặt. Điện thoại: màn đầu chỉ có danh sách, khi mở mục chỉ có nội dung + nút quay lại. */
export function SettingsShell({ perms, active, t, children }: ShellProps) {
  const current = active ? t.items[active] : null;
  return (
    <div className={COLUMN}>
      <div className={GRID}>
        {/* Tiêu đề nằm cùng cột danh sách nên dính theo, không trôi khi cuộn nội dung dài */}
        <div className={cn(NAV, current && "hidden lg:flex")}>
          <h1 className="text-xl font-bold sm:text-2xl">{t.title}</h1>
          <nav aria-label={t.navLabel}>
            <SettingsList perms={perms} active={active} t={t} />
          </nav>
        </div>
        {current ? (
          // lg:pt-11: tiêu đề mục thẳng hàng nhóm đầu của cột trái; nội dung gọn, không kéo giãn hết màn
          <div className="flex max-w-2xl min-w-0 flex-col gap-4 lg:pt-11">
            <Link href="/admin/cai-dat" className="-ml-2 inline-flex min-h-11 w-fit items-center gap-1 rounded-lg pr-3 text-sm font-medium text-muted focus-ring hover:text-primary lg:hidden">
              <ChevronLeftIcon size={20} />
              {t.back}
            </Link>
            <div className="flex flex-col gap-0.5">
              <h2 className="text-lg font-bold">{current.label}</h2>
              <p className="text-ui text-muted">{current.description}</p>
            </div>
            {children}
          </div>
        ) : (
          // Máy tính mở thẳng URL này (menu tài khoản đã đưa vào mục đầu): gợi ý chọn mục
          <p className="hidden pt-12 text-sm text-muted lg:block">{t.pick}</p>
        )}
      </div>
    </div>
  );
}

/** Khung chờ đúng hình: danh sách + nội dung (điện thoại chỉ một khối). */
export function SettingsSkeleton() {
  return (
    <div className={COLUMN}>
      <Skeleton className="h-8 w-40" />
      <div className={GRID}>
        <Skeleton className="hidden h-64 w-full rounded-card lg:block" />
        <Skeleton className="h-96 w-full rounded-card" />
      </div>
    </div>
  );
}
