"use client";

import { useEffect, useState } from "react";
import { errorText } from "@/lib/api/write";
import { getSeriesPreview } from "./requests";
import type { SeriesDate, SeriesParams } from "./types";

// Tự kiểm lịch của gói: tham số đổi ⇒ chờ 400 ms rồi gọi preview; lần mới hủy lần cũ (AbortController) nên kết quả
// không về lệch thứ tự. Trạng thái tải suy từ "khóa" tham số: kết quả đang giữ thuộc khóa cũ ⇒ đang kiểm.
// Ngày người dùng tự bỏ tích chỉ giữ lại nếu còn trong kết quả mới.

const DEBOUNCE_MS = 400;
type Result = { key: string; dates: SeriesDate[] } | { key: string; error: string };

export function useSeriesPreview(params: SeriesParams) {
  const [nonce, setNonce] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const [unpicked, setUnpicked] = useState<ReadonlySet<string>>(() => new Set());
  const need = params.weekdays.length === 0;
  const key = `${JSON.stringify(params)}#${nonce}`;

  useEffect(() => {
    if (need) return;
    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      const res = await getSeriesPreview(params, ctrl.signal);
      if (ctrl.signal.aborted) return;
      if (!res.ok) return setResult({ key, error: errorText(res.error) });
      const dates = res.data.dates;
      setResult({ key, dates });
      setUnpicked((cur) => new Set([...cur].filter((d) => dates.some((x) => x.date === d))));
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [key, need, params]); // `key` đổi theo `params` + lần bấm Thử lại

  const fresh = !need && result?.key === key ? result : null;
  const dates = fresh && "dates" in fresh ? fresh.dates : null;
  const picked = new Set((dates ?? []).filter((d) => d.status === "ok" && !unpicked.has(d.date)).map((d) => d.date));

  return {
    need,
    isLoading: !need && !fresh,
    error: fresh && "error" in fresh ? fresh.error : "",
    dates,
    picked,
    total: (dates ?? []).filter((d) => picked.has(d.date)).reduce((n, d) => n + d.price, 0),
    retry: () => setNonce((n) => n + 1),
    toggle: (date: string) =>
      setUnpicked((cur) => {
        const next = new Set(cur);
        if (!next.delete(date)) next.add(date);
        return next;
      }),
    /** 409 lúc đặt: đánh dấu đỏ các ngày vừa bị người khác đặt (không gọi lại preview). */
    markConflicts: (hit: { date: string; reason?: string | null }[]) => {
      const reasons = new Map(hit.map((c) => [c.date, c.reason]));
      setResult((r) =>
        r && "dates" in r
          ? { ...r, dates: r.dates.map((d) => (reasons.has(d.date) ? { ...d, status: "conflict", reason: reasons.get(d.date) ?? d.reason } : d)) }
          : r,
      );
    },
  };
}
