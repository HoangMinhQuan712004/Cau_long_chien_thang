import { NavTabs } from "@/components/ui/nav-tabs";

const TABS = [
  { href: "/admin/san", label: "Danh mục sân", id: "list" },
  { href: "/admin/san/bang-gia", label: "Bảng giá", id: "prices" },
] as const;

/** Hai tab của màn Sân & bảng giá (mỗi tab một đường dẫn riêng để mở thẳng và quay lại được). */
export function SanTabs({ active }: { active: "list" | "prices" }) {
  return <NavTabs label="Sân & bảng giá" items={TABS} active={active} />;
}
