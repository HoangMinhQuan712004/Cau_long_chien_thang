"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { Skeleton } from "@/components/ui/skeleton";
import type { Dictionary } from "@/i18n/dictionaries";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { fill, formatVnd, vnDate, weekdayIndex } from "@/lib/format";
import type { Block } from "./block";
import { authFailure, STALE_CODES } from "./booking-dialogs";
import { CustomerPicker, customerErrors, customerPayload, emptyCustomer, type CustomerErrors } from "./customer-picker";
import { sendSeries } from "./requests";
import { SeriesFields } from "./series-fields";
import { SeriesPreviewList } from "./series-preview";
import type { Calendar, SeriesParams } from "./types";
import { useSeriesPreview } from "./use-series-preview";

// Đặt theo tháng tại quầy: chọn tháng / sân / giờ / thứ ⇒ tự kiểm lịch (preview) ⇒ tích ngày ⇒ Đặt gói (một lệnh, Idempotency-Key).
// 409 ⇒ đánh dấu đỏ ngày trùng, giữ hộp mở để đặt lại các ngày còn lại.

type T = Dictionary["series"];
type Props = {
  calendar: Calendar;
  /** Một khối đang chọn trên lưới ⇒ điền sẵn sân, giờ, thứ + tháng của ngày đang xem. */
  prefill?: Block | null;
  t: T;
  onClose: () => void;
  onBooked: (code: string) => void;
};

const MONTHS_AHEAD = 6;

/** Tháng hiện tại (giờ VN) và các tháng sau, dạng "YYYY-MM". */
function nextMonths(nowIso: string): string[] {
  const [y, m] = vnDate(nowIso).split("-").map(Number);
  return Array.from({ length: MONTHS_AHEAD }, (_, i) => {
    const d = new Date(Date.UTC(y, m - 1 + i, 1));
    return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
  });
}

function initialParams(calendar: Calendar, months: string[], prefill?: Block | null): SeriesParams {
  const hours = calendar.columns;
  if (prefill) {
    const month = calendar.date.slice(0, 7);
    return { ...prefill, month: months.includes(month) ? month : months[0], weekdays: [weekdayIndex(calendar.date) + 1] };
  }
  const start = hours.includes(17) ? 17 : hours[0];
  return {
    resource_code: calendar.resources.find((r) => r.is_active)?.code ?? "",
    month: months[0],
    weekdays: [],
    start_hour: start,
    end_hour: Math.min(start + 2, hours[hours.length - 1] + 1),
  };
}

export function SeriesDialog({ calendar, prefill, t, onClose, onBooked }: Props) {
  const [months] = useState(() => nextMonths(calendar.now));
  const [params, setParams] = useState(() => initialParams(calendar, months, prefill));
  const [customer, setCustomer] = useState(emptyCustomer);
  const [serverErrors, setServerErrors] = useState<CustomerErrors>({});
  const [submitted, setSubmitted] = useState(false);
  const [banner, setBanner] = useState("");
  const [busy, setBusy] = useState(false);
  const preview = useSeriesPreview(params);
  const courts = calendar.resources.filter((r) => r.is_active);

  function change(patch: Partial<SeriesParams>) {
    setParams((p) => ({ ...p, ...patch }));
    setBanner("");
  }

  async function submit() {
    setSubmitted(true);
    setBanner("");
    setServerErrors({});
    const payload = customerPayload(customer);
    const chosen = (preview.dates ?? []).filter((d) => preview.picked.has(d.date)).map((d) => d.date);
    if (Object.keys(customerErrors(customer)).length || !payload || !chosen.length) return;
    setBusy(true);
    try {
      const res = await write((key) => sendSeries(key, { ...params, dates: chosen, customer: payload }));
      if (res.ok) {
        toast(fill(t.booked, { code: res.data.code, n: chosen.length }), t.bookedSub);
        onBooked(res.data.code);
        return;
      }
      const e = res.error;
      if (authFailure(e)) return;
      if (e.status === 409 && Array.isArray(e.extra.conflicts)) {
        preview.markConflicts(e.extra.conflicts as { date: string; reason?: string }[]);
        setBanner(t.conflict);
      } else if (e.code && STALE_CODES.includes(e.code)) setBanner(errorText(e));
      else if (e.code === "E-018" || e.code === "E-002") setServerErrors({ phone: errorText(e) });
      else if (e.code === "E-014") setServerErrors({ pick: errorText(e) });
      else setBanner(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      sheet
      onClose={onClose}
      title={t.title}
      footer={
        <>
          <p aria-live="polite" className="mr-auto self-center text-sm font-semibold tabular-nums">
            {preview.dates ? fill(t.summary, { n: preview.picked.size, total: formatVnd(preview.total) }) : null}
          </p>
          <Button variant="secondary" onClick={onClose} disabled={busy}>{t.cancel}</Button>
          <Button onClick={() => void submit()} disabled={!preview.picked.size} loading={busy}>
            {busy ? t.submitting : t.submit}
          </Button>
        </>
      }
    >
      {banner ? <Alert>{banner}</Alert> : null}
      <SeriesFields value={params} onChange={change} months={months} courts={courts} hours={calendar.columns} t={t} />
      {preview.need ? <p className="text-ui text-muted">{t.needWeekday}</p> : null}
      {preview.isLoading ? (
        <div className="flex flex-col gap-2" aria-busy>
          <p role="status" className="sr-only">{t.checking}</p>
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-11 w-full" />)}
        </div>
      ) : null}
      {preview.error ? (
        <div className="flex flex-wrap items-center gap-2">
          <Alert className="flex-1">{preview.error}</Alert>
          <Button variant="secondary" onClick={preview.retry}>{t.retry}</Button>
        </div>
      ) : null}
      {preview.dates ? <SeriesPreviewList dates={preview.dates} picked={preview.picked} onToggle={preview.toggle} t={t} /> : null}
      <div className="flex flex-col gap-2 border-t pt-4">
        <h3 className="text-sm font-semibold">{t.customer}</h3>
        <CustomerPicker state={customer} onChange={setCustomer} submitted={submitted} serverErrors={serverErrors} />
      </div>
    </Modal>
  );
}
