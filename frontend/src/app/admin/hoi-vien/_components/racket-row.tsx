"use client";

import { useId, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { fieldErrorId } from "@/components/ui/field";
import { IconButton } from "@/components/ui/icon-button";
import { EyeIcon, EyeOffIcon, PencilIcon, TrashIcon } from "@/components/ui/icons";
import { Input } from "@/components/ui/input";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import type { Racket } from "./use-rackets";

type Props = {
  racket: Racket;
  /** Vừa thêm ⇒ hiện bằng hiệu ứng trượt lên. */
  isNew?: boolean;
  /** Đổi tên; trả câu lỗi (vd trùng tên E-MEM-5) hoặc null khi xong. */
  onRename: (name: string) => Promise<string | null>;
  onToggle: () => Promise<void>;
  /** Mở hộp xác nhận xóa. */
  onDelete: () => void;
  t: Dictionary["members"]["rackets"];
};

const NAME = "min-w-0 flex-1 text-sm wrap-break-word";
const LINK = "-my-2 rounded-sm px-1 py-2 font-medium text-primary focus-ring hover:underline disabled:opacity-50";

/** Một dòng danh mục vợt: tên (vợt ẩn mờ + "Đã ẩn"), Sửa tên ngay trên dòng, Ẩn / Hiện, Xóa. */
export function RacketRow({ racket, isNew = false, onRename, onToggle, onDelete, t }: Props) {
  const id = useId();
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);

  // Lưu tên mới; không đổi gì ⇒ đóng ô sửa
  async function save() {
    const name = (draft ?? "").trim();
    if (!name || name === racket.name) return cancel();
    setIsPending(true);
    const message = await onRename(name);
    setIsPending(false);
    if (message) return setError(message);
    cancel();
  }

  function cancel() {
    setDraft(null);
    setError(null);
  }

  if (draft !== null) {
    return (
      <li className="flex flex-col gap-1.5 border-t px-1 py-3">
        <div className="flex items-center gap-2">
          <Input
            compact
            autoFocus
            aria-label={t.nameLabel}
            value={draft}
            maxLength={100}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void save();
              }
              if (e.key === "Escape") {
                e.preventDefault(); // chỉ thoát sửa, không đóng cả drawer
                cancel();
              }
            }}
            readOnly={isPending}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? fieldErrorId(id) : undefined}
          />
          <button type="button" className={LINK} onClick={() => void save()} disabled={isPending}>
            {isPending ? t.saving : t.save}
          </button>
          <button type="button" className={cn(LINK, "text-muted")} onClick={cancel} disabled={isPending}>
            {t.cancel}
          </button>
        </div>
        {error ? (
          <p id={fieldErrorId(id)} className="text-ui text-danger">
            {error}
          </p>
        ) : null}
      </li>
    );
  }

  return (
    <li className={cn("flex min-h-12 items-center gap-3 border-t px-1 py-2", isNew && `
      animate-slide-up
    `)}>
      <span className={cn(NAME, !racket.is_active && "text-subtle")}>{racket.name}</span>
      {racket.is_active ? null : <Badge variant="neutral">{t.hidden}</Badge>}
      <span className="flex shrink-0 items-center gap-1">
        <IconButton icon={<PencilIcon />} label={`${t.rename}: ${racket.name}`} tooltip={t.rename} onClick={() => setDraft(racket.name)} />
        <IconButton
          // Icon theo hành động sẽ làm: đang hiện ⇒ mắt gạch (ẩn đi)
          icon={racket.is_active ? <EyeOffIcon /> : <EyeIcon />}
          label={`${racket.is_active ? t.hide : t.show}: ${racket.name}`}
          tooltip={racket.is_active ? t.hide : t.show}
          disabled={isPending}
          onClick={async () => {
            setIsPending(true);
            await onToggle();
            setIsPending(false);
          }}
        />
        <IconButton icon={<TrashIcon />} label={`${t.delete}: ${racket.name}`} tooltip={t.delete} variant="danger" onClick={onDelete} />
      </span>
    </li>
  );
}
