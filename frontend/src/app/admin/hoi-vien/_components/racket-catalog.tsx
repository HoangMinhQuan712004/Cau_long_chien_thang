"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { InboxIcon, PlusIcon, SearchIcon, SearchXIcon } from "@/components/ui/icons";
import { Input } from "@/components/ui/input";
import { SidePanel } from "@/components/ui/side-panel";
import { Skeleton } from "@/components/ui/skeleton";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { memberFailure } from "@/lib/api/members";
import { toast } from "@/lib/feedback";
import { RacketAddForm } from "./racket-add-form";
import { RacketDelete } from "./racket-delete";
import { RacketRow } from "./racket-row";
import { type Racket, type RacketResult, useRackets } from "./use-rackets";

type Props = { onClose: () => void; t: Dictionary["members"] };

// Không phân biệt hoa thường / dấu cách thừa khi tìm
const norm = (s: string) => s.trim().replace(/\s+/g, " ").toLocaleLowerCase("vi");

/** Drawer "Danh mục vợt" (chỉ Admin): thêm, tìm, sửa tên ngay trên dòng, ẩn / hiện. Theo phong cách P5c. */
export function RacketCatalog({ onClose, t }: Props) {
  const r = t.rackets;
  const { state, add, update, remove, reload } = useRackets(true);
  const [toDelete, setToDelete] = useState<Racket | null>(null);
  const [q, setQ] = useState("");
  // Khối thêm: mở/đóng, tên điền sẵn (từ ô tìm), `seed` đổi ⇒ nạp lại form; vợt vừa thêm hiện có hiệu ứng
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [seed, setSeed] = useState({ n: 0, name: "" });
  const [newId, setNewId] = useState<number | null>(null);

  // Lỗi API (trùng tên E-MEM-5, không quyền…) ⇒ câu hiện dưới ô
  const messageOf = (result: Extract<RacketResult, { ok: false }>) =>
    memberFailure(result.error, result.response, t.errors).message;

  function openAdd(name = "") {
    setSeed((x) => ({ n: x.n + 1, name }));
    setIsAddOpen(true);
  }

  async function onAdd(name: string) {
    const result = await add(name);
    if (!result.ok) return messageOf(result);
    toast(r.toast.added, result.racket.name);
    setNewId(result.racket.id);
    setIsAddOpen(false);
    return null;
  }

  const items = state.status === "ok" ? state.items : [];
  const shown = q.trim() ? items.filter((x) => norm(x.name).includes(norm(q))) : items;
  const hiddenCount = items.filter((x) => !x.is_active).length;

  return (
    <SidePanel
      title={r.title}
      closeLabel={r.close}
      onClose={onClose}
      resizeLabel={r.resize}
      storageKey="hoi-vien.danh-muc-vot.rong"
      status={state.status}
      loadingLabel={t.form.loading}
      errorText={r.loadError}
      skeleton={<CatalogSkeleton />}
    >
      <div className="flex flex-col gap-5">
        <div className="flex flex-col gap-3">
          <div className="@container/racket-bar flex gap-2">
            <Input
              compact
              type="search"
              aria-label={r.searchLabel}
              placeholder={r.searchPlaceholder}
              value={q}
              maxLength={50}
              onChange={(e) => setQ(e.target.value)}
              startSlot={<SearchIcon size={18} />}
              onClear={() => setQ("")}
              clearLabel={r.clearSearch}
              // Có startSlot ⇒ className rơi vào khung bọc ngoài, cần flex-1 để ô giãn hết hàng
              className="min-w-0 flex-1"
            />
            <Button
              variant="secondary"
              className="shrink-0"
              aria-expanded={isAddOpen}
              onClick={() => (isAddOpen ? setIsAddOpen(false) : openAdd())}
            >
              <PlusIcon />
              {/* Hàng hẹp hơn 20rem ⇒ nút chỉ còn icon, chữ vẫn đọc được */}
              <span className="sr-only @xs/racket-bar:not-sr-only">{r.addOpen}</span>
            </Button>
          </div>
          <RacketAddForm key={seed.n} open={isAddOpen} initialName={seed.name} onSubmit={onAdd} onCancel={() => setIsAddOpen(false)} t={r} />
          <p className="text-ui text-muted tabular-nums" aria-live="polite">
            {r.summary.replace("{n}", String(items.length)).replace("{hidden}", String(hiddenCount))}
          </p>
        </div>

        {shown.length === 0 ? (
          q.trim() ? (
            <EmptyState
              icon={<SearchXIcon size={24} />}
              title={r.emptySearch.title}
              description={r.emptySearch.text.replace("{q}", q.trim())}
              // Tìm không ra ⇒ thêm luôn tên đang gõ
              action={
                <Button variant="secondary" onClick={() => openAdd(q.trim())}>
                  <PlusIcon />
                  {r.addFromSearch.replace("{q}", q.trim())}
                </Button>
              }
            />
          ) : (
            <EmptyState icon={<InboxIcon size={24} />} title={r.empty.title} description={r.empty.text} />
          )
        ) : (
          <ul aria-label={r.title} className="-mt-2 border-b">
            {shown.map((racket) => (
              <RacketRow
                key={racket.id}
                racket={racket}
                isNew={racket.id === newId}
                t={r}
                onRename={async (name) => {
                  const result = await update(racket.id, { name });
                  if (!result.ok) return messageOf(result);
                  toast(r.toast.renamed, result.racket.name);
                  return null;
                }}
                onToggle={async () => {
                  const result = await update(racket.id, { is_active: !racket.is_active });
                  if (!result.ok) return toast(messageOf(result), undefined, "error");
                  toast(result.racket.is_active ? r.toast.shown : r.toast.hidden, result.racket.name);
                }}
                onDelete={() => setToDelete(racket)}
              />
            ))}
          </ul>
        )}
      </div>
      {toDelete ? (
        <RacketDelete racket={toDelete} remove={remove} reload={reload} onClose={() => setToDelete(null)} t={t} />
      ) : null}
    </SidePanel>
  );
}

// Khung tải đúng hình: hàng tìm, vài dòng vợt
function CatalogSkeleton() {
  return (
    <div className="flex flex-col gap-5">
      <Skeleton className="h-11 rounded-lg sm:h-10.5" />
      <Skeleton className="h-11 rounded-lg sm:h-10.5" />
      <div className="flex flex-col">
        {["w-1/2", "w-2/3", "w-2/5", "w-3/5"].map((w) => (
          <div key={w} className="flex items-center justify-between gap-4 border-t py-4">
            <Skeleton className={cn("h-4", w)} />
            <Skeleton className="h-4 w-24" />
          </div>
        ))}
      </div>
    </div>
  );
}
