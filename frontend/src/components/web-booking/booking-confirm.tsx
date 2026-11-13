"use client";

import type { Dispatch, ReactNode, SetStateAction } from "react";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { formatLongDate, formatVnd } from "@/lib/format";
import { phoneHref } from "@/lib/site";
import type { BookingVenue } from "./booking-flow";
import { TierRangeBlock } from "./booking-parts";
import type { Group } from "./booking-summary";
import { MemberHint } from "./member-hint";
import { BookingPhoneOtp, type VerifiedAccount } from "./phone-otp";

// /dat-san bước 2 – "Xác nhận đặt sân": thông tin sân, lịch đặt, khoảng hạng (hội viên), khách hàng + OTP, lưu ý.
// Chỉ hiển thị; state + gửi đơn ở booking-flow.

type Field = "name" | "phone" | "note";
export type ConfirmForm = { name: string; phone: string; note: string };
export type OtpStep = { phone: string; resendAt: number | null; testOtp: string | null };

type Props = {
  venue: BookingVenue;
  date: string;
  groups: Group[];
  totalHours: number;
  total: number;
  holdMinutes: number;
  member: boolean;
  isGuest: boolean;
  tiers: { min: string; max: string };
  setTiers: (v: { min: string; max: string }) => void;
  form: ConfirmForm;
  setForm: Dispatch<SetStateAction<ConfirmForm>>;
  onTouch: (k: Field) => void;
  /** Lỗi đang hiện của ô (đã bấm gửi / đã rời ô), "" khi không lỗi */
  errorOf: (k: Field) => string | false;
  ids: Record<Field, string>;
  otp: OtpStep | null;
  texts: Dictionary["phoneVerify"];
  /** SĐT hợp lệ và đã xác minh (hội viên / tài khoản đã xác minh / vừa nhập OTP) */
  phoneVerified: boolean;
  /** Bỏ được OTP ⇒ nút chính là "Xác nhận & thanh toán" (không thì "Gửi mã xác minh") */
  readyToPay: boolean;
  busy: boolean;
  onlineOff: boolean;
  banner: string;
  onBack: () => void;
  onSubmit: () => void;
  onChangePhone: () => void;
  onVerified: (token: string, expiresAt: string, accountVerified: boolean, account: VerifiedAccount) => void;
  /** Hộp chặn đơn mới (đơn cũ chưa thanh toán) */
  dialog: ReactNode;
};

const FIELD = "w-full rounded-lg border bg-surface px-3 py-2.5 text-sm";

export function BookingConfirm(p: Props) {
  const err = (k: Field) => p.errorOf(k);
  const locked = p.otp !== null || p.member;
  return (
    <div className="mx-auto w-full max-w-xl space-y-5">
      {/* Khu hội viên trên điện thoại: lùi về chọn giờ bằng nút quay lại trên app bar (người dùng 13/11) ⇒ ẩn nút này */}
      <button type="button" onClick={p.onBack} className={cn("text-sm text-muted hover:text-foreground", p.member && "max-lg:hidden")}>
        ← Quay lại chọn giờ
      </button>
      <div>
        <h2 className="text-2xl font-bold">Xác nhận đặt sân</h2>
        <p className="text-sm text-muted">Kiểm tra lại thông tin rồi thanh toán để giữ chỗ.</p>
      </div>

      <section className="rounded-xl bg-surface p-4 shadow-card sm:p-5" aria-labelledby="venue-title">
        <h3 id="venue-title" className="text-sm font-bold text-primary">
          Thông tin sân
        </h3>
        <p className="mt-2 font-semibold">{p.venue.name}</p>
        <p className="text-sm text-muted">{p.venue.address}</p>
        <a href={phoneHref(p.venue.phone)} className="mt-1 inline-flex min-h-11 items-center text-sm font-semibold text-primary hover:underline focus-ring">
          {p.venue.phone}
        </a>
      </section>

      <section className="rounded-xl bg-surface p-4 shadow-card sm:p-5" aria-labelledby="sum-title">
        <h3 id="sum-title" className="text-sm font-bold text-primary">
          Thông tin lịch đặt
        </h3>
        <dl className="mt-3 space-y-3 text-sm">
          {p.groups.map((g) => (
            <div key={g.code} className="grid grid-cols-[6.5rem_1fr] gap-x-3 gap-y-1">
              <dt className="text-muted">Sân</dt>
              <dd className="font-medium">{g.name}</dd>
              <dt className="text-muted">Khung giờ</dt>
              <dd className="font-medium">
                {g.ranges} ({g.hours.length} giờ)
              </dd>
              {p.groups.length > 1 ? (
                <>
                  <dt className="text-muted">Tiền sân</dt>
                  <dd className="font-medium tabular-nums">{formatVnd(g.amount)}</dd>
                </>
              ) : null}
            </div>
          ))}
          <div className="grid grid-cols-[6.5rem_1fr] gap-x-3 border-t border-border pt-3">
            <dt className="text-muted">Ngày</dt>
            <dd className="font-medium">{formatLongDate(p.date)}</dd>
            <dt className="text-muted">Tổng giờ</dt>
            <dd className="font-medium">{p.totalHours} giờ</dd>
          </div>
        </dl>
        <div className="mt-4 flex items-baseline justify-between border-t border-border pt-3">
          <span className="text-sm text-muted">Tổng tiền</span>
          <span className="text-xl font-bold tabular-nums">{formatVnd(p.total)}</span>
        </div>
      </section>

      {p.member ? <TierRangeBlock min={p.tiers.min} max={p.tiers.max} onChange={p.setTiers} /> : null}

      {p.isGuest && !p.member ? <MemberHint next={`/dat-san?ngay=${p.date}`} /> : null}

      <section className="rounded-xl bg-surface p-4 shadow-card sm:p-5">
        <h3 className="text-sm font-bold text-primary">Khách hàng</h3>
        <div className="mt-3 space-y-4">
          <div>
            <label htmlFor={p.ids.name} className="mb-1 block text-sm font-medium">
              Họ tên <span className="text-danger">*</span>
            </label>
            <input
              id={p.ids.name}
              value={p.form.name}
              maxLength={120}
              readOnly={locked}
              autoComplete="name"
              onChange={(e) => p.setForm((f) => ({ ...f, name: e.target.value }))}
              onBlur={() => p.onTouch("name")}
              aria-invalid={Boolean(err("name")) || undefined}
              aria-describedby={err("name") ? `${p.ids.name}-err` : undefined}
              className={`${FIELD} ${err("name") ? "border-danger" : "border-border"}`}
            />
            {err("name") ? (
              <p id={`${p.ids.name}-err`} role="alert" className="mt-1 text-xs text-danger">
                {err("name")}
              </p>
            ) : null}
          </div>
          <div>
            <label htmlFor={p.ids.phone} className="mb-1 block text-sm font-medium">
              Số điện thoại <span className="text-danger">*</span>
            </label>
            <input
              id={p.ids.phone}
              value={p.form.phone}
              inputMode="tel"
              autoComplete="tel"
              maxLength={16}
              readOnly={locked}
              onChange={(e) => p.setForm((f) => ({ ...f, phone: e.target.value }))}
              onBlur={() => p.onTouch("phone")}
              aria-invalid={Boolean(err("phone")) || undefined}
              aria-describedby={`${p.ids.phone}-hint`}
              className={`${FIELD} ${err("phone") ? "border-danger" : "border-border"}`}
            />
            {err("phone") ? (
              <p role="alert" className="mt-1 text-xs text-danger">
                {err("phone")}
              </p>
            ) : null}
            <p id={`${p.ids.phone}-hint`} className="mt-1 text-xs text-muted">
              Dùng số này cùng mã booking để tra cứu.
              {p.phoneVerified ? <b className="ml-1 font-semibold text-primary">Số điện thoại đã xác minh.</b> : null}
            </p>
          </div>
          <div>
            <label htmlFor={p.ids.note} className="mb-1 block text-sm font-medium">
              Ghi chú (không bắt buộc)
            </label>
            <textarea
              id={p.ids.note}
              value={p.form.note}
              placeholder="Ví dụ: cần mượn vợt"
              onChange={(e) => p.setForm((f) => ({ ...f, note: e.target.value }))}
              onBlur={() => p.onTouch("note")}
              aria-invalid={Boolean(err("note")) || undefined}
              className={`${FIELD} min-h-20 ${err("note") ? "border-danger" : "border-border"}`}
            />
            {err("note") ? <p className="mt-1 text-xs text-danger">{err("note")}</p> : null}
          </div>
        </div>

        {p.banner ? (
          <p role="alert" className="mt-4 rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
            {p.banner}
          </p>
        ) : null}
        {p.otp ? (
          <BookingPhoneOtp
            t={p.texts}
            phone={p.otp.phone}
            initialResendAt={p.otp.resendAt}
            initialTestOtp={p.otp.testOtp}
            onChangePhone={p.onChangePhone}
            onVerified={p.onVerified}
          />
        ) : (
          <button
            type="button"
            onClick={p.onSubmit}
            disabled={p.busy || p.onlineOff}
            className="mt-5 h-12 w-full rounded-lg bg-cta px-4 text-sm font-bold tracking-wide text-cta-fg uppercase hover:bg-cta-hover focus-ring disabled:opacity-60"
          >
            {p.busy ? "Đang xử lý…" : p.readyToPay ? "Xác nhận & thanh toán" : "Gửi mã xác minh"}
          </button>
        )}
        <p className="mt-2 text-center text-xs text-muted">Khung giờ được giữ {p.holdMinutes} phút để thanh toán, bắt đầu sau khi bạn xác minh số điện thoại.</p>
        {p.onlineOff ? <p className="mt-2 text-center text-xs text-danger">Đặt online đang tạm ngưng. Vui lòng gọi hotline {p.venue.phone}.</p> : null}
      </section>

      <section className="rounded-xl border border-accent/50 bg-accent-soft p-4 text-sm sm:p-5" aria-labelledby="note-title">
        <h3 id="note-title" className="text-sm font-bold text-accent-fg">
          Lưu ý
        </h3>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-foreground">
          <li>Khung giờ được giữ {p.holdMinutes} phút để chuyển khoản; hết thời gian mà chưa nhận được tiền thì khung giờ được mở lại.</li>
          <li>Đơn đã thanh toán không hủy và không hoàn tiền. Đơn chưa thanh toán có thể hủy giữ chỗ trước khi hết thời gian.</li>
          <li>Vui lòng đến trước giờ chơi và báo mã booking tại quầy.</li>
        </ul>
      </section>
      {p.dialog}
    </div>
  );
}
