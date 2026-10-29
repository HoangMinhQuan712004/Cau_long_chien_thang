"use client";

import { useState } from "react";
import { EMPTY_OTP, OtpForm } from "@/components/auth/otp-form";
import { TestOtpNotice } from "@/components/auth/test-otp-notice";
import { Alert } from "@/components/ui/alert";
import type { Dictionary } from "@/i18n/dictionaries";
import { otpErrorText, otpResendAt } from "@/lib/api/auth";
import { requestBookingPhone, verifyBookingPhone } from "./requests";

type Texts = Dictionary["phoneVerify"];

// Bước xác minh SĐT trước khi giữ chỗ (T-013 AC24): nhập 6 số OTP gửi tới `phone`; đúng ⇒ `phone_token` (30 phút).
// Các khung giờ đã chọn nằm ở cha và giữ nguyên trong suốt bước này.
export function BookingPhoneOtp({
  t,
  phone,
  initialResendAt,
  initialTestOtp,
  onVerified,
  onChangePhone,
}: {
  t: Texts;
  phone: string;
  initialResendAt: number | null;
  initialTestOtp: string | null;
  onVerified: (token: string, expiresAt: string) => void;
  onChangePhone: () => void;
}) {
  const [digits, setDigits] = useState(EMPTY_OTP);
  const [resendAt, setResendAt] = useState(initialResendAt);
  const [testOtp, setTestOtp] = useState(initialTestOtp);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function verify(code: string) {
    if (isPending) return;
    setIsPending(true);
    setError(null);
    setNotice(null);
    const result = await verifyBookingPhone(phone, code);
    if (result.ok) return onVerified(result.phone_token, result.expires_at);
    setIsPending(false);
    setError(otpErrorText(t.errors, result));
    setDigits(EMPTY_OTP);
  }

  async function resend() {
    setError(null);
    setNotice(null);
    const result = await requestBookingPhone(phone);
    if (!result.ok) setError(otpErrorText(t.errors, result));
    const at = otpResendAt(result);
    if (at === null) return;
    setResendAt(at);
    if (!result.ok) return;
    setTestOtp(result.test_otp ?? null);
    setDigits(EMPTY_OTP);
    setNotice(t.resent);
  }

  return (
    <div className="mt-5 flex flex-col gap-4 border-t border-border pt-5" aria-live="polite">
      <div>
        <h3 className="text-base font-semibold">{t.title}</h3>
        <p className="mt-1 text-sm text-muted">{t.otpDescription.replace("{phone}", phone)}</p>
      </div>
      {error && <Alert variant="error">{error}</Alert>}
      {notice && <Alert variant="info">{notice}</Alert>}
      <TestOtpNotice code={testOtp} />
      <OtpForm
        t={t}
        digits={digits}
        onDigitsChange={setDigits}
        onVerify={verify}
        onResend={resend}
        isPending={isPending}
        resendAt={resendAt}
        changePhone={
          <button type="button" onClick={onChangePhone} className="-my-3 py-3 text-ui text-muted focus-ring hover:text-primary">
            {t.changePhone}
          </button>
        }
      />
    </div>
  );
}
