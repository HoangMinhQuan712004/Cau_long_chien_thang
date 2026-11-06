"use client";

import { useId, useState } from "react";
import { Dropdown } from "@/components/ui/dropdown";
import { TrashIcon } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { formatDayMonth, formatDayMonthYear } from "@/lib/format";
import { closeHours, firstFreePeak, fitPeaks, hhmm, openHours, peakFromHours, peakToHours, sortBands, t5, toMin, withPeakFrom, type Band, type Form, type ResourceType } from "./court-form-logic";
import type { CourtFormState } from "./use-court-form";

const INPUT = "w-full rounded-md border border-border bg-background px-3 py-2 text-sm";

/** Các ô của form sân (dùng trong popup "Thêm sân" và ngăn chi tiết): lỗi server, tên, loại, giờ mở cửa, cao điểm, trạng thái. */
export function CourtForm({ state, types, onReload }: { state: CourtFormState; types: ResourceType[]; onReload: () => void }) {
  const { f, setF, touched, setTouched, submitted, banner, err, tomorrow } = state;
  const ids = { name: useId(), nameErr: useId(), open: useId(), close: useId(), closeErr: useId() };
  const [adjusted, setAdjusted] = useState(false);
  const edit = f.mode === "edit";
  const showName = submitted || touched.name;
  const showHours = submitted || touched.hours;
  const showPeaks = submitted || touched.peaks;
  const slots = Math.max(0, Math.floor((toMin(f.close) - toMin(f.open)) / 60));
  // Dữ liệu cũ có giờ rưỡi: vẫn hiện đúng giá trị để không mất im lặng
  const hasHalfHour = [f.open, f.close, ...f.peaks.flat()].some((x) => !x.endsWith(":00"));
  const patch = (p: Partial<Form>) => setF((cur) => ({ ...cur, ...p }));
  const nextPeak = firstFreePeak(f);
  // Đổi giờ mở / đóng: khung ra ngoài tự co về trong giờ mở, báo một dòng dưới phần cao điểm
  const setHours = (open: string, close: string) => {
    const fitted = fitPeaks(f.peaks, open, close);
    setTouched((t) => ({ ...t, hours: true }));
    setAdjusted(fitted.changed);
    patch({ open, close, peaks: fitted.peaks });
  };
  const setPeak = (i: number, band: Band) => {
    setTouched((t) => ({ ...t, peaks: true }));
    setF((cur) => ({ ...cur, peaks: cur.peaks.map((p, k) => (k === i ? band : p)) }));
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
            <TimeSelect id={ids.open} label="Mở cửa" hours={openHours(f)} value={f.open} onChange={(v) => setHours(v, f.close)} />
          </div>
          <div>
            <label htmlFor={ids.close} className="mb-1 block text-sm font-medium">Đóng cửa</label>
            <TimeSelect
              id={ids.close}
              label="Đóng cửa"
              hours={closeHours(f)}
              value={f.close}
              invalid={Boolean(showHours && err.close)}
              onChange={(v) => setHours(f.open, v)}
            />
            {showHours && err.close ? <p id={ids.closeErr} className="mt-1 text-xs text-danger">{err.close}</p> : null}
          </div>
          <div>
            <span className="mb-1 block text-sm font-medium">Số khung</span>
            {/* Cùng khung với hai ô chọn giờ bên cạnh để ba cột thẳng hàng (dev T-044) */}
            <p className="rounded-md border border-transparent bg-background/60 px-3 py-2 text-sm text-muted">{slots} khung 1 giờ mỗi ngày</p>
          </div>
        </div>
        {hasHalfHour ? <p role="alert" className="mt-2 text-xs text-danger">Sân này còn giờ rưỡi từ dữ liệu cũ, vẫn giữ nguyên khi lưu. Giờ mới chỉ chọn được giờ chẵn.</p> : null}
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
                  <TimeSelect label="Từ" hours={peakFromHours(f, i)} value={p[0]} onChange={(v) => setPeak(i, withPeakFrom(f, i, v))} />
                  <span aria-hidden className="text-muted">
                    –
                  </span>
                  <TimeSelect label="Đến" hours={peakToHours(f, i)} value={p[1]} onChange={(v) => setPeak(i, [p[0], v])} />
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
          {adjusted ? <p role="status" className="text-xs font-medium text-primary">Đã chỉnh khung cao điểm theo giờ mở cửa mới. Lưu mới có hiệu lực.</p> : null}
          <button
            type="button"
            disabled={!nextPeak}
            onClick={() => nextPeak && patch({ peaks: sortBands([...f.peaks, nextPeak]) })}
            className="min-h-11 text-sm text-primary hover:underline disabled:text-muted disabled:no-underline"
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

// Cùng cao với ô nhập của form: 44 điện thoại, 38 từ sm
const TIME_SELECT = "[&>button]:h-11 [&>button]:text-sm sm:[&>button]:h-9.5";

/** Ô chọn giờ như popup đặt định kỳ, `hours` = các giờ hợp lệ (phút). Giá trị đang lưu ngoài danh sách (vd giờ rưỡi cũ) vẫn có một lựa chọn để không tự đổi. */
function TimeSelect({ id, value, hours, onChange, label, invalid }: { id?: string; value: string; hours: number[]; onChange: (v: string) => void; label: string; invalid?: boolean }) {
  const values = hours.map(hhmm);
  const all = values.includes(value) ? values : [...values, value].sort();
  return <Dropdown id={id} aria-label={label} value={value} onChange={onChange} options={all.map((v) => ({ value: v, label: v }))} className={cn(TIME_SELECT, "min-w-0", invalid && "[&>button]:border-danger")} />;
}
