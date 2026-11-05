"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { UnsavedGuard } from "@/components/admin/unsaved-guard";
import { Button } from "@/components/ui/button";
import { ResetIcon } from "@/components/ui/icons";
import type { Dictionary } from "@/i18n/dictionaries";
import { api, errorMessage } from "@/lib/api/client";
import { toast } from "@/lib/feedback";
import { NAV_ICONS } from "../../../_components/admin-sidebar";
import { DEFAULT_MENU_ORDER, type MenuKey, sortNav } from "../../../_components/forbidden";
import { SortableList } from "./sortable-list";
import { UnsavedBar } from "./unsaved-bar";

// Tùy chỉnh menu trái (thứ tự CHUNG cho mọi tài khoản): sửa nháp rồi Lưu; nháp trùng mặc định ⇒ DELETE, còn lại ⇒ PUT.

type T = Dictionary["menuOrder"];
const same = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((k, i) => k === b[i]);

export function MenuOrderEditor({ initial, labels, t }: { initial: string[]; labels: Record<MenuKey, string>; t: T }) {
  const router = useRouter();
  // Thứ tự đã lưu (đủ mọi mục; khóa lạ / thiếu được sortNav xếp lại)
  const [saved, setSaved] = useState<MenuKey[]>(() => sortNav(initial).map((n) => n.key));
  const [draft, setDraft] = useState<MenuKey[]>(saved);
  const [isSaving, setIsSaving] = useState(false);
  const isDirty = !same(draft, saved);

  const move = (from: number, to: number) =>
    setDraft((d) => {
      const next = [...d];
      const [item] = next.splice(from, 1);
      next.splice(to, 0, item);
      return next;
    });

  async function save() {
    setIsSaving(true);
    try {
      const toDefault = same(draft, DEFAULT_MENU_ORDER);
      const { error, response } = toDefault
        ? await api.DELETE("/api/v1/admin/menu-order")
        : await api.PUT("/api/v1/admin/menu-order", { body: { order: draft } });
      if (!response.ok) return toast(errorMessage(error, t.unavailable), undefined, "error");
      setSaved(draft);
      toast(t.saved, t.savedSub);
      router.refresh(); // sidebar lấy thứ tự mới ngay
    } catch {
      toast(t.network, undefined, "error");
    } finally {
      setIsSaving(false);
    }
  }

  const items = draft.map((key) => {
    const Icon = NAV_ICONS[key];
    return { key, label: labels[key], icon: <Icon className="size-4" /> };
  });

  return (
    // Nội dung tab "Thứ tự menu" (khung + tiêu đề trang ở page.tsx)
    <div className="flex flex-col gap-4">
      {/* Mô tả đã có dưới tiêu đề trang; ở đây chỉ còn nút Về mặc định, căn phải */}
      <div className="flex justify-end">
        <Button variant="secondary" onClick={() => setDraft([...DEFAULT_MENU_ORDER])} disabled={same(draft, DEFAULT_MENU_ORDER) || isSaving}>
          <ResetIcon />
          {t.reset}
        </Button>
      </div>

      <div className="overflow-hidden rounded-card bg-surface shadow-card">
        <SortableList items={items} onMove={move} t={t} />
      </div>

      {isDirty ? (
        <UnsavedBar t={t} isSaving={isSaving} onCancel={() => setDraft(saved)} onSave={() => void save()} />
      ) : null}
      <UnsavedGuard dirty={isDirty} />
    </div>
  );
}
