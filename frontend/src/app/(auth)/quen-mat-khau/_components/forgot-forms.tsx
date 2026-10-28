"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { EMPTY_OTP, OtpForm } from "@/components/auth/otp-form";
import { PhoneForm } from "@/components/auth/phone-form";
import { TestOtpNotice } from "@/components/auth/test-otp-notice";
import { Alert } from "@/components/ui/alert";
import { useResetOnHide } from "@/hooks/use-reset-on-hide";
import type { Dictionary } from "@/i18n/dictionaries";
import {
  otpErrorText,
  otpResendAt,
  RESET_PHONE_KEY,
  RESET_RESEND_KEY,
  RESET_TEST_OTP_KEY,
  RESET_TOKEN_KEY,
  requestReset,
  saveResetValue,
  useResetValue,
  verifyOtp,
} from "@/lib/api/auth";
import { AuthTextLink } from "../../_components/auth-card";

type ForgotTexts = Dictionary["forgot"];

// Màn 1: nhập SĐT ⇒ gửi mã Zalo ⇒ sang màn nhập mã (429 vẫn sang vì mã trước còn dùng được)
export function RequestForm({ t }: { t: ForgotTexts }) {
  const router = useRouter();
  const [phone, setPhone] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useResetOnHide(() => {
    setIsPending(false);
    setError(null);
  });

  async function send(value: string) {
    setIsPending(true);
    setError(null);
    const result = await requestReset(value);
    const at = otpResendAt(result);
    if (at === null) {
      setIsPending(false);
      if (!result.ok) setError(otpErrorText(t.errors, result));
      return;
    }
    saveResetValue(RESET_PHONE_KEY, value);
    saveResetValue(RESET_TOKEN_KEY, null);
    saveResetValue(RESET_RESEND_KEY, String(at));
    saveResetValue(RESET_TEST_OTP_KEY, result.ok ? (result.test_otp ?? null) : null);
    router.push("/quen-mat-khau/xac-minh");
  }

  return (
    <div className="flex flex-col gap-4">
      {error && <Alert variant="error">{error}</Alert>}
      <PhoneForm
        id="phone"
        t={{
          label: t.request.phoneLabel,
          placeholder: t.request.phonePlaceholder,
          submit: t.request.submit,
          submitting: t.request.submitting,
        }}
        value={phone}
        onChange={setPhone}
        isPending={isPending}
        onSubmit={send}
        onEmpty={() => setError(t.errors.phoneRequired)}
      >
        <AuthTextLink href="/dang-nhap">{t.backToLogin}</AuthTextLink>
      </PhoneForm>
    </div>
  );
}

// "0912345678" ⇒ "09•• ••• 678" (khoảng trắng không ngắt dòng)
const maskPhone = (phone: string) => `${phone.slice(0, 2)}•• ••• ${phone.slice(-3)}`;

// Màn 2: nhập mã 6 số ⇒ nhận reset_token ⇒ sang màn đặt mật khẩu mới
export function VerifyForm({ t }: { t: ForgotTexts }) {
  const router = useRouter();
  const phone = useResetValue(RESET_PHONE_KEY);
  const storedResendAt = Number(useResetValue(RESET_RESEND_KEY)) || null;
  const storedTestOtp = useResetValue(RESET_TEST_OTP_KEY);
  // Mã thử của lần "Gửi lại mã" (state vì sessionStorage không báo thay đổi trong cùng tab)
  const [testOtp, setTestOtp] = useState<string | null | undefined>(undefined);
  // Mốc mới khi bấm "Gửi lại mã" (sessionStorage không báo thay đổi trong cùng tab)
  const [resendAt, setResendAt] = useState<number | null>(null);
  const [digits, setDigits] = useState(EMPTY_OTP);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  useResetOnHide(() => {
    setIsPending(false);
    setError(null);
    setDigits(EMPTY_OTP);
  });

  // Vào thẳng màn này (chưa nhập SĐT) ⇒ về màn 1
  useEffect(() => {
    if (phone === null) router.replace("/quen-mat-khau");
  }, [phone, router]);

  async function verify(code: string) {
    if (!phone || isPending) return;
    setIsPending(true);
    setError(null);
    setNotice(null);
    const result = await verifyOtp(phone, code);
    if (result.ok) {
      saveResetValue(RESET_TOKEN_KEY, result.reset_token);
      router.push("/quen-mat-khau/dat-lai");
      return;
    }
    setIsPending(false);
    setError(otpErrorText(t.errors, result));
    setDigits(EMPTY_OTP);
  }

  async function resend() {
    if (!phone) return;
    setError(null);
    setNotice(null);
    const result = await requestReset(phone);
    if (!result.ok) setError(otpErrorText(t.errors, result));
    const at = otpResendAt(result);
    if (at === null) return;
    saveResetValue(RESET_RESEND_KEY, String(at));
    setResendAt(at);
    if (!result.ok) return;
    saveResetValue(RESET_TEST_OTP_KEY, result.test_otp ?? null);
    setTestOtp(result.test_otp ?? null);
    setDigits(EMPTY_OTP);
    setNotice(t.verify.resent);
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-ui text-muted">
        {t.verify.description.replace("{phone}", phone ? maskPhone(phone) : "…")}
      </p>
      {error && <Alert variant="error">{error}</Alert>}
      {notice && <Alert variant="info">{notice}</Alert>}
      <TestOtpNotice code={testOtp === undefined ? storedTestOtp : testOtp} />
      <OtpForm
        t={t.verify}
        digits={digits}
        onDigitsChange={setDigits}
        onVerify={verify}
        onResend={resend}
        isPending={isPending}
        disabled={!phone}
        resendAt={resendAt ?? storedResendAt}
        changePhone={<AuthTextLink href="/quen-mat-khau">{t.verify.changePhone}</AuthTextLink>}
      />
    </div>
  );
}
