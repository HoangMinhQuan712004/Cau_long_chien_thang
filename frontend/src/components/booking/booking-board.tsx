"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { Dictionary } from "@/i18n/dictionaries";
import { api, errorDetail, errorMessage } from "@/lib/api/client";
import { formatTime, todayVn } from "@/lib/format";
import { BookingSummary } from "./booking-summary";
import { PhoneVerify } from "./phone-verify";
import { SlotGrid } from "./slot-grid";
import { type Availability, useSlotSelection } from "./use-slot-selection";

type Message = { type: "error" | "ok"; text: string };

const addDays = (date: string, days: number) => {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};

type BookingBoardProps = {
  maxAdvanceDays: number;
  t: Dictionary["booking"];
  phoneVerifyTexts: Dictionary["phoneVerify"];
};

// Trang đặt sân: chọn ngày ⇒ chọn ô giờ ⇒ báo giá ⇒ đặt (thiếu SĐT thì xác minh trước)
export function BookingBoard({ maxAdvanceDays, t, phoneVerifyTexts }: BookingBoardProps) {
  const router = useRouter();
  const today = todayVn();
  const [date, setDate] = useState(today);
  const [reloadKey, setReloadKey] = useState(0);
  const [board, setBoard] = useState<{ data: Availability; loadedAt: number } | null>(null);
  const [quote, setQuote] = useState<{ key: string; total: number } | null>(null);
  const [message, setMessage] = useState<Message | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // 409 phone_required ⇒ xác minh SĐT, giữ nguyên khung giờ đang chọn
  const [needsPhone, setNeedsPhone] = useState(false);
  const [isPasswordCleared, setIsPasswordCleared] = useState(false);
  const { rows, slots, selected, isBusy, toggle, clear } = useSlotSelection(date, board);
  const data = board?.data ?? null;
  const slotsKey = JSON.stringify(slots);
  const total = quote?.key === slotsKey ? quote.total : null;

  // Tải lịch trống; bỏ response cũ khi đổi ngày liên tục
  useEffect(() => {
    let cancelled = false;
    api
      .GET("/api/v1/bookings/availability", { params: { query: { date } } })
      .then(({ data, error }) => {
        if (cancelled) return;
        if (data) setBoard({ data, loadedAt: Date.now() });
        else setMessage({ type: "error", text: errorMessage(error) });
      })
      .catch(() => !cancelled && setMessage({ type: "error", text: t.network }));
    return () => {
      cancelled = true;
    };
  }, [date, reloadKey, t.network]);

  // Báo giá mỗi khi đổi lựa chọn
  useEffect(() => {
    if (!slots.length) return;
    let cancelled = false;
    api
      .POST("/api/v1/bookings/quote", { body: slots })
      .then(({ data, error }) => {
        if (cancelled) return;
        if (data) setQuote({ key: slotsKey, total: data.total_amount });
        setMessage(error ? { type: "error", text: errorMessage(error) } : null);
      })
      .catch(() => !cancelled && setMessage({ type: "error", text: t.network }));
    return () => {
      cancelled = true;
    };
  }, [slots, slotsKey, t.network]);

  const changeDate = (day: string) => {
    if (!day) return;
    setDate(day);
    setBoard(null);
    clear();
    setMessage(null);
  };

  const submit = async (prefix = "") => {
    setIsSubmitting(true);
    try {
      const { data: booking, error, response } = await api.POST("/api/v1/bookings", { body: { slots } });
      if (response.status === 401) {
        router.push(`/dang-nhap?next=${encodeURIComponent("/dat-san")}`);
        return;
      }
      if (response.status === 409 && errorDetail(error).code === "phone_required") {
        setMessage(null);
        setNeedsPhone(true);
        return;
      }
      if (error || !booking) {
        setMessage({ type: "error", text: errorMessage(error) });
      } else {
        clear();
        const time = booking.expires_at ? formatTime(booking.expires_at) : t.beforePlay;
        setMessage({ type: "ok", text: prefix + t.booked.replace("{code}", booking.code).replace("{time}", time) });
      }
      setReloadKey((k) => k + 1);
    } catch {
      setMessage({ type: "error", text: t.network });
    } finally {
      setIsSubmitting(false);
    }
  };

  const [beforeLink, afterLink] = phoneVerifyTexts.passwordCleared.split("{link}");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="booking-date" className="font-medium">
          {t.dateLabel}
        </label>
        <input
          id="booking-date"
          type="date"
          value={date}
          min={today}
          max={addDays(today, maxAdvanceDays)}
          onChange={(e) => changeDate(e.target.value)}
          className="rounded-md border border-border bg-surface px-3 py-2"
        />
        <span className="text-sm text-muted">{t.hint}</span>
      </div>

      {data ? (
        <SlotGrid data={data} rows={rows} selected={selected} isBusy={isBusy} onToggle={toggle} t={t} />
      ) : message?.type === "error" ? (
        <button
          type="button"
          onClick={() => {
            setMessage(null);
            setReloadKey((k) => k + 1);
          }}
          className="rounded-md border border-border px-4 py-2"
        >
          {t.reload}
        </button>
      ) : (
        <p className="text-muted">{t.loading}</p>
      )}

      {needsPhone && (
        <PhoneVerify
          t={phoneVerifyTexts}
          onVerified={(merged, passwordCleared) => {
            setNeedsPhone(false);
            setIsPasswordCleared(merged && !!passwordCleared);
            // Gộp tài khoản ⇒ cookie đổi, tải lại header
            if (merged) router.refresh();
            submit(merged ? `${phoneVerifyTexts.merged} ` : "");
          }}
        />
      )}

      {message && (
        <p role="status" className={message.type === "error" ? "text-danger" : "text-primary"}>
          {message.text}
        </p>
      )}
      {isPasswordCleared && (
        <p role="status" className="text-muted">
          {beforeLink}
          <Link href="/quen-mat-khau" className="font-semibold text-primary hover:underline">
            {phoneVerifyTexts.forgotPassword}
          </Link>
          {afterLink}
        </p>
      )}

      <BookingSummary
        slots={slots}
        courtName={(id) => data?.courts.find((c) => c.court_id === id)?.name}
        total={total}
        isSubmitting={isSubmitting}
        disabled={!slots.length || total === null || isSubmitting || needsPhone}
        onSubmit={() => submit()}
        t={t}
      />
    </div>
  );
}
