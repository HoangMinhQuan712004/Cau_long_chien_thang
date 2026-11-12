import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { useCountdown } from "@/hooks/use-countdown";
import { cn } from "@/lib/cn";
import { formatCountdown } from "@/lib/format";

const OTP_LENGTH = 6;
export const EMPTY_OTP = Array<string>(OTP_LENGTH).fill("");

type OtpInputProps = {
  digits: string[];
  onChange: (digits: string[]) => void;
  disabled: boolean;
  label: string;
  digitLabel: string;
};

function OtpInput({ digits, onChange, disabled, label, digitLabel }: OtpInputProps) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const isEmpty = digits.every((d) => !d);

  // Mới vào hoặc vừa nhập sai ⇒ con trỏ về ô đầu
  useEffect(() => {
    if (isEmpty && !disabled) refs.current[0]?.focus();
  }, [isEmpty, disabled]);

  // Rải chuỗi số (gõ, dán, tự điền cả mã) từ ô `from`
  function fill(from: number, text: string) {
    const chars = text.replace(/\D/g, "").slice(0, OTP_LENGTH - from).split("");
    const next = [...digits];
    if (chars.length === 0) next[from] = "";
    chars.forEach((c, i) => (next[from + i] = c));
    onChange(next);
    refs.current[Math.min(from + chars.length, OTP_LENGTH - 1)]?.focus();
  }

  function onKeyDown(i: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key !== "Backspace" || digits[i] || i === 0) return;
    e.preventDefault();
    onChange(digits.map((d, j) => (j === i - 1 ? "" : d)));
    refs.current[i - 1]?.focus();
  }

  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="mb-1.5 text-label font-semibold text-muted">
        {label}
        <span aria-hidden className="ml-0.5 text-danger">
          *
        </span>
      </legend>
      <div className="grid grid-cols-6 gap-2">
        {digits.map((d, i) => (
          <input
            key={i}
            ref={(el) => {
              refs.current[i] = el;
            }}
            value={d}
            onChange={(e) => fill(i, e.target.value)}
            onKeyDown={(e) => onKeyDown(i, e)}
            onPaste={(e) => {
              e.preventDefault();
              fill(i, e.clipboardData.getData("text"));
            }}
            onFocus={(e) => e.target.select()}
            disabled={disabled}
            inputMode="numeric"
            pattern="[0-9]*"
            // Chỉ ô đầu nhận gợi ý mã từ bàn phím điện thoại
            autoComplete={i === 0 ? "one-time-code" : "off"}
            maxLength={OTP_LENGTH}
            aria-label={digitLabel.replace("{n}", String(i + 1))}
            className={cn(
              "h-12 w-full rounded-lg border border-border-strong bg-surface text-center text-xl",
              "font-semibold tabular-nums focus-ring transition-shadow",
              "disabled:cursor-not-allowed disabled:bg-background disabled:text-muted",
            )}
          />
        ))}
      </div>
    </fieldset>
  );
}

type OtpFormProps = {
  t: {
    otpLabel: string;
    digitLabel: string;
    submit: string;
    submitting: string;
    resend: string;
    resendIn: string;
  };
  digits: string[];
  onDigitsChange: (digits: string[]) => void;
  onVerify: (code: string) => void;
  onResend: () => void;
  isPending: boolean;
  disabled?: boolean;
  resendAt: number | null;
  changePhone: React.ReactNode;
};

// Bước nhập mã OTP: 6 ô, "Xác nhận" khi đủ số (Enter = bấm), "Gửi lại mã" đếm ngược, "Đổi số"
export function OtpForm({
  t,
  digits,
  onDigitsChange,
  onVerify,
  onResend,
  isPending,
  disabled = false,
  resendAt,
  changePhone,
}: OtpFormProps) {
  const remaining = useCountdown(resendAt, () => {});
  const isComplete = digits.every(Boolean);
  return (
    <form
      noValidate
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (isComplete) onVerify(digits.join(""));
      }}
    >
      <OtpInput
        digits={digits}
        onChange={onDigitsChange}
        disabled={isPending || disabled}
        label={t.otpLabel}
        digitLabel={t.digitLabel}
      />
      <Button type="submit" block loading={isPending} disabled={!isComplete || disabled}>
        {isPending ? t.submitting : t.submit}
      </Button>
      <div className="flex flex-wrap items-center justify-between gap-x-4">
        <button
          type="button"
          onClick={onResend}
          disabled={remaining > 0 || isPending || disabled}
          className={cn(
            "-my-3 py-3 text-ui font-semibold text-primary tabular-nums focus-ring",
            "disabled:cursor-not-allowed disabled:font-normal disabled:text-muted",
          )}
        >
          {remaining > 0 ? t.resendIn.replace("{time}", formatCountdown(remaining)) : t.resend}
        </button>
        {changePhone}
      </div>
    </form>
  );
}
