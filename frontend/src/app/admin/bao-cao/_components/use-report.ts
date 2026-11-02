"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { api, errorDetail } from "@/lib/api/client";
import { FORBIDDEN_REPORT_PARAM } from "../../_components/forbidden";
import type { RangeError } from "./report-period";
import type { ReportOverview } from "@/lib/api/server";

/** Lỗi đang hiện: E-002/E-003 (+ ngày tương lai) dưới bộ lọc; "load" = E-004 đầu trang. */
export type ReportError = RangeError | "future" | "load";

const RANGE_CODE: Record<string, ReportError> = {
  "E-REPORT-1": "fromAfterTo",
  "E-REPORT-2": "tooLong",
  "E-REPORT-3": "future",
};

type State = { data: ReportOverview | null; isLoading: boolean; error: ReportError | null };

/**
 * Số liệu báo cáo: lần đầu do server tải sẵn (kỳ Tuần); đổi kỳ / Làm mới gọi lại API.
 * Lỗi ⇒ giữ số cũ kèm giờ cập nhật cũ; đổi kỳ khi lần trước chưa xong ⇒ hủy lần trước, chỉ nhận kết quả sau cùng.
 */
export function useReport(initial: ReportOverview | null) {
  const router = useRouter();
  const [state, setState] = useState<State>({ data: initial, isLoading: false, error: initial ? null : "load" });
  const current = useRef<AbortController | null>(null);

  const load = async (from: string, to: string) => {
    current.current?.abort();
    const ctrl = new AbortController();
    current.current = ctrl;
    setState((s) => ({ ...s, isLoading: true, error: null }));

    let next: Partial<State>;
    try {
      const { data, error, response } = await api.GET("/api/v1/admin/reports/overview", {
        params: { query: { from, to } },
        signal: ctrl.signal,
      });
      if (response.status === 403) {
        // Quyền bị đổi khi đang mở màn (BR-001): về Đặt sân + báo E-001
        router.replace(`/admin/dat-san?${FORBIDDEN_REPORT_PARAM}`);
        return;
      }
      next = data ? { data } : { error: RANGE_CODE[errorDetail(error).code ?? ""] ?? "load" };
    } catch {
      // Bị hủy vì đã chọn kỳ khác ⇒ bỏ qua; lỗi mạng ⇒ E-004 (lớp phủ Mất kết nối do khung chung lo)
      if (ctrl.signal.aborted) return;
      next = { error: "load" };
    }
    if (current.current !== ctrl) return;
    setState((s) => ({ ...s, ...next, isLoading: false }));
  };

  /** Báo lỗi khoảng ngày kiểm ở trình duyệt (không gọi API, giữ kỳ và số đang hiện). */
  const setRangeError = (error: RangeError | null) => setState((s) => ({ ...s, error }));

  return { ...state, load, setRangeError };
}
