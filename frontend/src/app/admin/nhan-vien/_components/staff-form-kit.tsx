import { useRef, useState } from "react";
import { isPasswordValid, PASSWORD_MAX, PasswordRules } from "@/components/auth/password-rules";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import type { Dictionary } from "@/i18n/dictionaries";
import { errorMessage } from "@/lib/api/client";

export type StaffTexts = Dictionary["staff"] & { passwordRules: Dictionary["passwordRules"] };

// Bỏ ký tự dễ nhầm (0/O, 1/l/I), ký tự đặc biệt dễ gõ trên điện thoại
const PASSWORD_CHARS = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%&*?+=";

// 12 ký tự ngẫu nhiên (crypto), sinh lại tới khi đạt luật mật khẩu
function randomPassword(length = 12): string {
  for (;;) {
    const bytes = crypto.getRandomValues(new Uint32Array(length));
    const password = Array.from(bytes, (n) => PASSWORD_CHARS[n % PASSWORD_CHARS.length]).join("");
    if (isPasswordValid(password)) return password;
  }
}

// Trạng thái gửi + câu lỗi chung cho mọi thao tác ghi; `submit` trả true khi thành công
export function useStaffSubmit(t: StaffTexts) {
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inFlight = useRef(false);

  async function submit(call: () => Promise<{ error?: unknown }>): Promise<boolean> {
    // Khóa ngay trong cùng tick (state chưa kịp cập nhật): endpoint này không có Idempotency-Key
    if (inFlight.current) return false;
    inFlight.current = true;
    setIsPending(true);
    setError(null);
    let message: string | null;
    try {
      const { error } = await call();
      // 422 ⇒ câu của backend
      const isInvalid = Array.isArray((error as { detail?: unknown } | undefined)?.detail);
      message = !error ? null : isInvalid ? errorMessage(error, t.errors.generic) : t.errors.generic;
    } catch {
      message = t.errors.network;
    }
    inFlight.current = false;
    setIsPending(false);
    setError(message);
    return message === null;
  }

  return { isPending, error, setError, submit };
}

type StaffFormProps = {
  t: StaffTexts;
  isPending: boolean;
  error: string | null;
  submitLabel: string;
  onSubmit: () => void;
  onCancel: () => void;
  canSubmit?: boolean;
  children: React.ReactNode;
};

// Khung form mở trong trang: lỗi + các ô + nút gửi/Hủy
export function StaffForm({
  t,
  isPending,
  error,
  submitLabel,
  onSubmit,
  onCancel,
  canSubmit = true,
  children,
}: StaffFormProps) {
  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className="flex max-w-xl flex-col gap-4"
    >
      {error && <Alert variant="error">{error}</Alert>}
      {children}
      <div className="flex flex-col gap-2 sm:flex-row">
        <Button type="submit" loading={isPending} disabled={!canSubmit}>
          {isPending ? t.saving : submitLabel}
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isPending}>
          {t.cancel}
        </Button>
      </div>
    </form>
  );
}

type PasswordFieldProps = {
  t: StaffTexts;
  id: string;
  value: string;
  onChange: (value: string, isGenerated?: boolean) => void;
  disabled?: boolean;
};

// Ô mật khẩu Admin đặt cho nhân viên + nút tạo ngẫu nhiên + luật
export function PasswordField({ t, id, value, onChange, disabled }: PasswordFieldProps) {
  return (
    <Field label={t.passwordLabel} htmlFor={id}>
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="flex-1">
          <PasswordInput
            id={id}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            disabled={disabled}
            showLabel={t.showPassword}
            hideLabel={t.hidePassword}
            autoComplete="new-password"
            maxLength={PASSWORD_MAX}
            aria-describedby={`${id}-rules ${id}-hint`}
            required
          />
        </div>
        <Button
          type="button"
          variant="secondary"
          disabled={disabled}
          onClick={() => onChange(randomPassword(), true)}
        >
          {t.generatePassword}
        </Button>
      </div>
      <PasswordRules id={`${id}-rules`} password={value} t={t.passwordRules} />
      <p id={`${id}-hint`} className="text-ui text-muted">
        {t.passwordHint}
      </p>
    </Field>
  );
}

export type FormProps = { t: StaffTexts; onCancel: () => void; onDone: () => void };

// Ô họ tên nhân viên
export function NameInput({ id, value, onChange, disabled }: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
}) {
  return (
    <Input
      id={id}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      autoComplete="off"
      maxLength={255}
      required
    />
  );
}
