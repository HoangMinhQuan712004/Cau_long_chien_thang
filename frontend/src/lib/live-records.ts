"use client";

import { useEffect, useRef } from "react";
import type { components } from "@/lib/api/schema";

// Tin trực tiếp từ máy đo tốc độ (websocket /api/v1/member-area/records/live, chỉ hội viên đã đăng nhập):
// "record.new" khi một cú đập vừa được ghi, "record.video" khi video cắt ghép của nó đã có. Tên đã ẩn danh theo người xem như Bảng xếp hạng.

export type LiveRecord = {
  record_id: number;
  speed_kmh: number;
  measured_at: string;
  display_name: string;
  avatar_url: string | null;
  resource_name: string | null;
  is_me: boolean;
  video: components["schemas"]["VideoOut"] | null;
};
export type LiveEvent = { event: "record.new" | "record.video"; record: LiveRecord };

const PATH = "/api/v1/member-area/records/live";
const UNAUTHORIZED = 4401; // phiên hết hạn / chưa đăng nhập: làm mới phiên rồi nối lại
const FORBIDDEN_ORIGIN = 4403;

/** Nghe tin trực tiếp khi màn đang mở; tự nối lại (chờ tăng dần tới 30 s), làm mới access token khi server đóng vì hết phiên. */
export function useLiveRecords(onEvent: (e: LiveEvent) => void) {
  const handler = useRef(onEvent);
  useEffect(() => {
    handler.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    let delay = 1000;
    let refreshes = 0;

    const later = () => {
      if (stopped) return;
      timer = setTimeout(open, delay);
      delay = Math.min(delay * 2, 30_000);
    };

    function open() {
      if (stopped) return;
      ws = new WebSocket(`${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}${PATH}`);
      ws.onopen = () => {
        delay = 1000;
        refreshes = 0;
      };
      ws.onmessage = (m) => {
        let msg: unknown;
        try {
          msg = JSON.parse(String(m.data));
        } catch {
          return;
        }
        const e = msg as Partial<LiveEvent>;
        if ((e.event === "record.new" || e.event === "record.video") && e.record) handler.current(e as LiveEvent);
      };
      ws.onclose = (e) => {
        ws = null;
        if (stopped || e.code === FORBIDDEN_ORIGIN) return;
        if (e.code === UNAUTHORIZED) {
          if (refreshes++ >= 2) return; // làm mới không được: thôi nghe, màn vẫn dùng bình thường
          void fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include" })
            .then((r) => (r.ok ? open() : undefined))
            .catch(later);
          return;
        }
        later();
      };
    }

    open();
    return () => {
      stopped = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, []);
}
