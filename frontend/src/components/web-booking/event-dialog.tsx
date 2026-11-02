"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import type { Dictionary } from "@/i18n/dictionaries";
import { otpErrorText, otpResendAt } from "@/lib/api/auth";
import { api } from "@/lib/api/client";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatLongDate, formatVnd, hhmm } from "@/lib/format";
import { isValidPhone, normalizePhone } from "@/lib/phone";
import { fullAddress, site } from "@/lib/site";
import { MemberHint } from "./member-hint";
import { BookingPhoneOtp, type VerifiedAccount } from "./phone-otp";
import { getEventDetail, requestBookingPhone, sendEventCheckout } from "./requests";
import { clearToken, saveToken, savedToken, useVerifiedPhone } from "./session-store";
import type { EventDetail, EventReason, PayStatus } from "./types";

// Popup mua vé sự kiện (T-023 AC17), dùng chung /dat-san (khách) và /hoi-vien/dat-san (hội viên điền sẵn + khóa, không OTP).
// Từ trên xuống: thông tin sân · thẻ vé · số vé · phương thức · gợi ý đăng nhập (khách) · khách hàng · thanh dưới "Tổng" + Xác nhận.

const MAX_SEATS = 10;
const PAY_LABEL: Record<PayStatus, string> = { unpaid: "Chưa thanh toán", paid: "Đã thanh toán", uncollectible: "Không thu được" };
const REASON_TEXT: Record<EventReason, string> = {
  started: "Sự kiện đã bắt đầu.",
  full: "Sự kiện đã hết chỗ.",
  free: "Sự kiện này không bán vé online. Đăng ký tại quầy.",
  online_off: "Đặt online đang tạm ngưng.",
  deleted: "Sự kiện không còn nữa.",
};

type Me = { full_name: string; phone: string | null; phone_verified: boolean };
type Member = { name: string; phone: string };

export function EventDialog({
  eventCode,
  date,
  member,
  hotline,
  texts,
  onClose,
  onChanged,
}: {
  /** Mở khi khác null */
  eventCode: string | null;
  /** Ngày đang xem trên lưới – để dựng `next` cho đăng nhập / đăng ký */
  date: string;
  member?: Member;
  hotline: string;
  texts: Dictionary["phoneVerify"];
  onClose: () => void;
  /** Chỗ / giờ đã đổi (409) ⇒ lưới cần tải lại */
  onChanged: () => void;
}) {
  const router = useRouter();
  const ids = { name: useId(), phone: useId() };
  const [detail, setDetail] = useState<{ code: string; data: EventDetail | null } | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [seats, setSeats] = useState(1);
  const [me, setMe] = useState<Me | null>(null);
  const [isGuest, setIsGuest] = useState(false);
  const [form, setForm] = useState({ name: member?.name ?? "", phone: member?.phone ?? "" });
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  const [otp, setOtp] = useState<{ phone: string; resendAt: number | null; testOtp: string | null } | null>(null);
  const verifiedPhone = useVerifiedPhone();

  const open = eventCode !== null;

  // Tải chi tiết sự kiện (có cookie hội viên thì kèm `my_tickets`)
  useEffect(() => {
    if (!eventCode) return;
    let stop = false;
    getEventDetail(eventCode).then((res) => {
      if (stop) return;
      setFailed(!res.ok);
      setDetail({ code: eventCode, data: res.ok ? res.data : null });
    });
    return () => {
      stop = true;
    };
  }, [eventCode, attempt]);

  // Mỗi lần mở: về 1 vé, xóa lỗi và bước OTP cũ
  useEffect(() => {
    if (!eventCode) return;
    /* eslint-disable react-hooks/set-state-in-effect -- đặt lại khi mở sự kiện */
    setSeats(1);
    setBanner("");
    setSubmitted(false);
    setOtp(null);
    setFailed(false);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [eventCode]);

  // Khách đang đăng nhập: điền sẵn tên + SĐT; chưa đăng nhập (401): hiện gợi ý. Hội viên (member) đã có từ hồ sơ.
  useEffect(() => {
    if (!eventCode || member) return;
    let stop = false;
    api
      .GET("/api/v1/auth/me")
      .then(({ data }) => {
        if (stop) return;
        if (!data) return setIsGuest(true);
        setIsGuest(false);
        setMe({ full_name: data.full_name, phone: data.phone ?? null, phone_verified: data.phone_verified });
        setForm((f) => ({ name: f.name || data.full_name, phone: f.phone || data.phone || "" }));
      })
      .catch(() => {});
    return () => {
      stop = true;
    };
  }, [eventCode, member]);

  const data = detail && detail.code === eventCode ? detail.data : null;
  const remaining = data ? Math.max(data.capacity - data.taken, 0) : 0;
  const maxSeats = Math.min(remaining, MAX_SEATS);
  const reason: EventReason | null = !data ? null : (data.reason ?? (data.ticket_price <= 0 ? "free" : remaining <= 0 ? "full" : null));
  const canBuy = Boolean(data?.can_buy) && !reason && maxSeats > 0;
  const count = Math.min(Math.max(seats, 1), Math.max(maxSeats, 1));
  const total = data ? count * data.ticket_price : 0;

  const cleanName = form.name.trim().replace(/\s+/g, " ");
  const phone = normalizePhone(form.phone);
  const errors = {
    name: !cleanName ? "Vui lòng nhập họ tên." : cleanName.length > 100 ? "Họ tên tối đa 100 ký tự." : "",
    phone: !isValidPhone(phone) ? "Số điện thoại không hợp lệ — cần đủ 10 số." : "",
  };
  const showErr = (k: "name" | "phone") => submitted && errors[k];
  const skipOtp = Boolean(member) || Boolean(me?.phone_verified && me.phone && normalizePhone(me.phone) === phone);
  const hasToken = isValidPhone(phone) && verifiedPhone === phone;
  const needsOtp = !skipOtp && !hasToken;

  // Đặt online lúc đã đăng nhập: xác minh SĐT xong có thể thành hội viên / gộp tài khoản (T-021). Việc mua vẫn tiếp tục.
  function afterAccountVerified(a: VerifiedAccount) {
    if (a.becameMember) toast(a.memberCode ? `Bạn đã là hội viên ${a.memberCode}` : "Bạn đã là hội viên", 'Mục "Khu hội viên" đã có ở menu tài khoản.');
    else if (a.reason === "E-AUTH-31") toast("Tài khoản hội viên đang bị ngừng. Vui lòng liên hệ quầy.", undefined, "error");
    if (a.merged) {
      void api
        .GET("/api/v1/auth/me")
        .then(({ data: d }) => d && setMe({ full_name: d.full_name, phone: d.phone ?? null, phone_verified: d.phone_verified }))
        .catch(() => {});
    }
    if (a.becameMember || a.merged) router.refresh();
  }

  /** Nút Xác nhận: kiểm form → (cần thì) gửi mã OTP → khi có phone_token mới giữ chỗ 5 phút và sang trang QR. */
  async function submit(tokenOverride?: string) {
    if (!data || !canBuy || busy) return;
    setSubmitted(true);
    setBanner("");
    if (errors.name || errors.phone) {
      document.getElementById(errors.name ? ids.name : ids.phone)?.focus();
      return;
    }
    const phoneToken = skipOtp ? null : (tokenOverride ?? savedToken(phone));
    setBusy(true);
    try {
      if (!skipOtp && !phoneToken) {
        const sent = await requestBookingPhone(phone);
        const at = otpResendAt(sent);
        // 429 vẫn sang bước nhập mã (mã trước còn dùng được); lỗi khác ⇒ báo ngay
        if (at === null) {
          if (!sent.ok) setBanner(otpErrorText(texts.errors, sent));
          return;
        }
        setOtp({ phone, resendAt: at, testOtp: sent.ok ? (sent.test_otp ?? null) : null });
        return;
      }
      const res = await write(
        (key) =>
          sendEventCheckout(key, {
            event_code: data.code,
            seats: count,
            full_name: cleanName,
            phone,
            as_member: Boolean(member),
            ...(phoneToken ? { phone_token: phoneToken } : {}),
          }),
        { retryRateLimit: false },
      );
      if (res.ok) {
        const token = (res.data as { token?: string }).token;
        if (!token) return setBanner("Không nhận được mã thanh toán. Vui lòng thử lại.");
        router.push(member ? `/hoi-vien/thanh-toan/${token}` : `/thanh-toan/${token}`);
        return;
      }
      const e = res.error;
      if (e.code === "E-WEB-8") clearToken(); // token hết hạn / không khớp SĐT ⇒ xác minh lại ở lần bấm kế tiếp
      setBanner(errorText(e));
      // Hết chỗ / đã bắt đầu / đã xóa: số liệu cũ ⇒ tải lại popup và lưới
      if (e.status === 409) {
        setAttempt((n) => n + 1);
        onChanged();
      }
    } finally {
      setBusy(false);
    }
  }

  const field = "w-full rounded-lg border bg-surface px-3 py-2.5 text-sm read-only:bg-background";
  // Đăng nhập / đăng ký xong quay về đúng ngày và tự mở lại popup này (AC18)
  const nextAfterLogin = `/dat-san?date=${date}&event=${eventCode ?? ""}`;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={data?.name ?? "Sự kiện"}
      footer={
        canBuy && data ? (
          <div className="flex w-full items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs text-muted">
                Tổng ({count} Vé)
              </p>
              <p className="text-lg font-bold text-primary tabular-nums">{formatVnd(total)}</p>
            </div>
            <Button onClick={() => void submit()} loading={busy} disabled={otp !== null || Boolean(errors.name || errors.phone)} className="min-h-11 px-6">
              {busy ? "Đang xử lý…" : needsOtp ? "Gửi mã xác minh" : "Xác nhận"}
            </Button>
          </div>
        ) : (
          <Button variant="secondary" onClick={onClose}>
            Đóng
          </Button>
        )
      }
    >
      {data ? (
        <>
          {/* 1. Thông tin sân */}
          <section aria-label="Thông tin sân" className="flex items-center gap-3 rounded-xl border border-border bg-surface p-3">
            <span aria-hidden className="grid size-11 shrink-0 place-items-center rounded-full bg-primary-softer text-xl">
              🏸
            </span>
            <div className="min-w-0 text-sm">
              <p className="font-semibold">{site.name}</p>
              <p className="text-xs text-muted">{fullAddress}</p>
            </div>
          </section>

          {/* 2. Thẻ vé */}
          <section aria-label="Thông tin sự kiện" className="relative overflow-hidden rounded-xl border border-primary/40 bg-primary-softer text-sm">
            <div className="p-3">
              <span className="rounded bg-surface px-1.5 py-0.5 text-[11px] font-semibold text-muted">{data.code}</span>
              <p className="mt-1.5 font-bold">{data.name}</p>
            </div>
            <div aria-hidden className="relative border-t border-dashed border-primary/40">
              <span className="absolute -top-2 -left-2 size-4 rounded-full border border-primary/40 bg-surface" />
              <span className="absolute -top-2 -right-2 size-4 rounded-full border border-primary/40 bg-surface" />
            </div>
            <dl className="space-y-2 p-3">
              <TicketRow label="Giá vé" value={data.ticket_price > 0 ? formatVnd(data.ticket_price) : "Miễn phí"} />
              <TicketRow label="Ngày" value={formatLongDate(data.play_date)} />
              <div>
                <dt className="text-muted">Sân &amp; Thời gian</dt>
                <dd className="mt-1 rounded-md bg-surface px-2 py-1.5 font-medium">
                  {hhmm(data.start_time)} - {hhmm(data.end_time)} <span className="font-normal text-muted">| {data.resource_names.join(", ")}</span>
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3 border-t border-primary/30 pt-2">
                <dt className="text-muted">Người tham gia</dt>
                <dd className="rounded-full bg-surface px-3 py-1 font-semibold tabular-nums">
                  {data.taken}/{data.capacity}
                </dd>
              </div>
            </dl>
          </section>

          {data.my_tickets && data.my_tickets.length > 0 ? (
            <section aria-label="Vé của tôi" className="rounded-lg bg-primary-softer p-3 text-sm">
              <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">Vé của tôi</h3>
              <ul className="mt-1.5 space-y-1">
                {data.my_tickets.map((t) => (
                  <li key={t.code} className="flex flex-wrap justify-between gap-x-3">
                    <b>{t.code}</b>
                    <span>{PAY_LABEL[t.pay_status]}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {canBuy ? (
            <>
              {/* 3. Số lượng vé */}
              <section aria-label="Số lượng vé" className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface p-3">
                <span id={`${ids.name}-seats`} className="text-sm font-medium">
                  Số lượng vé muốn đặt
                </span>
                <div role="group" aria-labelledby={`${ids.name}-seats`} className="flex items-center gap-1">
                  <button
                    type="button"
                    aria-label="Giảm số vé"
                    disabled={busy || otp !== null || count <= 1}
                    onClick={() => setSeats(count - 1)}
                    className="grid size-10 place-items-center rounded-lg bg-background text-lg font-bold focus-ring disabled:opacity-40"
                  >
                    –
                  </button>
                  <output aria-live="polite" className="w-9 text-center font-semibold tabular-nums">
                    {count}
                  </output>
                  <button
                    type="button"
                    aria-label="Tăng số vé"
                    disabled={busy || otp !== null || count >= maxSeats}
                    onClick={() => setSeats(count + 1)}
                    className="grid size-10 place-items-center rounded-lg bg-primary text-lg font-bold text-surface focus-ring disabled:opacity-40"
                  >
                    +
                  </button>
                </div>
              </section>

              {/* 4. Phương thức thanh toán */}
              <section aria-label="Phương thức thanh toán" className="rounded-xl border border-border bg-surface p-3 text-sm">
                <h3 className="font-semibold text-primary">Phương thức thanh toán</h3>
                <div className="mt-2 flex items-center justify-between gap-3">
                  <span>Chuyển khoản ngân hàng (QR)</span>
                  <span aria-hidden className="grid size-5 place-items-center rounded bg-primary text-xs text-surface">
                    ✓
                  </span>
                </div>
                <p className="mt-2 flex items-center justify-between gap-3 rounded-lg border border-primary/50 bg-primary-softer px-3 py-2">
                  <span>
                    Tổng tiền: <b className="text-primary tabular-nums">{formatVnd(total)}</b>
                  </span>
                  <b className="whitespace-nowrap">{count} Vé</b>
                </p>
              </section>

              {/* 5. Chỉ khi chưa đăng nhập */}
              {isGuest && !member ? <MemberHint compact next={nextAfterLogin} /> : null}

              {/* 6. Thông tin khách hàng */}
              <section aria-label="Thông tin khách hàng" className="space-y-3 text-sm">
                <h3 className="font-semibold text-primary">Thông tin khách hàng</h3>
                <div>
                  <label htmlFor={ids.name} className="mb-1 block font-medium">
                    Tên khách hàng <span className="text-danger">*</span>
                  </label>
                  <input
                    id={ids.name}
                    value={form.name}
                    maxLength={120}
                    readOnly={Boolean(member) || otp !== null}
                    autoComplete="name"
                    placeholder="Nhập tên của bạn"
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                    aria-invalid={Boolean(showErr("name")) || undefined}
                    className={`${field} ${showErr("name") ? "border-danger" : "border-border"}`}
                  />
                  {showErr("name") ? (
                    <p role="alert" className="mt-1 text-xs text-danger">
                      {errors.name}
                    </p>
                  ) : null}
                </div>
                <div>
                  <label htmlFor={ids.phone} className="mb-1 block font-medium">
                    Số điện thoại <span className="text-danger">*</span>
                  </label>
                  <input
                    id={ids.phone}
                    value={form.phone}
                    inputMode="tel"
                    autoComplete="tel"
                    maxLength={16}
                    readOnly={Boolean(member) || otp !== null}
                    placeholder="Nhập số điện thoại"
                    onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
                    aria-invalid={Boolean(showErr("phone")) || undefined}
                    aria-describedby={`${ids.phone}-hint`}
                    className={`${field} ${showErr("phone") ? "border-danger" : "border-border"}`}
                  />
                  {showErr("phone") ? (
                    <p role="alert" className="mt-1 text-xs text-danger">
                      {errors.phone}
                    </p>
                  ) : null}
                  <p id={`${ids.phone}-hint`} className="mt-1 text-xs text-muted">
                    Dùng số này cùng mã đơn để tra cứu vé.
                    {isValidPhone(phone) && (skipOtp || hasToken) ? <b className="ml-1 font-semibold text-primary">Số điện thoại đã xác minh.</b> : null}
                  </p>
                </div>
                {otp ? (
                  <BookingPhoneOtp
                    t={texts}
                    phone={otp.phone}
                    initialResendAt={otp.resendAt}
                    initialTestOtp={otp.testOtp}
                    onChangePhone={() => setOtp(null)}
                    onVerified={(token, expiresAt, accountVerified, account) => {
                      saveToken({ phone: otp.phone, token, expiresAt });
                      if (accountVerified && me?.phone && normalizePhone(me.phone) === otp.phone) setMe({ ...me, phone_verified: true });
                      afterAccountVerified(account);
                      setOtp(null);
                      void submit(token); // đã xác minh: giữ chỗ + tạo thanh toán luôn
                    }}
                  />
                ) : null}
              </section>

              {banner ? <Alert variant="error">{banner}</Alert> : null}
              <p className="text-center text-xs text-muted">Giữ chỗ 5 phút để chuyển khoản QR. Tiền về là có vé.</p>
            </>
          ) : (
            <p role="status" className="rounded-lg border border-border bg-background p-3 text-sm">
              {reason === "online_off" ? `${REASON_TEXT.online_off} Vui lòng gọi hotline ${hotline}.` : reason ? REASON_TEXT[reason] : "Hiện chưa mua vé online được."}
            </p>
          )}
        </>
      ) : failed ? (
        <div role="alert" className="space-y-3 text-sm">
          <p className="text-danger">Không tải được thông tin sự kiện.</p>
          <Button variant="secondary" onClick={() => setAttempt((n) => n + 1)}>
            Thử lại
          </Button>
        </div>
      ) : (
        <p className="text-sm text-muted" aria-busy>
          Đang tải…
        </p>
      )}
    </Modal>
  );
}

function TicketRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  );
}
