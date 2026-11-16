"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import { callMemberApi } from "@/lib/api/members";
import type { Racket } from "@/lib/api/server";

export type { Racket };

type State = { status: "loading" } | { status: "error" } | { status: "ok"; items: Racket[] };
export type RacketResult = { ok: true; racket: Racket } | { ok: false; error: unknown; response?: Response };

/** Danh mục vợt: `all` ⇒ cả vợt đã ẩn (Admin, drawer quản lý); không ⇒ chỉ vợt đang dùng (ô chọn trong form). `enabled` = false ⇒ không tải. */
export function useRackets(all: boolean, enabled = true) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let isCancelled = false;
    callMemberApi(() => api.GET("/api/v1/rackets", { params: { query: all ? { all: true } : {} } })).then(({ data }) => {
      if (!isCancelled) setState(Array.isArray(data) ? { status: "ok", items: data } : { status: "error" });
    });
    return () => {
      isCancelled = true;
    };
  }, [all, enabled, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  // Ghi xong ⇒ cập nhật ngay dòng trong danh sách (không chờ tải lại)
  const write = useCallback(async (request: () => Promise<{ data?: Racket; error?: unknown; response: Response }>): Promise<RacketResult> => {
    const { data, error, response } = await callMemberApi(request);
    if (!data) return { ok: false, error, response };
    setState((s) => {
      if (s.status !== "ok") return s;
      const exists = s.items.some((r) => r.id === data.id);
      return { status: "ok", items: exists ? s.items.map((r) => (r.id === data.id ? data : r)) : [data, ...s.items] };
    });
    return { ok: true, racket: data };
  }, []);

  // `sort_order: 0` = mặc định của BE (schema sinh ra thành bắt buộc)
  const add = useCallback((name: string) => write(() => api.POST("/api/v1/rackets", { body: { name, sort_order: 0 } })), [write]);
  const update = useCallback(
    (id: number, body: { name?: string; is_active?: boolean }) =>
      write(() => api.PATCH("/api/v1/rackets/{racket_id}", { params: { path: { racket_id: id } }, body })),
    [write],
  );

  // Xóa ⇒ bỏ dòng khỏi danh sách; trả mã HTTP khi lỗi (404 = đã bị xóa ở nơi khác)
  const remove = useCallback(async (id: number): Promise<{ ok: true } | { ok: false; status?: number; error: unknown; response?: Response }> => {
    const { error, response } = await callMemberApi(() => api.DELETE("/api/v1/rackets/{racket_id}", { params: { path: { racket_id: id } } }));
    if (!response?.ok) return { ok: false, status: response?.status, error, response };
    setState((s) => (s.status === "ok" ? { status: "ok", items: s.items.filter((r) => r.id !== id) } : s));
    return { ok: true };
  }, []);

  return { state, reload, add, update, remove };
}
