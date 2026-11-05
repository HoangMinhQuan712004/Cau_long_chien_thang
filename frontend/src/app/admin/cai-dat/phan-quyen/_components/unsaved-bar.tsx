"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

// Thanh dính đáy khi có thay đổi chưa lưu (2 tab Phân quyền & menu).
// data-bottom-bar: toast trên điện thoại tự đẩy lên trên, không che nút.

type Props = {
  t: { dirty: string; cancel: string; save: string; saving: string };
  isSaving: boolean;
  onCancel: () => void;
  onSave: () => void;
};

export function UnsavedBar({ t, isSaving, onCancel, onSave }: Props) {
  return (
    <div data-bottom-bar className={cn(`
      sticky bottom-0 z-10 -mx-4 flex flex-wrap items-center justify-between gap-3 border-t
      bg-surface px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] shadow-card
      lg:-mx-6 lg:px-6
    `)}>
      <p className="basis-full text-sm font-semibold sm:basis-auto">{t.dirty}</p>
      <div className={cn(`
        flex w-full justify-end gap-2
        sm:w-auto
        [&>button]:h-11 [&>button]:flex-1
        sm:[&>button]:h-9.5 sm:[&>button]:flex-none
      `)}>
        <Button variant="secondary" onClick={onCancel} disabled={isSaving}>{t.cancel}</Button>
        <Button onClick={onSave} loading={isSaving}>{isSaving ? t.saving : t.save}</Button>
      </div>
    </div>
  );
}
