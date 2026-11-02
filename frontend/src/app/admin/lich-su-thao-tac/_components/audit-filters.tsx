"use client";

import { type FilterDef, FilterBar } from "@/components/ui/filter-bar";
import { DateRange } from "@/components/ui/date-range";
import type { Dictionary } from "@/i18n/dictionaries";
import type { AuditCatalog } from "@/lib/api/server";
import { type AuditFilter, type AuditPatch, CLEAR_FILTERS } from "./audit-params";

type Props = {
  catalog: AuditCatalog;
  /** Bộ lọc đang áp (URL); ngày rỗng ⇒ khoảng API mặc định trả về. */
  filter: AuditFilter;
  /** Khoảng ngày có trên URL (khác mặc định 7 ngày) ⇒ tính 1 lọc ở nút Xóa lọc. */
  hasDateRange: boolean;
  onChange: (patch: AuditPatch) => void;
  t: Dictionary["auditLog"];
};

/** Thanh lọc giống màn Hội viên (FilterBar, không ô tìm): khoảng ngày, Người làm, Loại thao tác (cây nhóm), Xóa lọc; đổi là áp ngay. */
export function AuditFilters({ catalog, filter, hasDateRange, onChange, t }: Props) {
  const f = t.filters;
  const filters: FilterDef[] = [
    {
      key: "actor",
      label: f.actor,
      value: filter.actor,
      onChange: (actor) => onChange({ actor }),
      options: catalog.actors.map((a) => ({ value: a.key, label: a.label })),
      // Vừa đủ "Người làm: Nhân viên" kèm nút × (đo: 182px)
      className: "sm:w-48",
    },
    {
      key: "action",
      label: f.action,
      value: filter.action,
      onChange: (action) => onChange({ action }),
      // "Tất cả" (FilterBar tự thêm) đứng riêng trên cùng, rồi cây: nhóm (tiêu đề, không chọn được) ⇒ các loại
      options: catalog.groups.flatMap((g) => g.types.map((x) => ({ value: x.key, label: x.label, group: g.label }))),
      variant: "tree",
      // Cố định (đổi lựa chọn hàng không nhảy); 1280 có sidebar chỉ còn chừng này, tên dài cắt "…" + title.
      // Từ 2xl dư chỗ: vừa "Loại thao tác: Đăng xuất do đổi mật khẩu ×" (đo: 311px)
      className: "sm:w-64 2xl:w-78",
    },
  ];

  return (
    // Điện thoại: ngày ở trên, hàng ô chọn vuốt ngang bên dưới; từ xl: một hàng, căn giữa dọc (lg 1024 không đủ chỗ ⇒ ngày ở trên)
    <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:gap-2">
      <DateRange
        from={filter.from}
        to={filter.to}
        min={catalog.min_date}
        max={catalog.max_date}
        // Gõ tay ra ngày đầu sau ngày cuối ⇒ không gửi (tránh 422)
        onChange={(range) => range.from <= range.to && onChange(range)}
        t={f}
      />
      <div className="min-w-0 xl:flex-1">
        <FilterBar
          filters={filters}
          onClear={() => onChange(CLEAR_FILTERS)}
          extraCount={hasDateRange ? 1 : 0}
          t={f.filterBar}
        />
      </div>
    </div>
  );
}
