"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, fieldErrorId } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import type { Dictionary } from "@/i18n/dictionaries";

type Props = {
  /** Đang mở (đóng vẫn giữ trong DOM để thu lại mượt, nhưng `inert`). */
  open: boolean;
  /** Tên điền sẵn (vd chữ đang tìm); đổi `key` ở chỗ gọi để nạp lại. */
  initialName: string;
  /** Thêm vợt; trả câu lỗi (vd trùng tên E-MEM-5) hoặc null khi xong. */
  onSubmit: (name: string) => Promise<string | null>;
  onCancel: () => void;
  t: Dictionary["members"]["rackets"];
};

/** Khối thêm vợt mở ngay dưới hàng tìm: ô tên (tự focus), Lưu, Hủy; Esc chỉ đóng khối, không đóng ngăn. */
export function RacketAddForm({ open, initialName, onSubmit, onCancel, t }: Props) {
  const id = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState(initialName);
  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);

  // Mở ⇒ đưa con trỏ vào ô tên
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  async function save(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const value = name.trim();
    if (!value || isPending) return;
    setIsPending(true);
    setError(null);
    const message = await onSubmit(value);
    setIsPending(false);
    if (message) return setError(message);
    setName("");
  }

  return (
    <div id={`${id}-panel`} data-open={open} inert={!open} className="collapsible">
      <div>
        <form onSubmit={save} noValidate className="flex flex-col gap-3 pb-2">
          <Field label={t.addLabel} htmlFor={`${id}-name`} error={error ?? undefined}>
            <Input
              compact
              ref={inputRef}
              id={`${id}-name`}
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.preventDefault(); // chỉ đóng khối thêm, không đóng cả ngăn
                  onCancel();
                }
              }}
              placeholder={t.addPlaceholder}
              maxLength={100}
              autoComplete="off"
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? fieldErrorId(`${id}-name`) : undefined}
            />
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onCancel} disabled={isPending}>
              {t.addCancel}
            </Button>
            <Button type="submit" loading={isPending} disabled={!name.trim()}>
              {isPending ? t.adding : t.addSave}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
