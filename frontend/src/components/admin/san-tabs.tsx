import { NavTabs } from "@/components/ui/nav-tabs";
import type { Dictionary } from "@/i18n/dictionaries";

type Texts = Pick<Dictionary["courts"], "title" | "tabList" | "tabPrices">;

/** Hai tab của màn Sân & bảng giá (mỗi tab một đường dẫn riêng để mở thẳng và quay lại được); `end` = nút cuối hàng.
 * `showPrices` = có quyền booking.prices.manage (NV mặc định không có, người dùng 26/11) ⇒ mới hiện tab Bảng giá. */
export function SanTabs({ active, t, end, showPrices = true }: { active: "list" | "prices"; t: Texts; end?: React.ReactNode; showPrices?: boolean }) {
  const items = [
    { href: "/admin/san", label: t.tabList, id: "list" },
    ...(showPrices ? [{ href: "/admin/san/bang-gia", label: t.tabPrices, id: "prices" }] : []),
  ];
  return <NavTabs label={t.title} items={items} active={active} end={end} />;
}
