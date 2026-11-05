"use client";

import { cn } from "@/lib/cn";
import { formatDayMonth, formatVnd, weekdayIndex } from "@/lib/format";
import type { SeriesDate } from "./types";

// Danh sách ngày sau "Kiểm tra lịch": tích / bỏ từng ngày; ngày trùng (đỏ) bỏ tích sẵn, không tích được.

type Props = {
  dates: SeriesDate[];
  picked: ReadonlySet<string>;
  onToggle: (date: string) => void;
  t: { datesTitle: string; datesHint: string; empty: string; reasonDefault: string; weekdayShort: string[] };
};

/** "T7 07/11": thứ theo lịch (ngày ISO, không phụ thuộc múi giờ máy). */
export const dayLabel = (date: string, short: string[]) =>
  `${short[weekdayIndex(date)]} ${formatDayMonth(date)}`;

export function SeriesPreviewList({ dates, picked, onToggle, t }: Props) {
  if (!dates.length) return <p role="status" className="text-sm text-muted">{t.empty}</p>;
  return (
    <section aria-label={t.datesTitle} className="flex flex-col gap-1">
      <h3 className="text-sm font-semibold">{t.datesTitle}</h3>
      <p className="text-ui text-muted">{t.datesHint}</p>
      <ul className="mt-1 divide-y">
        {dates.map((d) => {
          const bad = d.status === "conflict";
          return (
            <li key={d.date}>
              <label
                className={cn(
                  "flex min-h-11 items-center gap-3 px-1 py-2",
                  bad ? "cursor-not-allowed bg-danger-soft text-danger" : `
                    cursor-pointer
                    hover:bg-primary-softer
                  `,
                )}
              >
                <input
                  type="checkbox"
                  className="size-5 shrink-0 accent-primary"
                  checked={!bad && picked.has(d.date)}
                  disabled={bad}
                  onChange={() => onToggle(d.date)}
                />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="text-sm font-medium tabular-nums">{dayLabel(d.date, t.weekdayShort)}</span>
                  {bad ? <span className="text-ui">{d.reason || t.reasonDefault}</span> : null}
                </span>
                <span className={cn("text-sm tabular-nums", bad && "line-through")}>{formatVnd(d.price)}</span>
              </label>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
