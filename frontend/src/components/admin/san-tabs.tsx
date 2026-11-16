import { NavTabs } from "@/components/ui/nav-tabs";
import type { Dictionary } from "@/i18n/dictionaries";

type Texts = Pick<Dictionary["courts"], "title" | "tabList" | "tabPrices">;

/** Hai tab của màn Sân & bảng giá (mỗi tab một đường dẫn riêng để mở thẳng và quay lại được); `end` = nút cuối hàng. */
export function SanTabs({ active, t, end }: { active: "list" | "prices"; t: Texts; end?: React.ReactNode }) {
  const items = [
    { href: "/admin/san", label: t.tabList, id: "list" },
    { href: "/admin/san/bang-gia", label: t.tabPrices, id: "prices" },
  ];
  return <NavTabs label={t.title} items={items} active={active} end={end} />;
}
