import { PASSWORD_MAX, PasswordRules, type PasswordRulesTexts } from "@/components/auth/password-rules";
import { Field } from "@/components/ui/field";
import { AlertCircleIcon, CheckCircleIcon } from "@/components/ui/icons";
import { PasswordInput } from "@/components/ui/password-input";
import { cn } from "@/lib/cn";

export type NewPasswordTexts = {
  passwordLabel: string;
  confirmLabel: string;
  showPassword: string;
  hidePassword: string;
  passwordMatch: string;
  passwordMismatch: string;
};

type Props = {
  password: string;
  confirm: string;
  onPassword: (value: string) => void;
  onConfirm: (value: string) => void;
  isPending: boolean;
  disabled?: boolean;
  /** Lỗi riêng của ô mật khẩu mới (vd trùng SĐT), hiện dưới danh sách quy tắc. */
  passwordError?: string | null;
  t: NewPasswordTexts;
  rules: PasswordRulesTexts;
};

// Nhập lại khớp nguyên văn (không trim)
export const isConfirmed = (password: string, confirm: string) => confirm !== "" && confirm === password;

/** Mật khẩu mới (kèm tick quy tắc) + nhập lại (báo khớp / chưa khớp): dùng ở Quên mật khẩu và Đổi mật khẩu lần đầu. */
export function NewPasswordFields({ password, confirm, onPassword, onConfirm, isPending, disabled, passwordError, t, rules }: Props) {
  const isMatch = isConfirmed(password, confirm);
  const isMismatch = confirm !== "" && !isMatch;
  const fieldProps = {
    readOnly: isPending,
    disabled,
    showLabel: t.showPassword,
    hideLabel: t.hidePassword,
    autoComplete: "new-password",
    maxLength: PASSWORD_MAX,
    required: true,
  };

  return (
    <>
      <Field label={t.passwordLabel} htmlFor="new-password" required>
        <PasswordInput
          id="new-password"
          value={password}
          onChange={(e) => onPassword(e.target.value)}
          aria-invalid={passwordError ? true : undefined}
          aria-describedby="new-password-rules new-password-error"
          {...fieldProps}
        />
        <PasswordRules id="new-password-rules" password={password} t={rules} />
        {passwordError ? (
          <p id="new-password-error" className="flex items-center gap-2 text-ui text-danger">
            <AlertCircleIcon size={16} className="shrink-0" />
            {passwordError}
          </p>
        ) : null}
      </Field>
      <Field label={t.confirmLabel} htmlFor="confirm-password" required>
        <PasswordInput
          id="confirm-password"
          value={confirm}
          onChange={(e) => onConfirm(e.target.value)}
          aria-invalid={isMismatch || undefined}
          aria-describedby="confirm-password-status"
          {...fieldProps}
        />
        <p
          id="confirm-password-status"
          aria-live="polite"
          className={cn("flex items-center gap-2 text-ui", isMatch ? "text-primary" : "text-danger")}
        >
          {isMatch && <CheckCircleIcon size={16} className="shrink-0" />}
          {isMismatch && <AlertCircleIcon size={16} className="shrink-0" />}
          {isMatch ? t.passwordMatch : isMismatch ? t.passwordMismatch : null}
        </p>
      </Field>
    </>
  );
}
