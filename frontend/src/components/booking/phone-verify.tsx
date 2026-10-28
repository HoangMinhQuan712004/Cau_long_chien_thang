"use client";

import { useEffect, useRef, useState } from "react";
import { otpErrorText, otpResendAt, requestPhoneVerify, verifyPhone } from "@/lib/api/auth";
import { EMPTY_OTP, OtpForm } from "@/components/auth/otp-form";
import { PhoneForm } from "@/components/auth/phone-form";
import { Alert } from "@/components/ui/alert";
import type { Dictionary } from "@/i18n/dictionaries";

type PhoneVerifyTexts = Dictionary["phoneVerify"];

type PhoneVerifyProps = {
  t: PhoneVerifyTexts;
  onVerified: (merged: boolean, passwordCleared?: boolean) => void;
};

// Khối xác minh SĐT trong trang đặt sân (tài khoản Google chưa có SĐT): nhập số ⇒ OTP ⇒ đặt tiếp
export function PhoneVerify({ t, onVerified }: PhoneVerifyProps) {
  const [phone, setPhone] = useState("");
  // SĐT đã gửi mã ⇒ sang bước nhập mã
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [digits, setDigits] = useState(EMPTY_OTP);
  const [resendAt, setResendAt] = useState<number | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const rootRef = useRef<HTMLElement>(null);

  // Cuộn tới khối (nằm cuối trang trên điện thoại)
  useEffect(() => {
    rootRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  // Gửi/gửi lại mã; 429 vẫn sang bước nhập mã
  async function send(value: string) {
    setIsPending(true);
    setError(null);
    setNotice(null);
    const result = await requestPhoneVerify(value);
    setIsPending(false);
    // Tài khoản vừa có SĐT (tab khác) ⇒ đặt sân luôn
    if (!result.ok && result.code === "phone_already_set") return onVerified(false);
    if (!result.ok) setError(otpErrorText(t.errors, result));
    const at = otpResendAt(result);
    if (at === null) return;
    setResendAt(at);
    if (result.ok && sentTo === value) setNotice(t.resent);
    setSentTo(value);
    setDigits(EMPTY_OTP);
  }

  async function verify(code: string) {
    if (!sentTo || isPending) return;
    setIsPending(true);
    setError(null);
    setNotice(null);
    const result = await verifyPhone(sentTo, code);
    if (result.ok) return onVerified(result.merged, result.password_cleared);
    setIsPending(false);
    if (result.code === "phone_already_set") return onVerified(false);
    setError(otpErrorText(t.errors, result));
    setDigits(EMPTY_OTP);
    // Số không gắn được ⇒ nhập lại mã vô ích, về bước nhập số
    if (result.code === "phone_unusable" || result.code === "merge_has_bookings") setSentTo(null);
  }

  return (
    <section
      ref={rootRef}
      aria-labelledby="phone-verify-title"
      className="flex max-w-xl flex-col gap-4 rounded-card bg-surface p-4 shadow-card sm:p-6"
    >
      <div className="flex flex-col gap-1">
        <h2 id="phone-verify-title" className="text-lg font-semibold">
          {t.title}
        </h2>
        <p className="text-ui text-muted">
          {sentTo ? t.otpDescription.replace("{phone}", sentTo) : t.description}
        </p>
      </div>
      {error && <Alert variant="error">{error}</Alert>}
      {notice && <Alert variant="info">{notice}</Alert>}

      {sentTo === null ? (
        <PhoneForm
          id="verify-phone"
          t={{ label: t.phoneLabel, placeholder: t.phonePlaceholder, submit: t.send, submitting: t.sending }}
          value={phone}
          onChange={setPhone}
          isPending={isPending}
          onSubmit={send}
          onEmpty={() => setError(t.errors.phoneRequired)}
        />
      ) : (
        <OtpForm
          t={t}
          digits={digits}
          onDigitsChange={setDigits}
          onVerify={verify}
          onResend={() => send(sentTo)}
          isPending={isPending}
          resendAt={resendAt}
          changePhone={
            <button
              type="button"
              onClick={() => {
                setSentTo(null);
                setError(null);
                setNotice(null);
              }}
              className="-my-3 py-3 text-ui text-muted focus-ring hover:text-primary"
            >
              {t.changePhone}
            </button>
          }
        />
      )}
    </section>
  );
}
