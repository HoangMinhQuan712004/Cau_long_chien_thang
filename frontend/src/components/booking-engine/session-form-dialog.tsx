"use client";

import { useId, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatLongDate, formatNumber, formatVnd } from "@/lib/format";
import { hourText } from "./block";
import { authFailure, STALE_CODES } from "./booking-dialogs";
import { sendCreateSession } from "./requests";
import type { Selection } from "./types";
import { btnCls, btnPrimaryCls, ErrorBanner, Hint, inputCls } from "./ui";

// Đặt sự kiện (Admin): một hoặc nhiều sân liền nhau, hoặc ngày sau (tách từ booking-dialogs.tsx).

type SessionFormProps = {
  selection: Selection;
  /** Tên sân theo mã để hiển thị. */
  resourceNames: Record<string, string>;
  onClose: () => void;
  onCreated: () => void;
  onStale: () => void;
};

const digits = (v: string) => v.replace(/\D/g, "");

export function SessionFormDialog({ selection, resourceNames, onClose, onCreated, onStale }: SessionFormProps) {
  const ids = { name: useId(), capacity: useId(), price: useId() };
  const [name, setName] = useState("");
  const [capacity, setCapacity] = useState("");
  const [price, setPrice] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [banner, setBanner] = useState("");
  const [busy, setBusy] = useState(false);

  const errName = !name.trim() ? "Vui lòng nhập Tên sự kiện." : name.trim().length > 100 ? "Tên sự kiện tối đa 100 ký tự." : "";
  const cap = Number(capacity);
  const errCap = !capacity ? "Vui lòng nhập Số chỗ tối đa." : cap < 1 || cap > 99 ? "Số chỗ tối đa là số nguyên từ 1 đến 99." : "";
  const errPrice = price === "" ? "Vui lòng nhập Giá vé." : "";

  async function submit() {
    setSubmitted(true);
    setBanner("");
    if (errName || errCap || errPrice) return;
    setBusy(true);
    try {
      const res = await write((key) =>
        sendCreateSession(key, {
          resource_codes: selection.resourceCodes,
          date: selection.date,
          start_hour: selection.startHour,
          end_hour: selection.endHour,
          name: name.trim(),
          capacity: cap,
          ticket_price: Number(price),
        }),
      );
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return;
        if (e.code && STALE_CODES.includes(e.code)) {
          toast(errorText(e), undefined, "error");
          onStale();
          return;
        }
        setBanner(errorText(e));
        return;
      }
      toast(`Đã lưu sự kiện "${name.trim()}" · ${cap} chỗ · ${formatVnd(Number(price))} / người.`);
      onCreated();
    } finally {
      setBusy(false);
    }
  }

  const names = selection.resourceCodes.map((c) => `${c} · ${resourceNames[c] ?? ""}`).join(", ");
  return (
    <Modal
      open
      onClose={onClose}
      title="Đặt sự kiện"
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy} className={btnCls}>
            Hủy
          </button>
          <button type="button" onClick={submit} disabled={busy} className={btnPrimaryCls}>
            {busy ? "Đang lưu…" : "Lưu sự kiện"}
          </button>
        </>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <div>
        <label htmlFor={ids.name} className="mb-1 block text-sm font-medium">
          Tên sự kiện <span className="text-danger">*</span>
        </label>
        <input
          id={ids.name}
          value={name}
          maxLength={100}
          placeholder="Giao lưu tối thứ Ba"
          onChange={(e) => setName(e.target.value)}
          aria-invalid={Boolean(submitted && errName) || undefined}
          className={inputCls}
        />
        {submitted && errName ? <p className="mt-1 text-xs text-danger">{errName}</p> : null}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <ReadOnly label="Ngày" value={formatLongDate(selection.date)} />
        <ReadOnly label="Từ – Đến" value={`${hourText(selection.startHour)} – ${hourText(selection.endHour)}`} />
        <ReadOnly label="Số sân" value={`${selection.resourceCodes.length} sân`} />
      </div>
      <ReadOnly label="Sân" value={names} />
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor={ids.capacity} className="mb-1 block text-sm font-medium">
            Số chỗ tối đa <span className="text-danger">*</span>
          </label>
          <input
            id={ids.capacity}
            value={capacity}
            inputMode="numeric"
            maxLength={3}
            placeholder="1 – 99"
            onChange={(e) => setCapacity(digits(e.target.value))}
            aria-invalid={Boolean(submitted && errCap) || undefined}
            className={inputCls}
          />
          {submitted && errCap ? <p className="mt-1 text-xs text-danger">{errCap}</p> : null}
        </div>
        <div>
          <label htmlFor={ids.price} className="mb-1 block text-sm font-medium">
            Giá vé (đ / người) <span className="text-danger">*</span>
          </label>
          <input
            id={ids.price}
            value={price === "" ? "" : formatNumber(Number(price))}
            inputMode="numeric"
            placeholder="VD: 60.000"
            onChange={(e) => setPrice(digits(e.target.value).slice(0, 9))}
            aria-invalid={Boolean(submitted && errPrice) || undefined}
            className={inputCls}
          />
          {submitted && errPrice ? <p className="mt-1 text-xs text-danger">{errPrice}</p> : null}
        </div>
      </div>
      <Hint>Khung đã chọn được giữ cho sự kiện; khách đăng ký vé tại quầy hoặc trên web.</Hint>
    </Modal>
  );
}

function ReadOnly({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="mb-1 block text-sm font-medium">{label}</span>
      <p className="rounded-md border border-border bg-background px-3 py-2 text-sm text-muted">{value}</p>
    </div>
  );
}
