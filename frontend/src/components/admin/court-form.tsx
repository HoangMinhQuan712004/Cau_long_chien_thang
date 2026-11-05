"use client";

import { useId } from "react";
import { TrashIcon } from "@/components/ui/icons";
import { formatDayMonth, formatDayMonthYear } from "@/lib/format";
import { hhmm, t5, TIMES, toMin, type Band, type Form, type ResourceType } from "./court-form-logic";
import type { CourtFormState } from "./use-court-form";

const INPUT = "w-full rounded-md border border-border bg-background px-3 py-2 text-sm";

/** Các ô của form sân (dùng trong popup "Thêm sân" và ngăn chi tiết): lỗi server, tên, loại, giờ mở cửa, cao điểm, trạng thái. */
export function CourtForm({ state, types, onReload }: { state: CourtFormState; types: ResourceType[]; onReload: () => void }) {
  const { f, setF, touched, setTouched, submitted, banner, err, tomorrow } = state;
  const ids = { name: useId(), nameErr: useId(), open: useId(), close: useId(), closeErr: useId() };
  const edit = f.mode === "edit";
  const showName = submitted || touched.name;
  const showHours = submitted || touched.hours;
  const showPeaks = submitted || touched.peaks;
  const slots = Math.max(0, (toMin(f.close) - toMin(f.open)) / 30);
  const patch = (p: Partial<Form>) => setF((cur) => ({ ...cur, ...p }));
  const setPeak = (i: number, j: 0 | 1, v: string) => {
    setTouched((t) => ({ ...t, peaks: true }));
    setF((cur) => ({ ...cur, peaks: cur.peaks.map((p, k) => (k === i ? (j === 0 ? [v, p[1]] : [p[0], v]) : p) as Band) }));
  };

  return (
    <div className="space-y-4">
      {banner ? (
        <div role="alert" className="rounded-md border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          <p>{banner.text}</p>
          {banner.items?.length ? (
            <ul className="mt-1.5 list-disc pl-5">
              {banner.items.slice(0, 6).map((it) => (
                <li key={`${it.code}-${it.date}-${it.start_time}`}>
                  {it.code} · {formatDayMonth(it.date)} {t5(it.start_time)}–{t5(it.end_time)}
                </li>
              ))}
              {banner.more ? <li>… và {banner.more} khung khác</li> : null}
            </ul>
          ) : null}
          {banner.reload ? (
            <button type="button" onClick={onReload} className="mt-2 rounded-md border border-danger/50 px-3 py-1 text-xs font-medium">
              Tải lại
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-sm font-medium">Mã sân</label>
          <input readOnly value={f.code ?? "Tự cấp khi thêm"} className={`${INPUT} text-muted`} />
          <p className="mt-1 text-xs text-muted">Hệ thống cấp, cố định.</p>
        </div>
        <div>
          <label htmlFor={ids.name} className="mb-1 block text-sm font-medium">
            Tên sân <span className="text-danger">*</span>
          </label>
          <input
            id={ids.name}
            value={f.name}
            maxLength={50}
            placeholder="VD: Sân 7"
            onChange={(e) => patch({ name: e.target.value })}
            onBlur={() => setTouched((t) => ({ ...t, name: true }))}
            aria-invalid={Boolean(showName && err.name)}
            aria-describedby={showName && err.name ? ids.nameErr : undefined}
            className={INPUT}
          />
          {showName && err.name ? <p id={ids.nameErr} className="mt-1 text-xs text-danger">{err.name}</p> : null}
        </div>
      </div>

      <fieldset>
        <legend className="mb-1 text-sm font-medium">
          Loại sân <span className="text-danger">*</span>
        </legend>
        <div className="flex flex-wrap gap-4 text-sm">
          {types.map((t) => (
            <label key={t.code} className="flex min-h-11 items-center gap-2">
              <input type="radio" name="resource-type" checked={f.type === t.code} onChange={() => patch({ type: t.code })} />
              {t.name}
            </label>
          ))}
        </div>
        <p className="mt-1 text-xs text-muted">Giá thuê lấy theo Loại sân ở tab Bảng giá.</p>
      </fieldset>

      <div>
        <p className="mb-2 text-sm font-semibold">Giờ hoạt động{edit ? ` · áp dụng từ ngày mai, ${formatDayMonthYear(tomorrow)}` : ""}</p>
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label htmlFor={ids.open} className="mb-1 block text-sm font-medium">Mở cửa</label>
            <TimeSelect id={ids.open} value={f.open} onChange={(v) => (setTouched((t) => ({ ...t, hours: true })), patch({ open: v }))} />
          </div>
          <div>
            <label htmlFor={ids.close} className="mb-1 block text-sm font-medium">Đóng cửa</label>
            <TimeSelect
              id={ids.close}
              value={f.close}
              invalid={Boolean(showHours && err.close)}
              describedBy={showHours && err.close ? ids.closeErr : undefined}
              onChange={(v) => (setTouched((t) => ({ ...t, hours: true })), patch({ close: v }))}
            />
            {showHours && err.close ? <p id={ids.closeErr} className="mt-1 text-xs text-danger">{err.close}</p> : null}
          </div>
          <div>
            <span className="mb-1 block text-sm font-medium">Số khung</span>
            {/* Cùng khung với hai ô chọn giờ bên cạnh để ba cột thẳng hàng (dev T-044) */}
            <p className="rounded-md border border-transparent bg-background/60 px-3 py-2 text-sm text-muted">{slots} khung 30 phút mỗi ngày</p>
          </div>
        </div>
      </div>

      <fieldset>
        <legend className="mb-2 text-sm font-semibold">Giờ cao điểm</legend>
        <div className="space-y-2">
          {f.peaks.map((p, i) => {
            const bad = showPeaks && (err.peaks[i] || err.overlapIdx?.includes(i));
            return (
              <div key={i}>
                {/* Hàng khung giờ: Từ – Đến cùng cỡ cột Mở cửa / Đóng cửa phía trên, nút xóa là icon (dev T-044) */}
                <div className={`grid grid-cols-[1fr_auto_1fr_auto] items-center gap-2 rounded-md sm:grid-cols-[minmax(0,10rem)_auto_minmax(0,10rem)_auto] ${bad ? "ring-1 ring-danger" : ""}`}>
                  <TimeSelect label="Từ" value={p[0]} onChange={(v) => setPeak(i, 0, v)} />
                  <span aria-hidden className="text-muted">
                    –
                  </span>
                  <TimeSelect label="Đến" value={p[1]} onChange={(v) => setPeak(i, 1, v)} />
                  <button
                    type="button"
                    title="Xóa khung giờ"
                    onClick={() => (setTouched((t) => ({ ...t, peaks: true })), setF((cur) => ({ ...cur, peaks: cur.peaks.filter((_, k) => k !== i) })))}
                    // Điện thoại 44px (vùng chạm), từ sm 36px như dev
                    className="grid size-11 place-items-center rounded-md text-muted hover:bg-danger-soft hover:text-danger focus-ring sm:size-9"
                  >
                    <TrashIcon size={16} />
                    <span className="sr-only">Xóa khung cao điểm {i + 1}</span>
                  </button>
                </div>
                {showPeaks && err.peaks[i] ? <p className="mt-1 text-xs text-danger">{err.peaks[i]}</p> : null}
              </div>
            );
          })}
          {showPeaks && err.overlap ? <p className="text-xs text-danger">{err.overlap}</p> : null}
          <button
            type="button"
            onClick={() => setF((cur) => ({ ...cur, peaks: [...cur.peaks, [cur.open, hhmm(Math.min(toMin(cur.open) + 60, toMin(cur.close)))]] }))}
            className="min-h-11 text-sm text-primary hover:underline"
          >
            + Thêm khung giờ
          </button>
        </div>
        <p className="mt-2 text-xs text-muted">Các khung không được chồng nhau và phải nằm trong giờ mở cửa · giá cao điểm theo Loại sân ở tab Bảng giá.</p>
      </fieldset>

      {edit ? (
        <fieldset>
          <legend className="mb-1 text-sm font-medium">Trạng thái</legend>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex min-h-11 items-center gap-2">
              <input type="radio" name="resource-active" checked={f.active} onChange={() => patch({ active: true })} />
              Hoạt động
            </label>
            <label className="flex min-h-11 items-center gap-2">
              <input type="radio" name="resource-active" checked={!f.active} onChange={() => patch({ active: false })} />
              Ngừng hoạt động
            </label>
          </div>
          <p className="mt-1 text-xs text-muted">Ngừng: khách không thấy, không đặt được sân.</p>
        </fieldset>
      ) : null}
    </div>
  );
}

function TimeSelect({ id, value, onChange, label, invalid, describedBy }: { id?: string; value: string; onChange: (v: string) => void; label?: string; invalid?: boolean; describedBy?: string }) {
  return (
    <select id={id} value={value} aria-label={label} aria-invalid={invalid || undefined} aria-describedby={describedBy} onChange={(e) => onChange(e.target.value)} className={INPUT}>
      {TIMES.map((t) => (
        <option key={t} value={t}>
          {t}
        </option>
      ))}
    </select>
  );
}
