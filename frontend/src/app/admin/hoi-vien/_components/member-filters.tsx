"use client";

import { type FilterDef, FilterBar } from "@/components/ui/filter-bar";
import type { Dictionary } from "@/i18n/dictionaries";
import { type MemberFilter, SEARCH_MAX, TIER_NONE, TIERS } from "./member-params";
import { useRackets } from "./use-rackets";

type Props = {
  filter: MemberFilter;
  onChange: (patch: Partial<MemberFilter>) => void;
  /** Admin: ô lọc Vợt có cả vợt đã ẩn (hồ sơ cũ vẫn có thể dùng). */
  canSeeHiddenRackets: boolean;
  t: Dictionary["members"];
};

/** Bộ lọc màn Hội viên (Loại là tab riêng ở MemberList): ô tìm + Trạng thái / Hạng / Vợt (giao diện do FilterBar lo). */
export function MemberFilters({ filter, onChange, canSeeHiddenRackets, t }: Props) {
  const rackets = useRackets(canSeeHiddenRackets).state;
  const racketItems = rackets.status === "ok" ? rackets.items : [];
  // Vợt trên URL không còn trong danh mục (đã xóa, link cũ) vẫn hiện để biết đang lọc gì
  const isUnlisted = filter.racket !== "" && !racketItems.some((r) => r.name === filter.racket);

  const filters: FilterDef[] = [
    {
      key: "status",
      label: t.statusLabel,
      value: filter.status,
      onChange: (v) => onChange({ status: v as MemberFilter["status"] }),
      options: (["active", "inactive"] as const).map((s) => ({ value: s, label: t.statuses[s] })),
      // Từ sm cố định, vừa "Trạng thái: Hoạt động" (đổi lọc không nhảy hàng)
      className: "sm:w-52",
    },
    {
      key: "tier",
      label: t.tierLabel,
      value: filter.tier,
      onChange: (tier) => onChange({ tier }),
      options: [...TIERS.map((x) => ({ value: x, label: x })), { value: TIER_NONE, label: t.tierNone }],
      // Vừa "Hạng: Trung bình yếu"
      className: "sm:w-52",
    },
    {
      key: "racket",
      label: t.racketFilterLabel,
      value: filter.racket,
      allValue: "",
      onChange: (racket) => onChange({ racket }),
      // Tên vợt dài cắt "…" (rê chuột xem trọn)
      className: "sm:w-56 2xl:w-72",
      options: [
        ...(isUnlisted ? [{ value: filter.racket, label: filter.racket }] : []),
        ...racketItems.map((r) => ({ value: r.name, label: r.is_active ? r.name : t.rackets.hiddenOption.replace("{name}", r.name) })),
      ],
    },
  ];

  return (
    <FilterBar
      search={{
        value: filter.q,
        onChange: (q) => onChange({ q }),
        label: t.searchLabel,
        placeholder: t.searchPlaceholder,
        maxLength: SEARCH_MAX,
      }}
      filters={filters}
      // Xóa cả ô tìm (như "Xóa lọc" ở câu trống của bảng); tab Loại giữ nguyên
      onClear={() => onChange({ status: "all", tier: "all", racket: "", q: "" })}
      t={t.filterBar}
    />
  );
}
