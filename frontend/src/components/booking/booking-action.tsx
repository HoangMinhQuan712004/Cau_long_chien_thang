"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, errorMessage } from "@/lib/api/client";

type Action = "cancel" | "confirm" | "pay-cash";

const LABEL: Record<Action, string> = {
  cancel: "Hủy",
  confirm: "Xác nhận",
  "pay-cash": "Thu tiền mặt",
};

const CONFIRM_TEXT: Partial<Record<Action, string>> = {
  cancel: "Bạn chắc chắn muốn hủy đơn này?",
};

async function run(action: Action, id: number) {
  const path = { params: { path: { booking_id: id } } };
  switch (action) {
    case "cancel":
      return api.POST("/api/v1/bookings/{booking_id}/cancel", path);
    case "confirm":
      return api.POST("/api/v1/admin/bookings/{booking_id}/confirm", path);
    case "pay-cash":
      return api.POST("/api/v1/admin/bookings/{booking_id}/payments", {
        ...path,
        body: { method: "cash" },
      });
  }
}

/** Nút thao tác trên một đơn; xong thì refresh Server Component để lấy dữ liệu mới. */
export function BookingAction({ id, action }: { id: number; action: Action }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  async function onClick() {
    const question = CONFIRM_TEXT[action];
    if (question && !window.confirm(question)) return;
    setPending(true);
    try {
      const { error } = await run(action, id);
      if (error) window.alert(errorMessage(error));
      else router.refresh();
    } catch {
      window.alert("Không kết nối được máy chủ, vui lòng thử lại");
    } finally {
      setPending(false);
    }
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={pending}
      className={`rounded border px-2 py-1 text-xs disabled:opacity-50 ${
        action === "cancel"
          ? "border-danger/40 text-danger"
          : "border-primary/40 text-primary"
      }`}
    >
      {pending ? "…" : LABEL[action]}
    </button>
  );
}
