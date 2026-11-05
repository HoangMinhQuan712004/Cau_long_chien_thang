"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";
import { formatVnd } from "@/lib/format";

// "Chi tiết giá" của đơn Đặt sân định kỳ, kiểu hóa đơn: "n buổi × đơn giá · khung giờ" (gộp buổi cùng giá + cùng khung)
// → giảm giá đơn → Tổng thanh toán. Số tổng / giảm luôn lấy của BE; dòng chi tiết cộng không khớp tiền gốc
// (làm tròn, giá khác) ⇒ chỉ hiện một dòng tổng gốc.
// - PriceBreakdown: khối đầy đủ (hộp kết quả sau khi đặt).
// - PriceFooter: ở chân hộp đặt, cạnh nút Đặt; điện thoại thu gọn còn "Tổng thanh toán" + "Chi tiết ▾".

export type PriceLine = { price: number; time: string };

type Money = {
  /** Mỗi buổi hợp lệ (chưa bỏ): đơn giá trước giảm + khung giờ "17:00–19:00". */
  lines: PriceLine[];
  originalAmount: number;
  discountPct: number;
  discountAmount: number;
  total: number;
};

/** Gộp buổi cùng đơn giá + cùng khung giờ thành một dòng. */
function groupLines(lines: PriceLine[]) {
  const groups = new Map<string, { price: number; time: string; n: number }>();
  for (const l of lines) {
    const k = `${l.price}|${l.time}`;
    const g = groups.get(k) ?? { price: l.price, time: l.time, n: 0 };
    g.n++;
    groups.set(k, g);
  }
  return [...groups.values()].sort((a, b) => a.price - b.price || a.time.localeCompare(b.time));
}

/** Các dòng chi tiết (gộp theo giá + khung) và dòng giảm giá; số căn phải sát mép khối. */
function PriceRows({ lines, originalAmount, discountPct, discountAmount }: Omit<Money, "total">) {
  const rows = groupLines(lines);
  const matches = rows.reduce((sum, g) => sum + g.n * g.price, 0) === originalAmount;
  const row = (key: string, label: React.ReactNode, value: string, tone = "") => (
    <div key={key} className={cn("flex items-baseline justify-between gap-3", tone)}>
      <dt className={cn("tabular-nums", !tone && "text-muted")}>{label}</dt>
      <dd className="shrink-0 font-semibold tabular-nums">{value}</dd>
    </div>
  );
  return (
    <dl className="space-y-1">
      {matches
        ? rows.map((g) => row(`${g.price}-${g.time}`, `${g.n} buổi × ${formatVnd(g.price)} · ${g.time}`, formatVnd(g.n * g.price)))
        : row("goc", `${lines.length} buổi · giá gốc`, formatVnd(originalAmount))}
      {discountAmount > 0 ? row("giam", `Giảm giá đơn ${discountPct}%`, `−${formatVnd(discountAmount)}`, "text-primary") : null}
    </dl>
  );
}

export function PriceBreakdown({ summary, excluded = 0, ...money }: Money & { summary: string; excluded?: number }) {
  return (
    <section aria-label="Chi tiết giá" className="space-y-2">
      <h4 className="text-sm font-semibold">Chi tiết giá</h4>
      <div className="text-ui">
        <PriceRows {...money} />
      </div>
      <div className="border-t border-border pt-2">
        <p className="text-sm font-semibold">Tổng thanh toán</p>
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <p className="text-ui text-muted tabular-nums">{summary}</p>
          <p className="text-2xl font-bold tabular-nums">{formatVnd(money.total)}</p>
        </div>
        {excluded > 0 ? <p className="text-xs text-danger">Chưa tính {excluded} buổi lỗi.</p> : null}
      </div>
    </section>
  );
}

/**
 * Khối giá ở chân hộp, rộng cố định (sm: 24rem) để nhãn trái / số phải thẳng cột.
 * Điện thoại luôn thu gọn còn Tổng + "Chi tiết ▾"; máy tính hiện đủ, chỉ thu gọn khi nhiều hơn 3 dòng.
 */
export function PriceFooter(money: Money) {
  const [open, setOpen] = useState(false);
  const rowCount = groupLines(money.lines).length + (money.discountAmount > 0 ? 1 : 0);
  const longOnDesktop = rowCount > 3;
  return (
    <section aria-label="Chi tiết giá" className="w-full min-w-0 text-xs">
      <div id="recurring-price-rows" className={cn("mb-1.5", open ? "block" : "hidden", !longOnDesktop && "sm:block")}>
        <PriceRows {...money} />
      </div>
      <div className="flex items-baseline justify-between gap-2 border-t border-border pt-1.5">
        <span className="flex items-baseline gap-1.5">
          <span className="text-sm font-semibold">Tổng thanh toán</span>
          <button
            type="button"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            aria-controls="recurring-price-rows"
            className={cn(
              "relative rounded-md px-1.5 py-0.5 font-medium text-primary hover:bg-primary-softer focus-ring before:absolute before:inset-x-0 before:-inset-y-2.5",
              !longOnDesktop && "sm:hidden",
            )}
          >
            Chi tiết {open ? "▴" : "▾"}
          </button>
        </span>
        <b className="text-lg tabular-nums sm:text-2xl">{formatVnd(money.total)}</b>
      </div>
    </section>
  );
}
