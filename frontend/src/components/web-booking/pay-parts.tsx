"use client";

import { useEffect, useRef, useState } from "react";
import { formatVnd } from "@/lib/format";
import type { Bank } from "./types";

// Mảnh dùng chung cho màn thanh toán và kết quả tra cứu: đếm ngược theo giờ server, nút Sao chép, khối QR + thông tin chuyển khoản.

/** Số giây còn lại tới `expiresAt`, tính theo đồng hồ server (bù lệch giờ máy khách); null khi chưa có dữ liệu. */
export function useCountdown(expiresAt: string | null, serverNow: string | null): number | null {
  const [left, setLeft] = useState<number | null>(null);
  const offset = useRef(0);
  useEffect(() => {
    if (!expiresAt || !serverNow) return;
    offset.current = Date.parse(serverNow) - Date.now();
    const exp = Date.parse(expiresAt);
    const tick = () => setLeft(Math.max(0, Math.ceil((exp - (Date.now() + offset.current)) / 1000)));
    const first = setTimeout(tick, 0);
    const id = setInterval(tick, 1000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [expiresAt, serverNow]);
  return expiresAt && serverNow ? left : null;
}

export const mmss = (sec: number) => `${String(Math.floor(sec / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;

export function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } finally {
        ta.remove();
      }
    }
    setDone(true);
    setTimeout(() => setDone(false), 1500);
  }
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={`Sao chép ${label}`}
      className="min-h-8 shrink-0 rounded-md border border-border bg-surface px-2.5 py-1 text-xs font-medium hover:bg-primary-softer"
    >
      {done ? "Đã chép" : "Sao chép"}
    </button>
  );
}

/** Khối QR + Ngân hàng / Số tài khoản / Chủ tài khoản / Số tiền / Nội dung CK. `dim` = hết giữ chỗ (QR mờ). */
/** `onQrReady`: ảnh QR đã hiện (hoặc lỗi tải) – màn thanh toán chỉ bắt đầu hiện đồng hồ từ lúc này. */
export function BankBox({ bank, amount, payRef, dim = false, onQrReady }: { bank: Bank; amount: number; payRef: string; dim?: boolean; onQrReady?: () => void }) {
  return (
    <div className="flex flex-col gap-5 sm:flex-row">
      <div className={`mx-auto shrink-0 rounded-xl border border-border bg-white p-3 sm:mx-0 ${dim ? "opacity-30" : ""}`}>
        {/* QR do SePay vẽ; referrerPolicy chặn lộ đường dẫn trang (chứa token) sang tên miền ngoài. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          ref={(el) => {
            if (el?.complete) onQrReady?.(); // ảnh đã có sẵn trong bộ nhớ đệm ⇒ không có sự kiện load
          }}
          onLoad={onQrReady}
          onError={onQrReady}
          src={bank.qr_url}
          alt={`Mã QR chuyển khoản ${formatVnd(amount)} nội dung ${payRef}`} width={192} height={192} referrerPolicy="no-referrer" className="size-48" />
      </div>
      <dl className="min-w-0 flex-1 space-y-2.5 text-sm">
        <Row label="Ngân hàng" value={bank.bank_name} />
        <Row label="Số tài khoản" value={bank.account_number} copy={bank.account_number} bold />
        <Row label="Chủ tài khoản" value={bank.account_name} />
        <Row label="Số tiền" value={formatVnd(amount)} copy={String(amount)} bold large />
        <Row label="Nội dung CK" value={payRef} copy={payRef} bold large />
      </dl>
    </div>
  );
}

function Row({ label, value, copy, bold, large }: { label: string; value: string; copy?: string; bold?: boolean; large?: boolean }) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[7rem_1fr] sm:items-center sm:gap-2">
      <dt className="text-muted">{label}</dt>
      <dd className="flex min-w-0 items-center gap-2">
        <span className={`min-w-0 break-all ${bold ? "font-semibold" : ""} ${large ? "text-base" : ""}`}>{value}</span>
        {copy ? <CopyButton text={copy} label={label.toLowerCase()} /> : null}
      </dd>
    </div>
  );
}
