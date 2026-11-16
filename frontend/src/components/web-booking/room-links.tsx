"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import type { CheckoutItem } from "./types";

// Sau khi đặt thành công trong khu hội viên (T-018 AC5): phòng chơi do hệ thống tạo sau khi có sự kiện booking,
// nên hỏi `rooms/by-booking/{mã khối}` mỗi 2 giây, tối đa 10 lần; quá thì hiện link sang Danh sách sân.

const TRIES = 10;
const EVERY_MS = 2000;

type State = { roomId: number } | "waiting" | "gave-up";

function useRoom(code: string): State {
  const [state, setState] = useState<State>("waiting");
  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let n = 0;
    const run = async () => {
      n += 1;
      try {
        const { data, response } = await api.GET("/api/v1/member-area/rooms/by-booking/{code}", { params: { path: { code } } });
        if (stop) return;
        if (response.ok && data) return setState({ roomId: data.room_id });
        // 404: phòng chưa tạo (hoặc không phải của mình) ⇒ thử lại; lỗi khác cũng thử lại cho tới hết lượt
      } catch {
        /* mất mạng: thử lại */
      }
      if (stop) return;
      if (n >= TRIES) return setState("gave-up");
      timer = setTimeout(run, EVERY_MS);
    };
    void run();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [code]);
  return state;
}

const btn = "inline-flex min-h-11 items-center justify-center rounded-lg px-4 py-2.5 text-center text-sm font-semibold focus-ring";

function RoomButton({ item, many }: { item: CheckoutItem; many: boolean }) {
  const state = useRoom(item.code);
  const label = many ? `Vào phòng ${item.resource_name}` : "Vào phòng";
  if (state === "waiting") {
    return (
      <span role="status" className={`${btn} border border-border text-muted`}>
        <span aria-hidden className="mr-2 size-4 animate-spin rounded-full border-2 border-border border-t-primary" />
        Đang tạo phòng{many ? ` ${item.resource_name}` : ""}…
      </span>
    );
  }
  if (state === "gave-up") return null;
  return (
    <Link href={`/hoi-vien/phong/${state.roomId}`} className={`${btn} bg-cta font-bold tracking-wide text-cta-fg uppercase hover:bg-cta-hover`}>
      {label}
    </Link>
  );
}

/** Nút "Vào phòng" cho từng khối của đơn (mỗi khối một phòng). Quá thời gian chờ thì chỉ còn link Danh sách sân. */
export function RoomLinks({ items }: { items: CheckoutItem[] }) {
  const many = items.length > 1;
  return (
    <div className="mt-4 space-y-3">
      <div className="flex flex-wrap gap-3">
        {items.map((it) => (
          <RoomButton key={it.code} item={it} many={many} />
        ))}
      </div>
      <p className="text-sm text-muted">
        Phòng chơi của bạn nằm ở{" "}
        <Link href="/hoi-vien/danh-sach-san" className="font-semibold text-primary underline">
          Danh sách sân
        </Link>{" "}
        (Sân của tôi). Nếu chưa thấy phòng, vui lòng đợi ít phút rồi tải lại.
      </p>
    </div>
  );
}
