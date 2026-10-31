"use client";

import { useId, useMemo, useState } from "react";
import { vnDate, vnMinutes } from "@/lib/format";
import type { Calendar } from "./types";
import { btnCls, btnPrimaryCls, inputCls } from "./ui";

export type Block = { resource_code: string; start_hour: number; end_hour: number };

export const MAX_BLOCKS = 20;
const pad2 = (n: number) => String(n).padStart(2, "0");
export const hourText = (h: number) => `${pad2(h)}:00`;
export const blockKey = (b: Block) => `${b.resource_code}|${b.start_hour}`;

/** Giờ của sân `code` còn đặt được: mở cửa, chưa qua, không có khối khác (lịch) và không trùng khối đã chọn. */
function freeHours(calendar: Calendar, code: string, chosen: Block[]): Set<number> {
  const res = calendar.resources.find((r) => r.code === code);
  const free = new Set<number>();
  if (!res || !res.is_active) return free;
  // Giờ hiện tại theo server, múi giờ Việt Nam: ô đã qua chỉ có ở hôm nay
  const nowMin = vnMinutes(calendar.now);
  const today = vnDate(calendar.now);
  for (const h of calendar.columns) {
    if (res.off_hours.includes(h)) continue;
    if (calendar.date === today && (h + 1) * 60 <= nowMin) continue;
    if (calendar.blocks.some((b) => b.resource_codes.includes(code) && b.start_hour <= h && h < b.end_hour)) continue;
    if (chosen.some((b) => b.resource_code === code && b.start_hour <= h && h < b.end_hour)) continue;
    free.add(h);
  }
  return free;
}

/**
 * "+ Thêm khối" trong popup đặt quầy (T-019): chọn sân + giờ bắt đầu / kết thúc cùng ngày.
 * Chỉ cho chọn giờ còn trống nên khối thêm vào luôn hợp lệ; server vẫn kiểm lại (409 E-003 → đánh dấu khối trùng).
 * Dùng `<select>` gốc: dùng được trên màn cảm ứng.
 */
export function BlockAdder({ calendar, chosen, onAdd, onCancel }: { calendar: Calendar; chosen: Block[]; onAdd: (b: Block) => void; onCancel: () => void }) {
  const ids = { court: useId(), start: useId(), end: useId() };
  const courts = useMemo(() => calendar.resources.filter((r) => r.is_active), [calendar.resources]);
  const [court, setCourt] = useState(courts[0]?.code ?? "");
  const [start, setStart] = useState<number | null>(null);
  const [end, setEnd] = useState<number | null>(null);
  const [error, setError] = useState("");

  const free = useMemo(() => freeHours(calendar, court, chosen), [calendar, court, chosen]);
  const starts = calendar.columns.filter((h) => free.has(h));
  // Giờ kết thúc: các giờ liền nhau còn trống kể từ giờ bắt đầu
  const ends: number[] = [];
  if (start !== null) for (let h = start; free.has(h); h++) ends.push(h + 1);

  function submit() {
    if (start === null || end === null) return setError("Vui lòng chọn giờ bắt đầu và giờ kết thúc.");
    setError("");
    onAdd({ resource_code: court, start_hour: start, end_hour: end });
  }

  const sel = `${inputCls} h-11 sm:h-10`;
  return (
    <fieldset className="space-y-3 rounded-lg border border-border p-3">
      <legend className="px-1 text-sm font-semibold">Thêm khối</legend>
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <label htmlFor={ids.court} className="mb-1 block text-xs font-medium text-muted">
            Sân
          </label>
          <select
            id={ids.court}
            value={court}
            onChange={(e) => {
              setCourt(e.target.value);
              setStart(null);
              setEnd(null);
              setError("");
            }}
            className={sel}
          >
            {courts.map((r) => (
              <option key={r.code} value={r.code}>
                {r.code} · {r.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={ids.start} className="mb-1 block text-xs font-medium text-muted">
            Từ giờ
          </label>
          <select
            id={ids.start}
            value={start ?? ""}
            onChange={(e) => {
              const v = e.target.value === "" ? null : Number(e.target.value);
              setStart(v);
              setEnd(v === null ? null : v + 1);
              setError("");
            }}
            className={sel}
          >
            <option value="">{starts.length ? "Chọn giờ" : "Hết giờ trống"}</option>
            {starts.map((h) => (
              <option key={h} value={h}>
                {hourText(h)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={ids.end} className="mb-1 block text-xs font-medium text-muted">
            Đến giờ
          </label>
          <select id={ids.end} value={end ?? ""} disabled={start === null} onChange={(e) => setEnd(Number(e.target.value))} className={sel}>
            {ends.map((h) => (
              <option key={h} value={h}>
                {hourText(h)}
              </option>
            ))}
          </select>
        </div>
      </div>
      {error ? (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onCancel} className={`${btnCls} h-11 sm:h-auto`}>
          Hủy
        </button>
        <button type="button" onClick={submit} className={`${btnPrimaryCls} h-11 sm:h-auto`}>
          Thêm
        </button>
      </div>
    </fieldset>
  );
}
