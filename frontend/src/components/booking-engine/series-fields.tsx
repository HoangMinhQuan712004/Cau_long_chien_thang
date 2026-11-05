"use client";

import { useId } from "react";
import { Button } from "@/components/ui/button";
import { Dropdown } from "@/components/ui/dropdown";
import { Field } from "@/components/ui/field";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { fill } from "@/lib/format";
import { hourText } from "./block";
import type { SeriesParams } from "./types";

// Ô nhập của hộp "Đặt theo tháng" bằng primitive dùng chung: Field + Dropdown (tháng, sân, giờ Từ–Đến theo giờ chẵn)
// và nhóm nút liền T2…CN (cùng kiểu bộ lọc kỳ ở Báo cáo: đang chọn nền xanh, còn lại nút nhẹ).


type Props = {
  value: SeriesParams;
  onChange: (patch: Partial<SeriesParams>) => void;
  months: string[];
  courts: { code: string; name: string }[];
  /** Giờ bắt đầu các cột của lưới (giờ mở cửa). */
  hours: number[];
  t: Dictionary["series"];
};

const ALL_WEEK = [1, 2, 3, 4, 5, 6, 7];
/** "2026-11" + "Tháng {m}/{y}" ⇒ "Tháng 11/2026". */
export const monthLabel = (ym: string, tpl: string) => fill(tpl, { m: Number(ym.slice(5)), y: ym.slice(0, 4) });
const hourOptions = (hs: number[]) => hs.map((h) => ({ value: String(h), label: hourText(h) }));

export function SeriesFields({ value, onChange, months, courts, hours, t }: Props) {
  const id = useId();
  const ends = hours.map((h) => h + 1).filter((h) => h > value.start_hour);
  const pickStart = (h: number) => onChange({ start_hour: h, end_hour: Math.max(value.end_hour, h + 1) });
  const toggleDay = (d: number) =>
    onChange({ weekdays: value.weekdays.includes(d) ? value.weekdays.filter((x) => x !== d) : [...value.weekdays, d].sort() });
  const allOn = value.weekdays.length === ALL_WEEK.length;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2 sm:col-span-1">
          <Field label={t.month} htmlFor={`${id}-m`}>
            <Dropdown
              id={`${id}-m`}
              value={value.month}
              onChange={(month) => onChange({ month })}
              options={months.map((m) => ({ value: m, label: monthLabel(m, t.monthOption) }))}
            />
          </Field>
        </div>
        <div className="col-span-2 sm:col-span-1">
          <Field label={t.court} htmlFor={`${id}-c`}>
            <Dropdown
              id={`${id}-c`}
              value={value.resource_code}
              onChange={(resource_code) => onChange({ resource_code })}
              options={courts.map((c) => ({ value: c.code, label: `${c.code} · ${c.name}` }))}
            />
          </Field>
        </div>
        <Field label={t.from} htmlFor={`${id}-f`}>
          <Dropdown id={`${id}-f`} value={String(value.start_hour)} onChange={(v) => pickStart(Number(v))} options={hourOptions(hours)} />
        </Field>
        <Field label={t.to} htmlFor={`${id}-t`}>
          <Dropdown id={`${id}-t`} value={String(value.end_hour)} onChange={(v) => onChange({ end_hour: Number(v) })} options={hourOptions(ends)} />
        </Field>
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <span id={`${id}-w`} className="text-label font-semibold text-muted">{t.weekdays}</span>
          <Button variant="ghost" onClick={() => onChange({ weekdays: allOn ? [] : ALL_WEEK })}>
            {allOn ? t.clearWeek : t.allWeek}
          </Button>
        </div>
        <div role="group" aria-labelledby={`${id}-w`} className={cn(`
          flex gap-0.5 rounded-lg border border-border-strong bg-surface p-0.5
        `)}>
          {ALL_WEEK.map((d) => (
            <Button
              key={d}
              variant={value.weekdays.includes(d) ? "primary" : "ghost"}
              aria-pressed={value.weekdays.includes(d)}
              onClick={() => toggleDay(d)}
              className="min-w-0 flex-1 px-0 sm:px-0"
            >
              {t.weekdayShort[d - 1]}
            </Button>
          ))}
        </div>
      </div>
    </div>
  );
}
