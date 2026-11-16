"use client";

import { useMemo, useState } from "react";
import { UnsavedGuard } from "@/components/admin/unsaved-guard";
import { ConfirmDialog } from "@/components/play-rooms/confirm-dialog";
import { Button } from "@/components/ui/button";
import { ResetIcon } from "@/components/ui/icons";
import type { Dictionary } from "@/i18n/dictionaries";
import { api, errorMessage } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { fill } from "@/lib/format";
import { toast } from "@/lib/feedback";
import { RolesMatrix } from "./roles-matrix";
import { UnsavedBar } from "./unsaved-bar";

// Chỉnh quyền của Nhân viên (Admin luôn toàn quyền): sửa cục bộ rồi "Lưu thay đổi"; bỏ hết quyền ⇒ hỏi; rời trang khi chưa lưu ⇒ hỏi (UnsavedGuard).

type RolesData = components["schemas"]["RolesOut"];
type T = Dictionary["roles"];
// Nút chữ nhỏ (Mở tất cả / Thu gọn tất cả): vùng chạm 44px
const LINK_BTN = "min-h-11 rounded-md px-2 text-ui font-semibold text-primary hover:underline focus-ring disabled:text-muted disabled:no-underline";

const toDraft = (d: RolesData): ReadonlySet<string> => new Set(d.roles.staff);
const same = (a: ReadonlySet<string>, b: ReadonlySet<string>) => a.size === b.size && [...a].every((x) => b.has(x));

export function RolesEditor({ initial, t }: { initial: RolesData; t: T }) {
  const [saved, setSaved] = useState(() => toDraft(initial));
  const [draft, setDraft] = useState(saved);
  const [isSaving, setIsSaving] = useState(false);
  const [askEmpty, setAskEmpty] = useState(false);
  // Mặc định của vai Nhân viên (so theo TẬP HỢP, thứ tự không quan trọng)
  const [defaults, setDefaults] = useState<ReadonlySet<string>>(() => new Set(initial.defaults.staff));
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set());
  const isDirty = useMemo(() => !same(draft, saved), [draft, saved]);
  const isDefault = useMemo(() => same(draft, defaults), [draft, defaults]);
  const total = initial.groups.reduce((n, g) => n + g.perms.length, 0);
  const onCollapse = (key: string) =>
    setCollapsed((c) => {
      const next = new Set(c);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const update = (fn: (s: Set<string>) => void) =>
    setDraft((d) => {
      const next = new Set(d);
      fn(next);
      return next;
    });
  const onToggle = (perm: string) => update((s) => (s.has(perm) ? s.delete(perm) : s.add(perm)));
  const onGroup = (perms: string[], on: boolean) => update((s) => perms.forEach((p) => (on ? s.add(p) : s.delete(p))));

  /** PUT quyền Nhân viên; trả lỗi (chuỗi) để hiện trong hộp xác nhận, hoặc null khi xong. */
  async function save(): Promise<string | null> {
    setIsSaving(true);
    try {
      const { data, error } = await api.PUT("/api/v1/admin/roles/{role}", { params: { path: { role: "staff" } }, body: { perms: [...draft] } });
      if (!data) return errorMessage(error, t.unavailable);
      const next = toDraft(data);
      setDefaults(new Set(data.defaults.staff));
      setSaved(next);
      setDraft(next);
      toast(t.saved, t.savedSub);
      return null;
    } catch {
      return t.network;
    } finally {
      setIsSaving(false);
    }
  }

  async function onSave() {
    if (draft.size === 0) return setAskEmpty(true);
    const err = await save();
    if (err) toast(err, undefined, "error");
  }

  return (
    // Nội dung tab "Phân quyền nhân viên" (khung + tiêu đề trang ở page.tsx)
    <div className="flex flex-col gap-4">
      {/* Dòng đếm + Mở/Thu gọn tất cả + Về mặc định (tiêu đề + mô tả trang đã có ở page.tsx) */}
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <p className="text-sm font-semibold tabular-nums">{fill(t.enabledCount, { n: draft.size, total })}</p>
        <div className="flex flex-wrap items-center gap-1">
          <button type="button" onClick={() => setCollapsed(new Set())} disabled={collapsed.size === 0} className={LINK_BTN}>{t.expandAll}</button>
          <button type="button" onClick={() => setCollapsed(new Set(initial.groups.map((g) => g.key)))} disabled={collapsed.size === initial.groups.length} className={LINK_BTN}>{t.collapseAll}</button>
          <Button variant="secondary" onClick={() => setDraft(new Set(defaults))} disabled={isDefault || isSaving}>
            <ResetIcon />
            {t.reset}
          </Button>
        </div>
      </div>
      <RolesMatrix groups={initial.groups} draft={draft} collapsed={collapsed} onToggle={onToggle} onGroup={onGroup} onCollapse={onCollapse} t={t} />

      {isDirty ? (
        <UnsavedBar t={t} isSaving={isSaving} onCancel={() => setDraft(saved)} onSave={() => void onSave()} />
      ) : null}

      {askEmpty ? (
        <ConfirmDialog
          danger
          title={t.emptyTitle}
          body={t.emptyBody}
          cancelLabel={t.cancel}
          confirmLabel={t.emptyConfirm}
          onClose={() => setAskEmpty(false)}
          onConfirm={async () => {
            const err = await save();
            if (!err) setAskEmpty(false);
            return err;
          }}
        />
      ) : null}
      <UnsavedGuard dirty={isDirty} />
    </div>
  );
}
