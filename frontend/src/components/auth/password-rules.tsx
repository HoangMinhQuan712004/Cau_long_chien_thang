import { CheckCircleIcon, CircleIcon } from "@/components/ui/icons";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";

// Luật mật khẩu MỚI, cùng định nghĩa với backend (không áp ở ô mật khẩu màn đăng nhập)
export const PASSWORD_MAX = 128;
const PASSWORD_MIN = 8;

type PasswordRule = "length" | "upper" | "digitOrSpecial";
const PASSWORD_RULES: PasswordRule[] = ["length", "upper", "digitOrSpecial"];

// In hoa kiểu Unicode (tính cả Đ, Ă)
const isUpper = (ch: string) => ch !== ch.toLowerCase() && ch === ch.toUpperCase();
// Chữ số, hoặc ký tự không phải chữ/số/khoảng trắng
const isDigitOrSpecial = (ch: string) => /\p{N}/u.test(ch) || !/[\p{L}\p{N}\s]/u.test(ch);

function checkPassword(password: string): Record<PasswordRule, boolean> {
  const chars = [...password];
  return {
    length: chars.length >= PASSWORD_MIN && chars.length <= PASSWORD_MAX,
    upper: chars.some(isUpper),
    digitOrSpecial: chars.some(isDigitOrSpecial),
  };
}

// Mật khẩu mới đạt đủ luật ⇒ mới cho bấm gửi
export const isPasswordValid = (password: string) =>
  Object.values(checkPassword(password)).every(Boolean);

export type PasswordRulesTexts = Dictionary["passwordRules"];

// Danh sách điều kiện dưới ô mật khẩu mới, tick xanh từng mục khi đạt
export function PasswordRules({ id, password, t }: { id: string; password: string; t: PasswordRulesTexts }) {
  const result = checkPassword(password);
  return (
    <div id={id} className="flex flex-col gap-1 text-ui">
      <p className="text-muted">{t.title}</p>
      <ul className="flex flex-col gap-1">
        {PASSWORD_RULES.map((rule) => {
          const isMet = result[rule];
          const Icon = isMet ? CheckCircleIcon : CircleIcon;
          return (
            <li
              key={rule}
              className={cn(
                "flex items-center gap-2 transition-colors motion-reduce:transition-none",
                isMet ? "text-primary" : "text-muted",
              )}
            >
              <Icon size={16} className="shrink-0" />
              <span>
                {t[rule]}
                <span className="sr-only">{` – ${isMet ? t.met : t.unmet}`}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
