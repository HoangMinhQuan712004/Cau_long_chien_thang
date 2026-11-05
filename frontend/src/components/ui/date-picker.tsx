"use client";

import { useEffect, useRef, useState } from "react";
import { useAnchoredPopover } from "@/hooks/use-anchored-popover";
import { cn } from "@/lib/cn";
import { addDaysIso, formatLongDate, weekdayIndex } from "@/lib/format";
import { BottomSheet } from "./bottom-sheet";
import { ChevronLeftIcon, ChevronRightIcon } from "./icons";

// Chọn một ngày từ lịch tháng (tuần bắt đầu T2). Máy tính: popover dưới nút; điện thoại (< sm): BottomSheet.
// Bàn phím: ← → ↑ ↓ đổi ngày, PageUp/PageDown đổi tháng, Home/End đầu/cuối tuần, Enter chọn, Esc đóng (focus về nút).

const WEEK = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
const pad = (n: number) => String(n).padStart(2, "0");
const monthOf = (d: string) => d.slice(0, 7);
/** Cùng ngày ở tháng lệch `n` (ngày 31 ⇒ ngày cuối tháng đích). */
const shiftMonth = (d: string, n: number) => {
  const [y, m, day] = d.split("-").map(Number);
  const first = new Date(Date.UTC(y, m - 1 + n, 1));
  const last = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate();
  return `${first.getUTCFullYear()}-${pad(first.getUTCMonth() + 1)}-${pad(Math.min(day, last))}`;
};

type Props = {
  value: string;
  today: string;
  onChange: (date: string) => void;
  className?: string;
};

export function DatePicker({ value, today, onChange, className }: Props) {
  const [open, setOpen] = useState(false);
  const [isSheet, setIsSheet] = useState(false);
  const anchorRef = useRef<HTMLDivElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const close = () => {
    setOpen(false);
    anchorRef.current?.querySelector("button")?.focus();
  };
  const pick = (d: string) => {
    close();
    if (d !== value) onChange(d);
  };
  // Lịch cao ~7 hàng ⇒ itemCount 7 để hook lật lên khi gần đáy màn hình
  const place = useAnchoredPopover({ isOpen: open && !isSheet, anchorRef, popoverRef: popRef, itemCount: 7, onDismiss: () => setOpen(false) });

  return (
    <div ref={anchorRef} className={className}>
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Chọn ngày, đang xem ${formatLongDate(value)}`}
        onClick={() => {
          setIsSheet(!window.matchMedia("(min-width: 40rem)").matches);
          setOpen(!open);
        }}
        className={cn(
          `
            relative inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-lg px-2
            text-sm font-semibold tabular-nums
          `,
          `
            focus-ring
            before:absolute before:inset-x-0 before:-inset-y-1.5
            hover:bg-primary-softer
            sm:h-9
          `,
        )}
      >
        {/* Chữ thuần, không icon (người dùng chốt); hover / focus-ring cho biết bấm được */}
        {formatLongDate(value)}
      </button>
      {open && isSheet ? (
        <BottomSheet open onClose={close} title="Chọn ngày">
          <MonthCalendar value={value} today={today} onPick={pick} />
        </BottomSheet>
      ) : null}
      {open && !isSheet ? (
        <div
          ref={popRef}
          role="dialog"
          aria-label="Chọn ngày"
          popover="manual"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              close();
            }
          }}
          style={place ? { position: "fixed", inset: "auto", ...place } : { visibility: "hidden" }}
          className="z-50 m-0 w-80 animate-scale-in rounded-card border bg-surface p-2 shadow-card"
        >
          <MonthCalendar value={value} today={today} onPick={pick} />
        </div>
      ) : null}
    </div>
  );
}

/** Lưới tháng (role grid): ngày đang xem tô primary, hôm nay viền primary, roving tabindex. */
function MonthCalendar({ value, today, onPick }: { value: string; today: string; onPick: (d: string) => void }) {
  const [focus, setFocus] = useState(value);
  const gridRef = useRef<HTMLTableElement>(null);
  // Chỉ đưa focus vào lưới khi mở lịch hoặc đi bằng phím (bấm ‹ › đổi tháng thì focus ở lại nút)
  const moveFocus = useRef(true);
  const month = monthOf(focus);
  const [y, m] = month.split("-").map(Number);

  // Focus theo ngày đang trỏ (mở lịch ⇒ vào ngày đang xem)
  // rAF: popover chỉ hiện (showPopover) sau effect của lưới ⇒ đợi một khung hình rồi mới focus được
  useEffect(() => {
    if (!moveFocus.current) return;
    const id = requestAnimationFrame(() => gridRef.current?.querySelector<HTMLElement>(`[data-date="${focus}"]`)?.focus());
    return () => cancelAnimationFrame(id);
  }, [focus]);
  const goMonth = (n: number) => {
    moveFocus.current = false;
    setFocus(shiftMonth(focus, n));
  };

  const first = `${month}-01`;
  const start = addDaysIso(first, -weekdayIndex(first));
  const days = Array.from({ length: 42 }, (_, i) => addDaysIso(start, i));
  const weeks = Array.from({ length: days[35].startsWith(month) ? 6 : 5 }, (_, w) => days.slice(w * 7, w * 7 + 7));

  function onKey(e: React.KeyboardEvent) {
    const step: Record<string, () => string> = {
      ArrowLeft: () => addDaysIso(focus, -1),
      ArrowRight: () => addDaysIso(focus, 1),
      ArrowUp: () => addDaysIso(focus, -7),
      ArrowDown: () => addDaysIso(focus, 7),
      PageUp: () => shiftMonth(focus, -1),
      PageDown: () => shiftMonth(focus, 1),
      Home: () => addDaysIso(focus, -weekdayIndex(focus)),
      End: () => addDaysIso(focus, 6 - weekdayIndex(focus)),
    };
    if (!step[e.key]) return;
    e.preventDefault();
    moveFocus.current = true;
    setFocus(step[e.key]());
  }

  const navBtn = "relative grid size-8 place-items-center rounded-lg text-muted hover:bg-primary-softer hover:text-primary focus-ring before:absolute before:-inset-1.5 [&>svg]:size-4";
  return (
    <div className="px-1">
      <div className="mb-1 flex items-center justify-between gap-2">
        <button type="button" aria-label="Tháng trước" onClick={() => goMonth(-1)} className={navBtn}>
          <ChevronLeftIcon aria-hidden />
        </button>
        <p aria-live="polite" className="text-sm font-semibold">
          Tháng {m}/{y}
        </p>
        <button type="button" aria-label="Tháng sau" onClick={() => goMonth(1)} className={navBtn}>
          <ChevronRightIcon aria-hidden />
        </button>
      </div>
      <table ref={gridRef} role="grid" aria-label={`Tháng ${m}/${y}`} onKeyDown={onKey} className={cn(`
        w-full table-fixed border-separate border-spacing-0.5 text-center
      `)}>
        <thead>
          <tr>
            {WEEK.map((d) => (
              <th key={d} scope="col" className="h-8 text-xs font-semibold text-muted">
                {d}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((week) => (
            <tr key={week[0]}>
              {week.map((d) => {
                const isValue = d === value;
                const isToday = d === today;
                return (
                  <td key={d} role="gridcell" aria-selected={isValue}>
                    <button
                      type="button"
                      data-date={d}
                      tabIndex={d === focus ? 0 : -1}
                      aria-label={`${formatLongDate(d)}${isToday ? ", hôm nay" : ""}`}
                      aria-current={isToday ? "date" : undefined}
                      onClick={() => onPick(d)}
                      className={cn(
                        "h-10 w-full rounded-lg text-sm tabular-nums focus-ring sm:h-9",
                        isValue ? "bg-primary font-semibold text-white" : "hover:bg-primary-softer",
                        !isValue && isToday && `
                          font-semibold text-primary ring-1 ring-primary ring-inset
                        `,
                        !isValue && !isToday && !d.startsWith(month) && "text-subtle",
                      )}
                    >
                      {Number(d.slice(8))}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-1 flex justify-end border-t pt-2">
        <button type="button" onClick={() => onPick(today)} className={cn(`
          relative h-8 rounded-lg px-3 text-sm font-semibold text-primary focus-ring
          before:absolute before:inset-x-0 before:-inset-y-1.5
          hover:bg-primary-softer
        `)}>
          Hôm nay
        </button>
      </div>
    </div>
  );
}
