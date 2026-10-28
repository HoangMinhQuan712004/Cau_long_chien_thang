"use client";

import { useEffect, useId, useRef, useState } from "react";
import { errorText } from "@/lib/api/write";
import { formatDateTime, formatLongDate, formatVnd } from "@/lib/format";
import { isValidPhone, normalizePhone } from "@/lib/phone";
import { BankBox, mmss, useCountdown } from "./pay-parts";
import { lookupBooking } from "./requests";
import type { Lookup, LookupStatus } from "./types";

// /tra-cuu: Mã booking + SĐT → thẻ kết quả. Sai mã hay sai SĐT cùng một thông báo (T-008 AC25–AC27).

const hhmm = (t: string) => t.slice(0, 5);

const BADGE: Record<LookupStatus, { label: string; cls: string }> = {
  paid: { label: "Đã thanh toán", cls: "bg-free text-success" },
  unpaid: { label: "Chưa thanh toán", cls: "bg-blk-unpaid text-blk-unpaid-fg" },
  uncollectible: { label: "Không thu được", cls: "bg-blk-bad text-blk-bad-fg" },
  pending: { label: "Đang chờ thanh toán", cls: "bg-blk-unpaid text-blk-unpaid-fg" },
  expired: { label: "Giữ chỗ hết hạn", cls: "bg-blk-bad text-blk-bad-fg" },
};

export function LookupScreen({ hotline }: { hotline: string }) {
  const ids = { code: useId(), phone: useId() };
  const [code, setCode] = useState("");
  const [phone, setPhone] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Lookup | null>(null);
  const query = useRef<{ code: string; phone: string } | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  const errCode = !code.trim() ? "Vui lòng nhập mã booking." : "";
  const normalized = normalizePhone(phone);
  const errPhone = !isValidPhone(normalized) ? "Số điện thoại không hợp lệ — cần đủ 10 số." : "";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    setError("");
    if (errCode || errPhone) return;
    setBusy(true);
    setResult(null);
    const q = { code: code.trim(), phone: normalized };
    const res = await lookupBooking(q.code, q.phone);
    setBusy(false);
    if (res.ok) {
      query.current = q;
      setResult(res.data);
      // Điện thoại: kết quả nằm dưới form, đưa vào tầm nhìn.
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    } else {
      query.current = null;
      setError(res.error.code === "E-WEB-7" || res.error.status === 404 ? "Không tìm thấy booking. Kiểm tra lại mã và số điện thoại." : errorText(res.error));
    }
  }

  // Booking đang chờ thanh toán: hỏi lại trạng thái mỗi 3 giây (tab ẩn: thưa hơn) tới khi có kết quả cuối.
  const pending = result?.status === "pending";
  useEffect(() => {
    if (!pending) return;
    let stop = false;
    let ticks = 0;
    const id = setInterval(async () => {
      ticks += 1;
      if (document.visibilityState !== "visible" && ticks % 4 !== 0) return;
      const q = query.current;
      if (!q) return;
      const res = await lookupBooking(q.code, q.phone);
      if (!stop && res.ok) setResult(res.data);
    }, 3000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [pending]);

  const field = "w-full rounded-lg border bg-surface px-3 py-2.5 text-sm";
  return (
    <div className="mx-auto w-full max-w-xl space-y-5">
      <form onSubmit={submit} noValidate className="rounded-2xl border border-border bg-surface p-5 sm:p-6">
        <h1 className="text-2xl font-bold">Tra cứu booking</h1>
        <p className="mt-1 text-sm text-muted">Nhập mã booking và số điện thoại đã dùng khi đặt sân.</p>
        <div className="mt-4 space-y-4">
          <div>
            <label htmlFor={ids.code} className="mb-1 block text-sm font-medium">
              Mã booking <span className="text-danger">*</span>
            </label>
            <input
              id={ids.code}
              value={code}
              maxLength={40}
              autoComplete="off"
              autoCapitalize="characters"
              placeholder="BK-20261020-023"
              onChange={(e) => {
                setCode(e.target.value);
                setError("");
              }}
              aria-invalid={Boolean(submitted && errCode) || undefined}
              className={`${field} ${submitted && errCode ? "border-danger" : "border-border"}`}
            />
            {submitted && errCode ? <p className="mt-1 text-xs text-danger">{errCode}</p> : null}
          </div>
          <div>
            <label htmlFor={ids.phone} className="mb-1 block text-sm font-medium">
              Số điện thoại <span className="text-danger">*</span>
            </label>
            <input
              id={ids.phone}
              value={phone}
              inputMode="tel"
              autoComplete="tel"
              maxLength={16}
              onChange={(e) => {
                setPhone(e.target.value);
                setError("");
              }}
              aria-invalid={Boolean(submitted && errPhone) || undefined}
              className={`${field} ${submitted && errPhone ? "border-danger" : "border-border"}`}
            />
            {submitted && errPhone ? <p className="mt-1 text-xs text-danger">{errPhone}</p> : null}
          </div>
        </div>
        {error ? (
          <p role="alert" className="mt-4 rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
            {error}
          </p>
        ) : null}
        <button type="submit" disabled={busy} className="mt-5 w-full rounded-lg bg-primary px-4 py-3 text-sm font-semibold text-primary-fg disabled:opacity-60">
          {busy ? "Đang tra cứu…" : "Tra cứu"}
        </button>
      </form>

      <div ref={resultRef} className="scroll-mt-20">
        {result ? <ResultCard result={result} hotline={hotline} /> : null}
      </div>
    </div>
  );
}

function ResultCard({ result: r, hotline }: { result: Lookup; hotline: string }) {
  const left = useCountdown(r.pending?.expires_at ?? null, r.pending?.server_now ?? null);
  const badge = BADGE[r.status];
  // Giữ chỗ về 0 nhưng server chưa báo hết hạn (ân hạn nhận tiền): hiện nhãn hết giờ, vẫn hỏi tiếp.
  const timedOut = r.status === "pending" && left === 0;
  const money =
    r.status === "paid"
      ? `${formatVnd(r.amount)} · ${r.payment_method_label ?? "Chuyển khoản"}`
      : r.status === "uncollectible"
        ? formatVnd(r.amount)
        : `${formatVnd(r.amount)} · Chưa thanh toán`;

  return (
    <section className="rounded-2xl border border-border bg-surface p-5 sm:p-6" aria-label={`Kết quả ${r.code}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold text-primary">{r.code}</h2>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${timedOut ? BADGE.expired.cls : badge.cls}`}>{timedOut ? "Hết thời gian giữ chỗ" : badge.label}</span>
      </div>

      {r.status === "pending" && r.pending ? (
        <div className="mt-4 space-y-3">
          {r.pending.bank ? <BankBox bank={r.pending.bank} amount={r.pending.amount} payRef={r.pending.pay_ref} dim={timedOut} /> : null}
          <p role="status" className="flex items-center gap-2 rounded-lg border border-border bg-free px-4 py-3 text-sm">
            <span aria-hidden className="size-4 animate-spin rounded-full border-2 border-border border-t-primary" />
            {timedOut
              ? "Đã hết thời gian giữ chỗ, đang chờ hệ thống xác nhận lần cuối…"
              : `Đang chờ xác nhận thanh toán… Giữ chỗ còn ${left == null ? "--:--" : mmss(left)}.`}
          </p>
        </div>
      ) : null}

      <dl className="mt-4 space-y-2.5 text-sm">
        <Row label="Sân" value={r.resource_name} />
        <Row label="Ngày" value={formatLongDate(r.play_date)} />
        <Row label="Khung giờ" value={`${hhmm(r.start_time)} – ${hhmm(r.end_time)} (${r.hours} giờ)`} />
        <Row label="Người đặt" value={`${r.customer_name} · ${r.phone_masked}`} />
        <Row label="Số tiền" value={money} />
        {r.status === "paid" && r.paid_at ? <Row label="Thời gian TT" value={formatDateTime(r.paid_at)} /> : null}
      </dl>

      <p className="mt-4 border-t border-border pt-3 text-sm text-muted">
        {r.status === "expired"
          ? `Booking chưa thanh toán trong thời gian giữ chỗ nên đã hết hạn. Nếu bạn đã chuyển khoản, vui lòng gọi hotline ${hotline} kèm mã booking.`
          : `Cần đổi giờ / hủy sân? Vui lòng gọi hotline ${hotline}.`}
      </p>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[7rem_1fr] gap-3">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words font-medium">{value}</dd>
    </div>
  );
}
