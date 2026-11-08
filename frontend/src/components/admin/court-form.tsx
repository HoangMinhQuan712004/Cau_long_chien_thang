"use client";

import { useId, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, fieldErrorId } from "@/components/ui/field";
import { IconButton } from "@/components/ui/icon-button";
import { PlusIcon, TrashIcon } from "@/components/ui/icons";
import { Input } from "@/components/ui/input";
import { RadioGroup } from "@/components/ui/radio-group";
import type { Dictionary } from "@/i18n/dictionaries";
import { formatDayMonth, formatDayMonthYear } from "@/lib/format";
import { Dropdown } from "@/components/ui/dropdown";
import { cn } from "@/lib/cn";
import { closeHours, firstFreePeak, fitPeaks, hhmm, openHours, peakFromHours, peakToHours, sortBands, t5, toMin, withPeakFrom, type Band, type Form, type ResourceType } from "./court-form-logic";
import type { CourtFormState } from "./use-court-form";

const SECTION = "flex flex-col gap-3 border-t pt-4 first:border-t-0 first:pt-0";
const SECTION_TITLE = "text-sm font-semibold";

/** Các ô của form sân (dùng trong popup "Thêm sân" và ngăn chi tiết): lỗi server, tên, loại, giờ mở cửa, cao điểm, trạng thái. */
export function CourtForm({ state, types, onReload, t: courts }: { state: CourtFormState; types: ResourceType[]; onReload: () => void; t: Dictionary["courts"] }) {
  const t = courts.form;
  const { f, setF, touched, setTouched, submitted, banner, err, tomorrow } = state;
  const ids = { name: useId(), open: useId(), close: useId() };
  const [adjusted, setAdjusted] = useState(false);
  const edit = f.mode === "edit";
  const nameError = (submitted || touched.name) && err.name ? err.name : undefined;
  const closeError = (submitted || touched.hours) && err.close ? err.close : undefined;
  const showPeaks = submitted || touched.peaks;
  const slots = Math.max(0, Math.floor((toMin(f.close) - toMin(f.open)) / 60));
  // Dữ liệu cũ có giờ rưỡi: vẫn hiện đúng giá trị để không mất im lặng, báo cần đổi sang giờ chẵn
  const hasHalfHour = [f.open, f.close, ...f.peaks.flat()].some((x) => !x.endsWith(":00"));
  const patch = (p: Partial<Form>) => setF((cur) => ({ ...cur, ...p }));
  const touchHours = () => setTouched((x) => ({ ...x, hours: true }));
  const nextPeak = firstFreePeak(f);
  // Đổi giờ mở / đóng: khung ra ngoài tự co về trong giờ mở, báo một dòng dưới phần cao điểm
  const setHours = (open: string, close: string) => {
    const fitted = fitPeaks(f.peaks, open, close);
    touchHours();
    setAdjusted(fitted.changed);
    patch({ open, close, peaks: fitted.peaks });
  };
  const setPeak = (i: number, band: Band) => {
    setTouched((x) => ({ ...x, peaks: true }));
    setF((cur) => ({ ...cur, peaks: cur.peaks.map((p, k) => (k === i ? band : p)) }));
  };

  return (
    <div className="flex flex-col gap-4">
      {banner ? (
        <Alert variant="error">
          <span className="flex flex-col gap-1.5">
            <span>{banner.text}</span>
            {banner.items?.length ? (
              <ul className="list-disc pl-5">
                {banner.items.slice(0, 6).map((it) => (
                  <li key={`${it.code}-${it.date}-${it.start_time}`}>
                    {it.code} · {formatDayMonth(it.date)} {t5(it.start_time)}–{t5(it.end_time)}
                  </li>
                ))}
                {banner.more ? <li>{t.moreConflicts.replace("{n}", String(banner.more))}</li> : null}
              </ul>
            ) : null}
            {banner.reload ? (
              <Button type="button" variant="secondary" onClick={onReload} className="w-fit">
                {t.reload}
              </Button>
            ) : null}
          </span>
        </Alert>
      ) : null}

      <section className={SECTION}>
        <Field label={`${t.nameLabel} *`} htmlFor={ids.name} error={nameError}>
          <Input
            id={ids.name}
            value={f.name}
            maxLength={50}
            placeholder={t.namePlaceholder}
            onChange={(e) => patch({ name: e.target.value })}
            onBlur={() => setTouched((x) => ({ ...x, name: true }))}
            aria-invalid={nameError ? true : undefined}
            aria-describedby={nameError ? fieldErrorId(ids.name) : undefined}
          />
        </Field>
        <RadioGroup
          name="resource-type"
          legend={`${t.typeLabel} *`}
          options={types.map((x) => ({ value: x.code, label: x.name }))}
          value={f.type}
          onChange={(type) => patch({ type })}
        />
      </section>

      <section className={SECTION}>
        <h3 className={SECTION_TITLE}>{edit ? t.hoursTitleEdit.replace("{date}", formatDayMonthYear(tomorrow)) : t.hoursTitle}</h3>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t.open} htmlFor={ids.open}>
            <TimeSelect id={ids.open} label={t.open} hours={openHours(f)} value={f.open} onChange={(v) => setHours(v, f.close)} />
          </Field>
          <Field label={t.close} htmlFor={ids.close} error={closeError}>
            <TimeSelect id={ids.close} label={t.close} hours={closeHours(f)} value={f.close} invalid={Boolean(closeError)} onChange={(v) => setHours(f.open, v)} />
          </Field>
        </div>
        <p className="text-ui text-muted">{t.slots.replace("{n}", String(slots))}</p>
        {hasHalfHour ? <p role="alert" className="text-ui text-danger">{t.halfHourWarning}</p> : null}
      </section>

      <section className={SECTION}>
        <h3 className={SECTION_TITLE}>{t.peaksTitle}</h3>
        {f.peaks.map((p, i) => {
          const bad = showPeaks && Boolean(err.peaks[i] || err.overlapIdx?.includes(i));
          return (
            <div key={i} className="flex flex-col gap-1">
              <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto] items-center gap-2">
                <TimeSelect label={t.peakFrom} hours={peakFromHours(f, i)} value={p[0]} invalid={bad} onChange={(v) => setPeak(i, withPeakFrom(f, i, v))} />
                <span aria-hidden className="text-muted">–</span>
                <TimeSelect label={t.peakTo} hours={peakToHours(f, i)} value={p[1]} invalid={bad} onChange={(v) => setPeak(i, [p[0], v])} />
                <IconButton
                  icon={<TrashIcon />}
                  variant="danger"
                  label={t.removePeak.replace("{n}", String(i + 1))}
                  tooltip={t.removePeakShort}
                  onClick={() => (setTouched((x) => ({ ...x, peaks: true })), setF((cur) => ({ ...cur, peaks: cur.peaks.filter((_, k) => k !== i) })))}
                />
              </div>
              {showPeaks && err.peaks[i] ? <p className="text-ui text-danger">{err.peaks[i]}</p> : null}
            </div>
          );
        })}
        {showPeaks && err.overlap ? <p className="text-ui text-danger">{err.overlap}</p> : null}
        {adjusted ? <p role="status" className="text-ui font-medium text-primary">{t.peaksAdjusted}</p> : null}
        <Button
          type="button"
          variant="secondary"
          className="w-fit"
          disabled={!nextPeak}
          onClick={() => nextPeak && patch({ peaks: sortBands([...f.peaks, nextPeak]) })}
        >
          <PlusIcon />
          {t.addPeak}
        </Button>
        <p className="text-ui text-muted">{t.peaksHint}</p>
      </section>

      {edit ? (
        <section className={SECTION}>
          <RadioGroup
            name="resource-active"
            legend={t.statusLabel}
            options={[
              { value: "active", label: courts.active },
              { value: "inactive", label: courts.inactive },
            ]}
            value={f.active ? "active" : "inactive"}
            onChange={(v) => patch({ active: v === "active" })}
          />
          <p className="text-ui text-muted">{t.statusHint}</p>
        </section>
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
