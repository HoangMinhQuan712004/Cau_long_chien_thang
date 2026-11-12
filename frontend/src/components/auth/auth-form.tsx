"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { GoogleSignIn } from "@/app/(auth)/dang-nhap/_components/google-sign-in";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import type { Dictionary } from "@/i18n/dictionaries";
import { googleSignIn, otpErrorText, otpResendAt, registerRequest, registerVerify } from "@/lib/api/auth";
import { toast } from "@/lib/feedback";
import { isValidPhone, normalizePhone } from "@/lib/phone";
import { destination, safeNext } from "@/lib/safe-next";
import { EMPTY_OTP, OtpForm } from "./otp-form";
import { isPasswordValid, PASSWORD_MAX, PasswordRules, type PasswordRulesTexts } from "./password-rules";
import { TestOtpNotice } from "./test-otp-notice";

// "0912345678" ⇒ "09•• ••• 678"
const maskPhone = (phone: string) => `${phone.slice(0, 2)}•• ••• ${phone.slice(-3)}`;

type Step = { kind: "info" } | { kind: "otp"; phone: string; resendAt: number | null; testOtp: string | null };

/**
 * Đăng ký tài khoản khách, 2 bước (T-021): thông tin ⇒ mã OTP gửi tới SĐT. Đúng mã ⇒ tài khoản + hội viên + đăng nhập
 * luôn, vào khu hội viên. Đăng nhập dùng màn chung /dang-nhap.
 */
export function AuthForm({
  rules,
  login,
  forgot,
}: {
  rules: PasswordRulesTexts;
  login: Dictionary["login"];
  forgot: Dictionary["forgot"];
}) {
  const router = useRouter();
  const nextParam = safeNext(useSearchParams().get("next"), "");
  const [step, setStep] = useState<Step>({ kind: "info" });
  const [fullName, setFullName] = useState("");
  const [phoneText, setPhoneText] = useState("");
  const [password, setPassword] = useState("");
  const [digits, setDigits] = useState(EMPTY_OTP);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [isGoogleOff, setIsGoogleOff] = useState(false);
  // E-AUTH-23: chưa có kênh OTP ⇒ đăng ký tạm ngưng
  const [isClosed, setIsClosed] = useState(false);
  // E-AUTH-22 (báo sau OTP đúng): SĐT đã có tài khoản ⇒ câu của BE + link Đăng nhập / Quên mật khẩu
  const [taken, setTaken] = useState<{ message: string; phone: string } | null>(null);

  const phone = normalizePhone(phoneText);
  const canSubmit = fullName.trim() !== "" && isValidPhone(phone) && isPasswordValid(password) && !pending && !isClosed;

  // Gửi mã (bước 1) hoặc gửi lại mã (bước 2); 429 vẫn sang bước nhập mã vì mã trước còn dùng được
  async function send(resend = false) {
    setPending(true);
    setError(null);
    setNotice(null);
    setTaken(null);
    const result = await registerRequest({ full_name: fullName.trim().replace(/\s+/g, " "), phone, password });
    setPending(false);
    if (!result.ok && result.code === "E-AUTH-23") {
      setIsClosed(true);
      setStep({ kind: "info" });
      return setError(result.message ?? forgot.errors.unavailable);
    }
    if (!result.ok) setError(otpErrorText(forgot.errors, result));
    const at = otpResendAt(result);
    if (at === null) return;
    setStep({ kind: "otp", phone, resendAt: at, testOtp: result.ok ? (result.test_otp ?? null) : null });
    setDigits(EMPTY_OTP);
    if (resend && result.ok) setNotice(forgot.verify.resent);
  }

  async function verify(code: string) {
    if (step.kind !== "otp" || pending) return;
    setPending(true);
    setError(null);
    setNotice(null);
    const result = await registerVerify(step.phone, code);
    if (result.ok) {
      const name = result.account.full_name.trim().split(/\s+/).pop() ?? result.account.full_name;
      toast(
        `Chào mừng ${name}, bạn đã là hội viên ${result.member_code}`,
        result.upgraded_from_temp ? "Lịch sử đặt sân trước đây của bạn đã được giữ lại." : undefined,
      );
      // Hội viên mới vào khu hội viên (hoặc ?next an toàn, không vào khu quản trị)
      router.replace(destination("member", nextParam, "/hoi-vien"));
      router.refresh();
      return;
    }
    setPending(false);
    setDigits(EMPTY_OTP);
    if (result.code === "E-AUTH-22") {
      return setTaken({ message: result.message ?? "", phone: step.phone });
    }
    // Mã hết hạn / nhập sai quá nhiều ⇒ "Gửi lại mã"; E-AUTH-31 (hội viên Ngừng) ⇒ câu của BE (liên hệ quầy)
    setError(otpErrorText(forgot.errors, result));
  }

  // Khách đăng ký/đăng nhập bằng Google (tạo tài khoản khách nếu chưa có)
  async function onGoogle(credential: string) {
    setPending(true);
    setError(null);
    const result = await googleSignIn(credential);
    if (result.ok) {
      router.replace(destination("member", nextParam));
      router.refresh();
      return;
    }
    setPending(false);
    if (result.code === "google_disabled") return setIsGoogleOff(true);
    setError(login.errors[result.code as keyof typeof login.errors] ?? login.errors.unavailable);
  }

  const loginHref = nextParam ? `/dang-nhap?next=${encodeURIComponent(nextParam)}` : "/dang-nhap";

  if (step.kind === "otp") {
    return (
      <div className="flex flex-col gap-4">
        <p className="text-ui text-muted">{forgot.verify.description.replace("{phone}", maskPhone(step.phone))}</p>
        {error && <Alert variant="error">{error}</Alert>}
        {notice && <Alert variant="info">{notice}</Alert>}
        {taken && <PhoneTaken message={taken.message} phone={taken.phone} t={login.phoneTaken} />}
        <TestOtpNotice code={step.testOtp} />
        <OtpForm
          t={forgot.verify}
          digits={digits}
          onDigitsChange={setDigits}
          onVerify={verify}
          onResend={() => void send(true)}
          isPending={pending}
          disabled={taken !== null}
          resendAt={step.resendAt}
          changePhone={
            <button
              type="button"
              onClick={() => {
                setStep({ kind: "info" });
                setError(null);
                setNotice(null);
                setTaken(null);
              }}
              className="-my-3 py-3 text-ui text-muted focus-ring hover:text-primary"
            >
              {forgot.verify.changePhone}
            </button>
          }
        />
      </div>
    );
  }

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        if (canSubmit) void send();
      }}
      className="flex flex-col gap-4"
    >
      <Field label="Họ tên" htmlFor="full_name" required>
        <Input
          id="full_name"
          name="full_name"
          required
          maxLength={100}
          autoComplete="name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
        />
      </Field>
      <Field label="Số điện thoại" htmlFor="phone" required>
        <Input
          id="phone"
          name="phone"
          type="tel"
          inputMode="tel"
          required
          autoComplete="tel"
          value={phoneText}
          onChange={(e) => setPhoneText(e.target.value)}
        />
      </Field>
      <Field label="Mật khẩu" htmlFor="password" required>
        <PasswordInput
          id="password"
          name="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          maxLength={PASSWORD_MAX}
          autoComplete="new-password"
          aria-describedby="register-password-rules"
          showLabel={login.showPassword}
          hideLabel={login.hidePassword}
        />
      </Field>
      <PasswordRules id="register-password-rules" password={password} t={rules} />
      {error && <Alert variant="error">{error}</Alert>}
      <Button type="submit" block loading={pending} disabled={!canSubmit}>
        {pending ? "Đang gửi mã…" : "Đăng ký"}
      </Button>
      <p className="text-center text-xs text-muted">
        Mã xác minh gửi qua Zalo tới số điện thoại của bạn.
      </p>
      <GoogleSignIn onCredential={onGoogle} disabled={pending} isServerDisabled={isGoogleOff} t={login.google} />
      <p className="text-center text-sm text-muted">
        Đã có tài khoản?{" "}
        <Link href={loginHref} className="rounded-sm font-semibold text-primary focus-ring hover:underline">
          Đăng nhập
        </Link>
      </p>
    </form>
  );
}

// SĐT đã có tài khoản (mọi loại – không lộ là hội viên hay không): câu của BE + Đăng nhập / Quên mật khẩu
function PhoneTaken({ message, phone, t }: { message: string; phone: string; t: Dictionary["login"]["phoneTaken"] }) {
  const query = phone ? `?sdt=${encodeURIComponent(phone)}` : "";
  return (
    <div role="alert" className="flex flex-col gap-2 rounded-lg border border-danger/30 bg-danger-soft p-3 text-sm">
      <p>{message}</p>
      <p className="flex flex-wrap gap-x-4 gap-y-1 font-semibold">
        <Link href="/dang-nhap" className="rounded-sm text-primary focus-ring hover:underline">
          {t.login}
        </Link>
        <Link href={`/quen-mat-khau${query}`} className="rounded-sm text-primary focus-ring hover:underline">
          {t.forgot}
        </Link>
      </p>
    </div>
  );
}
