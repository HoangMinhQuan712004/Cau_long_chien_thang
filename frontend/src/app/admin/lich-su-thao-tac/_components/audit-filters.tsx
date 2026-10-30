"use client";

import { useState } from "react";
import { type FilterDef, FilterBar } from "@/components/ui/filter-bar";
import { Input } from "@/components/ui/input";
import type { Dictionary } from "@/i18n/dictionaries";
import type { AuditCatalog } from "@/lib/api/server";
import { cn } from "@/lib/cn";
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
        onChange={(range) => onChange(range)}
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

type Range = { from: string; to: string };

type DateRangeProps = Range & {
  /** Giới hạn lịch: 12 tháng gần nhất (BR-012). */
  min: string;
  max: string;
  /** Gọi khi khoảng ngày hợp lệ (đủ 2 ngày, trong giới hạn, từ ≤ đến). */
  onChange: (range: Range) => void;
  t: Range;
};

/**
 * Từ ngày – Đến ngày: đổi là áp ngay. Giữ chữ đang gõ riêng, chỉ áp khi hợp lệ
 * (gõ tay năm từng số ra ngày lạ ⇒ không gửi, tránh 422).
 */
function DateRange({ from, to, min, max, onChange, t }: DateRangeProps) {
  const [draft, setDraft] = useState<Range>({ from, to });
  const [synced, setSynced] = useState<Range>({ from, to });
  // URL đổi từ ngoài (Xóa lọc, Back) ⇒ ô theo
  if (from !== synced.from || to !== synced.to) {
    setSynced({ from, to });
    setDraft({ from, to });
  }

  const update = (patch: Partial<Range>) => {
    const next = { ...draft, ...patch };
    setDraft(next);
    const isValid = next.from >= min && next.to <= max && next.from !== "" && next.from <= next.to;
    if (isValid && (next.from !== from || next.to !== to)) onChange(next);
  };
  // Lịch không cho chọn ngoài giới hạn, ngày đầu không sau ngày cuối
  const limits = {
    from: { min, max: draft.to || max },
    to: { min: draft.from || min, max },
  };

  return (
    <div className="grid shrink-0 grid-cols-2 gap-2 sm:flex sm:items-center sm:gap-3 xl:gap-2">
      {(["from", "to"] as const).map((key) => (
        <label key={key} className={cn(`
          flex min-w-0 flex-col gap-1
          sm:flex-row sm:items-center sm:gap-2
          xl:gap-1.5
        `)}>
          <span className="shrink-0 text-xs text-muted sm:text-ui">{t[key]}</span>
          <Input
            compact
            type="date"
            required
            value={draft[key]}
            {...limits[key]}
            onChange={(e) => update({ [key]: e.target.value })}
            // Máy tính hẹp lại để cả 5 phần vừa một hàng ở 1280px
            className="tabular-nums sm:w-40 xl:w-34"
          />
        </label>
      ))}
    </div>
  );
}
