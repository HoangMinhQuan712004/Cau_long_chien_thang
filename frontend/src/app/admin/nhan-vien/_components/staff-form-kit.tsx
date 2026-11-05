import { useRef, useState } from "react";
import { isPasswordValid, PASSWORD_MAX, PasswordRules } from "@/components/auth/password-rules";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import type { Dictionary } from "@/i18n/dictionaries";
import { errorMessage } from "@/lib/api/client";

export type StaffTexts = Dictionary["staff"] & {
  passwordRules: Dictionary["passwordRules"];
  /** Câu tên thiết bị lấy từ Hồ sơ của tôi (adminProfile). */
  device: Pick<Dictionary["adminProfile"], "deviceOn" | "unknownBrowser" | "signedInAt">;
};

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

// Khung form trong hộp thoại: lỗi + các ô + nút Hủy / gửi
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
      className="flex flex-col gap-4"
    >
      {error && <Alert variant="error">{error}</Alert>}
      {children}
      {/* Cuối hộp: Hủy | nút gửi, rộng bằng nhau */}
      <div className="grid grid-cols-2 gap-2">
        <Button type="button" variant="secondary" block onClick={onCancel} disabled={isPending}>
          {t.cancel}
        </Button>
        <Button type="submit" block loading={isPending} disabled={!canSubmit}>
          {isPending ? t.saving : submitLabel}
        </Button>
      </div>
    </form>
  );
}

type PasswordFieldProps = {
  t: StaffTexts;
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
};

// Ô mật khẩu Admin đặt cho nhân viên + nút tạo ngẫu nhiên + luật
export function PasswordField({ t, id, value, onChange, disabled }: PasswordFieldProps) {
  return (
    <Field label={t.passwordLabel} htmlFor={id}>
      {/* Ô + nút cùng cao 36 / 38, căn giữa; điện thoại hẹp: nút xuống hàng dưới rộng hết */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex-1">
          <PasswordInput
            className="h-9! sm:h-9.5!"
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
          onClick={() => onChange(randomPassword())}
          className="h-9! w-full shrink-0 sm:h-9.5! sm:w-auto"
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

/** "Bình Đức" ⇒ "binh duc": bỏ dấu (cả đ / Đ), chữ thường; dùng cho ô tìm và xem trước tên đăng nhập. */
export const fold = (text: string) =>
  text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/gi, "d").toLowerCase().trim();

/** Như BE `_ascii_word`: bỏ dấu, chỉ giữ a-z0-9 (chữ thường). */
const asciiWord = (word: string) => fold(word).replace(/[^a-z0-9]/g, "");

const USERNAME_MAX = 30;
// Bảng chữ đuôi ngẫu nhiên (tạm, chờ BE báo): a-z + 2-9, bỏ ký tự dễ nhầm 0 / o / 1 / l / i
const SUFFIX_CHARS = "abcdefghjkmnpqrstuvwxyz23456789";
const SUFFIX_LENGTH = 4;

/** Đuôi 4 ký tự ngẫu nhiên (crypto), gửi kèm POST tạo nhân viên (`username_suffix`) để xem trước khớp tên thật. */
export function randomSuffix(): string {
  const bytes = crypto.getRandomValues(new Uint32Array(SUFFIX_LENGTH));
  return Array.from(bytes, (n) => SUFFIX_CHARS[n % SUFFIX_CHARS.length]).join("");
}

/**
 * Tên đăng nhập sẽ tạo: CẢ họ và tên viết liền không dấu (đ→d, a-z0-9) + "." + đuôi ngẫu nhiên, cả chuỗi ≤ 30 ký tự
 * ("Nguyễn Văn An" + "k7q2" ⇒ "nguyenvanan.k7q2"). Không có chữ hợp lệ ⇒ "nv.<đuôi>" (dự kiến, chờ BE chốt). Họ tên rỗng ⇒ null.
 */
export function usernamePreview(fullName: string, suffix: string): string | null {
  if (!fullName.trim()) return null;
  const base = fullName.split(/\s+/).map(asciiWord).join("").slice(0, USERNAME_MAX - suffix.length - 1);
  return `${base || "nv"}.${suffix}`;
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
      className="h-9! sm:h-9.5!"
    />
  );
}
