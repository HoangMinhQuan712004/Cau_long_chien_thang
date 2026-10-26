import Link from "next/link";

const TABS = [
  { href: "/admin/san", label: "Danh mục sân", id: "list" },
  { href: "/admin/san/bang-gia", label: "Bảng giá", id: "prices" },
] as const;

/** Hai tab của màn Sân & bảng giá (mỗi tab một đường dẫn riêng để mở thẳng và quay lại được). */
export function SanTabs({ active }: { active: "list" | "prices" }) {
  return (
    <nav aria-label="Sân & bảng giá" className="flex gap-1 border-b border-border">
      {TABS.map((t) => (
        <Link
          key={t.id}
          href={t.href}
          aria-current={t.id === active ? "page" : undefined}
          className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${
            t.id === active
              ? "border-primary text-primary"
              : "border-transparent text-muted hover:text-foreground"
          }`}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
