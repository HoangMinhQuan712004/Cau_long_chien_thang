"use client";

import { useState } from "react";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorText, write, type ApiError } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDayMonthYear, todayVn } from "@/lib/format";
import { bandsOf, bannerFrom, hasErrors, sortBands, t5, validate, type Banner, type Form, type Resource } from "./court-form-logic";

const addDays = (isoDate: string, n: number) => {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

/** State + lưu form sân (thêm: POST; sửa: PATCH chỉ gửi trường đã đổi, giờ mới áp dụng từ ngày mai). */
export function useCourtForm(initial: Form, resources: Resource[], onSaved: (code: string) => void) {
  const [f, setF] = useState<Form>(initial);
  const [touched, setTouched] = useState<{ name?: boolean; hours?: boolean; peaks?: boolean }>({});
  const [submitted, setSubmitted] = useState(false);
  const [banner, setBanner] = useState<Banner | null>(null);
  const [busy, setBusy] = useState(false);
  const err = validate(f, resources);
  const tomorrow = addDays(todayVn(), 1);
  const dirty = JSON.stringify(f) !== JSON.stringify(initial);

  function fail(error: ApiError) {
    if (error.status === 401 || error.status === 403) return void toast(errorText(error), undefined, "error");
    setBanner(bannerFrom(error));
  }

  /** Trả true khi đã lưu (hoặc không có gì đổi), false khi còn lỗi. */
  async function submit(): Promise<boolean> {
    setSubmitted(true);
    setBanner(null);
    if (hasErrors(err)) return false;
    const peaks = sortBands(f.peaks);
    setBusy(true);
    try {
      if (f.mode === "add") {
        const res = await write((key) =>
          api.POST("/api/v1/booking/resources", {
            body: { name: f.name.trim(), resource_type_code: f.type, open_time: f.open, close_time: f.close, peak_bands: peaks },
            headers: { "Idempotency-Key": key },
          }),
        );
        if (!res.ok) return (fail(res.error), false);
        toast(`Đã thêm ${res.data.code} · ${res.data.name}. Khách đặt được ngay.`);
        onSaved(res.data.code);
        return true;
      }

      const orig = resources.find((r) => r.code === f.code);
      const base = orig?.pending_schedule ?? orig?.schedule;
      const hoursChanged =
        !base || f.open !== t5(base.open_time) || f.close !== t5(base.close_time) || JSON.stringify(peaks) !== JSON.stringify(bandsOf(base));
      const body: components["schemas"]["ResourceUpdate"] = { version: f.version ?? 0 };
      if (f.name.trim() !== orig?.name) body.name = f.name.trim();
      if (f.type !== orig?.resource_type_code) body.resource_type_code = f.type;
      if (f.active !== orig?.is_active) body.is_active = f.active;
      if (hoursChanged) Object.assign(body, { open_time: f.open, close_time: f.close, peak_bands: peaks });
      if (Object.keys(body).length === 1) return true; // không có gì thay đổi
      const res = await write((key) =>
        api.PATCH("/api/v1/booking/resources/{code}", { params: { path: { code: f.code! } }, body, headers: { "Idempotency-Key": key } }),
      );
      if (!res.ok) return (fail(res.error), false);
      toast(hoursChanged ? `Đã lưu ${res.data.name}. Giờ mới áp dụng từ ${formatDayMonthYear(tomorrow)}.` : `Đã lưu ${res.data.name}.`);
      onSaved(res.data.code);
      return true;
    } finally {
      setBusy(false);
    }
  }

  return { f, setF, touched, setTouched, submitted, banner, busy, err, tomorrow, dirty, submit };
}

export type CourtFormState = ReturnType<typeof useCourtForm>;
