"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";
import { formatLongDate, weekdayIndex } from "@/lib/format";

// Nút ngày + lịch tháng bật ra (kiểu ứng dụng đặt sân như Alobo, người dùng 12/11): bấm nút ⇒ lịch tháng, ‹ › đổi tháng,
// chọn ngày bất kỳ từ hôm nay đến hết `months` tháng tới; ngày đã qua mờ, không bấm được. Lịch mở giữa màn hình
// (nền mờ, khóa cuộn); Esc / bấm nền để đóng.

const WEEK = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
const ym = (d: string) => d.slice(0, 7);
const addMonths = (m: string, n: number) => new Date(Date.UTC(Number(m.slice(0, 4)), Number(m.slice(5, 7)) - 1 + n, 1)).toISOString().slice(0, 7);
const daysIn = (m: string) => new Date(Date.UTC(Number(m.slice(0, 4)), Number(m.slice(5, 7)), 0)).getUTCDate();

type Props = { date: string; today: string; months: number; onPick: (date: string) => void };

export function DatePicker({ date, today, months, onPick }: Props) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState(ym(date));
  const pop = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const first = ym(today);
  const last = addMonths(first, months - 1);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      trigger.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    // Lịch mở thì khóa cuộn nền
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    pop.current?.querySelector<HTMLElement>("[aria-pressed='true'], button:not(:disabled)")?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open]);

  const lead = weekdayIndex(`${view}-01`);
  const cells = [...Array<null>(lead).fill(null), ...Array.from({ length: daysIn(view) }, (_, i) => `${view}-${String(i + 1).padStart(2, "0")}`)];
  const nav = "grid size-9 place-items-center rounded-lg text-lg hover:bg-primary-softer focus-ring disabled:opacity-30 disabled:hover:bg-transparent";

  return (
    <div className="relative">
      <button
        ref={trigger}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          setView(ym(date));
          setOpen((o) => !o);
        }}
        aria-label={`Chọn ngày, đang xem ${formatLongDate(date)}`}
        className="-ml-1 flex h-10 items-center gap-1.5 rounded-lg px-1 text-base font-bold text-surface hover:bg-surface/10 focus-ring sm:h-11 sm:text-lg"
      >
        {/* Chữ tháng gọn (không khung) + mũi tên – bấm mở lịch (người dùng 12/11) */}
        Tháng {Number(date.slice(5, 7))}, {date.slice(0, 4)}
        <svg viewBox="0 0 20 20" className="size-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="m5 7.5 5 5 5-5" />
        </svg>
      </button>
      {open
        ? createPortal(
        // Giữa màn hình, nền tối mờ phía sau; bấm nền để đóng
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/45 p-4" onClick={(e) => e.target === e.currentTarget && setOpen(false)}>
        <div ref={pop} role="dialog" aria-modal="true" aria-label="Chọn ngày" className="w-full max-w-80 rounded-2xl bg-surface p-4 text-foreground shadow-card">
          <div className="flex items-center justify-between">
            <button type="button" aria-label="Tháng trước" disabled={view <= first} onClick={() => setView(addMonths(view, -1))} className={nav}>
              ‹
            </button>
            <p className="text-sm font-bold">
              Tháng {Number(view.slice(5, 7))}, {view.slice(0, 4)}
            </p>
            <button type="button" aria-label="Tháng sau" disabled={view >= last} onClick={() => setView(addMonths(view, 1))} className={nav}>
              ›
            </button>
          </div>
          <div className="mt-2 grid grid-cols-7 text-center text-[0.6875rem] font-semibold text-muted">
            {WEEK.map((w) => (
              <span key={w} className={cn("py-1", w === "T7" || w === "CN" ? "text-accent-fg" : "")}>
                {w}
              </span>
            ))}
          </div>
          <div role="grid" aria-label={`Tháng ${Number(view.slice(5, 7))}`} className="grid grid-cols-7 gap-0.5">
            {cells.map((d, i) =>
              d ? (
                <button
                  key={d}
                  type="button"
                  disabled={d < today}
                  aria-pressed={d === date}
                  aria-label={formatLongDate(d)}
                  onClick={() => {
                    setOpen(false);
                    if (d !== date) onPick(d);
                  }}
                  className={cn(
                    "grid aspect-square place-items-center rounded-lg text-sm tabular-nums focus-ring",
                    d === date ? "bg-primary font-bold text-surface" : "hover:bg-primary-softer",
                    d === today && d !== date && "font-bold text-primary ring-1 ring-primary/40",
                    d < today && "text-subtle hover:bg-transparent",
                  )}
                >
                  {Number(d.slice(8, 10))}
                </button>
              ) : (
                <span key={`e${i}`} aria-hidden />
              ),
            )}
          </div>
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              if (today !== date) onPick(today);
            }}
            className="mt-2 h-9 w-full rounded-lg text-sm font-semibold text-primary hover:bg-primary-softer focus-ring"
          >
            Hôm nay
          </button>
        </div>
        </div>,
        document.body,
      )
        : null}
    </div>
  );
}
