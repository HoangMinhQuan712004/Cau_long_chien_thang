import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

type PhoneFormProps = {
  id: string;
  t: { label: string; placeholder: string; submit: string; submitting: string };
  value: string;
  onChange: (value: string) => void;
  isPending: boolean;
  onSubmit: (phone: string) => void;
  onEmpty: () => void;
  children?: React.ReactNode;
};

// Bước nhập SĐT để gửi mã OTP qua Zalo (quên mật khẩu, xác minh SĐT khi đặt sân)
export function PhoneForm({ id, t, value, onChange, isPending, onSubmit, onEmpty, children }: PhoneFormProps) {
  return (
    <form
      noValidate
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        const phone = value.trim();
        if (phone) onSubmit(phone);
        else onEmpty();
      }}
    >
      <Field label={t.label} htmlFor={id} required>
        <Input
          id={id}
          name="phone"
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          readOnly={isPending}
          placeholder={t.placeholder}
          required
        />
      </Field>
      <Button type="submit" block loading={isPending}>
        {isPending ? t.submitting : t.submit}
      </Button>
      {children}
    </form>
  );
}
