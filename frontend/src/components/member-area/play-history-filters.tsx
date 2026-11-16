"use client";

import { DateRange, type DateRangeValue } from "@/components/ui/date-range";
import { SearchIcon } from "@/components/ui/icons";
import { Input } from "@/components/ui/input";
import { useSearchDraft } from "@/hooks/use-search-draft";
import { cn } from "@/lib/cn";
import { addDaysIso } from "@/lib/format";

// Thanh lọc Lịch sử chơi: chọn nhanh khoảng ngày (1 chạm) hoặc Từ – Đến tự do qua nhiều tháng, ô tìm sân.

/** Khoảng tối đa (khớp BE `MAX_RANGE_DAYS`). */
export const MAX_RANGE_DAYS = 366;
const monthStart = (d: string) => `${d.slice(0, 7)}-01`;

export const thisMonth = (today: string): DateRangeValue => ({ from: monthStart(today), to: today });

/** Số ngày từ `from` đến `to` (cùng ngày = 0). */
export const daysBetween = ({ from, to }: DateRangeValue) => Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);

function presets(today: string): { key: string; label: string; range: DateRangeValue }[] {
  const lastOfPrev = addDaysIso(monthStart(today), -1);
  return [
    { key: "7d", label: "7 ngày qua", range: { from: addDaysIso(today, -6), to: today } },
    { key: "month", label: "Tháng này", range: thisMonth(today) },
    { key: "prev", label: "Tháng trước", range: { from: monthStart(lastOfPrev), to: lastOfPrev } },
    { key: "3m", label: "3 tháng qua", range: { from: addDaysIso(today, -89), to: today } },
  ];
}

type Props = {
  today: string;
  range: DateRangeValue;
  onRange: (range: DateRangeValue) => void;
  /** Chữ tìm đang áp; ô tự giữ chữ đang gõ, ngừng gõ mới áp. */
  q: string;
  onSearch: (q: string) => void;
  /** Khoảng sai (quá 1 năm) – hiện dưới ô ngày. */
  error?: string;
};

export function PlayHistoryFilters({ today, range, onRange, q, onSearch, error }: Props) {
  const [draft, setDraft] = useSearchDraft(q, onSearch);

  return (
    <div className="flex flex-col gap-3">
      {/* Thời gian đi chung một hàng: chọn nhanh bên trái, Từ – Đến bên phải; điện thoại xếp dọc */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div
          role="group"
          aria-label="Chọn nhanh khoảng ngày"
          // Điện thoại: lưới 2×2 giãn đủ ngang (4 nút một hàng thì "Tháng trước" bị cắt); từ sm một hàng.
          // Cao bằng ô ngày / ô tìm (Input compact: 32px, từ sm 38px) cho thẳng hàng
          className="grid grid-cols-2 gap-2 sm:flex"
        >
          {presets(today).map((p) => {
            const isOn = p.range.from === range.from && p.range.to === range.to;
            return (
              <button
                key={p.key}
                type="button"
                aria-pressed={isOn}
                onClick={() => onRange(p.range)}
                className={cn(
                  `
                    h-8 rounded-full border px-3 text-xs font-medium whitespace-nowrap
                    transition-colors focus-ring
                    sm:h-9.5 sm:shrink-0 sm:px-4 sm:text-sm
                  `,
                  isOn ? "border-primary bg-primary text-surface" : "border-border-strong hover:bg-primary-softer",
                )}
              >
                {p.label}
              </button>
            );
          })}
        </div>
        <DateRange
          from={range.from}
          to={range.to}
          max={today}
          onChange={(next) => onRange(next)}
          invalid={error ? "from" : null}
          inputWidth="sm:w-40"
          t={{ from: "Từ ngày", to: "Đến ngày" }}
        />
      </div>
      {error ? (
        <p role="alert" className="text-ui text-danger lg:text-right">
          {error}
        </p>
      ) : null}
      <Input
        compact
        type="search"
        aria-label="Tìm buổi chơi"
        placeholder="Tìm theo sân, loại sân, ngày…"
        value={draft}
        maxLength={50}
        onChange={(e) => setDraft(e.target.value)}
        startSlot={<SearchIcon size={18} />}
        onClear={() => {
          setDraft("");
          onSearch("");
        }}
        clearLabel="Xóa chữ tìm"
      />
    </div>
  );
}
