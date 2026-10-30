"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import type { MemberDetail } from "@/lib/api/server";

type DetailState = { status: "loading" } | { status: "error" } | { status: "ok"; detail: MemberDetail };

/** Tải chi tiết một hồ sơ khi mở drawer / form (mỗi lần gọi backend ghi nhật ký xem ⇒ không tải trước). */
export function useMemberDetail(ref: string | null, initial?: MemberDetail): DetailState {
  const [state, setState] = useState<{ ref: string; value: DetailState } | null>(null);

  useEffect(() => {
    if (!ref || initial) return;
    let isCancelled = false;
    api
      .GET("/api/v1/members/{ref}", { params: { path: { ref } } })
      .then(({ data }) => (data ? ({ status: "ok", detail: data } as const) : ({ status: "error" } as const)))
      .catch(() => ({ status: "error" }) as const)
      .then((value) => {
        if (!isCancelled) setState({ ref, value });
      });
    return () => {
      isCancelled = true;
    };
  }, [ref, initial]);

  if (initial) return { status: "ok", detail: initial };
  return state && state.ref === ref ? state.value : { status: "loading" };
}
