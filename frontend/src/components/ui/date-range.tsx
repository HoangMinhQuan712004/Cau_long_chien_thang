"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";
import { Input } from "./input";

export type DateRangeValue = { from: string; to: string };
export type DateRangeKey = keyof DateRangeValue;

type Props = DateRangeValue & {
  /** Giới hạn lịch (YYYY-MM-DD); bỏ `min` ⇒ không giới hạn đầu. */
  min?: string;
  max: string;
  /** Lịch ngày đầu không cho chọn sau ngày cuối (và ngược lại). Tắt khi nơi gọi tự báo lỗi "Từ ngày sau Đến ngày". */
  linked?: boolean;
  /** Gọi khi đủ 2 ngày, trong giới hạn và khác khoảng đang áp; `key` = ô vừa đổi. Nơi gọi kiểm tiếp (từ ≤ đến…). */
  onChange: (range: DateRangeValue, key: DateRangeKey) => void;
  /** Ô viền đỏ (khoảng ngày sai, thông báo do nơi gọi hiện). */
  invalid?: DateRangeKey | null;
  /** Bề rộng ô ngày. Mặc định hẹp lại ở xl để thanh lọc Lịch sử thao tác vừa một hàng ở 1280px (đo 2026-11-02: w-34 thiếu 3px). */
  inputWidth?: string;
  t: DateRangeValue;
};

/**
 * Từ ngày – Đến ngày: đổi là áp ngay. Giữ chữ đang gõ riêng, chỉ gửi lên khi đủ ngày
 * (gõ tay năm từng số ra ngày lạ ⇒ không gửi). Khoảng đang áp đổi từ ngoài ⇒ ô theo.
 */
export function DateRange({
  from,
  to,
  min = "",
  max,
  linked = true,
  onChange,
  invalid = null,
  inputWidth = "sm:w-40 xl:w-33",
  t,
}: Props) {
  const [draft, setDraft] = useState<DateRangeValue>({ from, to });
  const [synced, setSynced] = useState<DateRangeValue>({ from, to });
  if (from !== synced.from || to !== synced.to) {
    setSynced({ from, to });
    setDraft({ from, to });
  }

  const update = (key: DateRangeKey, value: string) => {
    const next = { ...draft, [key]: value };
    setDraft(next);
    const isComplete = next.from !== "" && next.to !== "" && next.from >= min && next.to <= max;
    // Đang báo lỗi ⇒ luôn gửi (chọn lại đúng khoảng đang áp thì nơi gọi xóa lỗi)
    if (isComplete && (next.from !== from || next.to !== to || invalid)) onChange(next, key);
  };
  const limits = linked
    ? { from: { min: min || undefined, max: draft.to || max }, to: { min: draft.from || min || undefined, max } }
    : { from: { min: min || undefined, max }, to: { min: min || undefined, max } };

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
            aria-invalid={invalid === key || undefined}
            onChange={(e) => update(key, e.target.value)}
            className={cn("tabular-nums", inputWidth)}
          />
        </label>
      ))}
    </div>
  );
}
