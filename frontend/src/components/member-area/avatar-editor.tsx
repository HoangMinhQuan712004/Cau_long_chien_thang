"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { errorText, type WriteResult } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";
import { CropDialog } from "./crop-dialog";
import type { Crop } from "./types";

const MAX_FILE = 5 * 1024 * 1024;
const FILE_TYPES = ["image/jpeg", "image/png", "image/webp"];

// Nút nhìn 32 / 34px, vùng chạm mở rộng vô hình ≈ 44px
const TOUCH = "relative before:absolute before:-inset-x-0.5 before:-inset-y-2";

// Chữ mặc định là ảnh đại diện (khu hội viên, Hồ sơ quản trị); màn logo truyền `texts` riêng
const DEFAULT_TEXTS = {
  change: "Đổi ảnh đại diện",
  removeItem: "Xóa ảnh",
  cropTitle: "Cắt ảnh đại diện",
  saved: "Đã cập nhật ảnh đại diện",
  removed: "Đã xóa ảnh đại diện",
  confirmTitle: "Xóa ảnh đại diện?",
  confirmBody: "Ảnh sẽ được thay bằng chữ cái đầu tên của bạn ở mọi nơi.",
  confirmRemove: "Xóa ảnh",
};

type Props = {
  /** Đang có ảnh ⇒ menu có thêm "Xóa ảnh". */
  hasImage: boolean;
  /** Gửi ảnh + vùng cắt tới API của từng khu (hội viên / quản trị). */
  upload: (file: File, crop: Crop) => Promise<WriteResult<{ avatar_url: string }>>;
  remove: () => Promise<WriteResult<unknown>>;
  /** Lưu / xóa xong: URL mới, `null` khi đã xóa. */
  onChange: (url: string | null) => void;
  /** Khung xem trước khi cắt: tròn (mặc định) / vuông (logo). */
  shape?: "round" | "square";
  /** "menu": nút máy ảnh ở góc mở menu (mặc định); "buttons": hai nút chữ sau ảnh (màn logo). */
  actions?: "menu" | "buttons";
  texts?: Partial<typeof DEFAULT_TEXTS>;
  className?: string;
  /** Phần hiển thị ảnh: mỗi khu tự vẽ (cỡ, màu, chữ cái khi chưa có ảnh). */
  children: React.ReactNode;
};

/** Đổi ảnh đại diện dùng chung: nút máy ảnh ở góc mở menu Tải ảnh lên / Xóa ảnh, kiểm tệp, hộp cắt, xác nhận xóa. */
export function AvatarEditor({ hasImage, upload, remove, onChange, shape, actions = "menu", texts, className, children }: Props) {
  const t = { ...DEFAULT_TEXTS, ...texts };
  const [menu, setMenu] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  function pick(f: File | undefined) {
    // Menu 📷 luôn đóng khi đã có tệp (kể cả khi tệp được đưa vào ô chọn tệp mà không bấm mục menu)
    setMenu(false);
    if (!f) return;
    if (!FILE_TYPES.includes(f.type) || f.size > MAX_FILE) {
      toast("Ảnh phải là JPG, PNG hoặc WebP, tối đa 5 MB.", undefined, "error");
      return;
    }
    setFile(f);
  }

  async function confirmRemove() {
    if (busy) return;
    setBusy(true);
    setMenu(false);
    const res = await remove();
    setBusy(false);
    if (!res.ok) {
      toast(errorText(res.error), undefined, "error");
      return;
    }
    onChange(null);
    setConfirmDelete(false);
    toast(t.removed);
  }

  return (
    <>
      <div className={cn("relative shrink-0", className)} onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setMenu(false)}>
        {children}
        {actions === "buttons" ? (
          <div className="flex shrink-0 gap-2">
            <Button type="button" variant="secondary" onClick={() => input.current?.click()} className={TOUCH}>
              {t.change}
            </Button>
            {hasImage ? (
              <Button type="button" variant="ghost" onClick={() => setConfirmDelete(true)} className={TOUCH}>
                {t.removeItem}
              </Button>
            ) : null}
          </div>
        ) : (
          <>
        <button
          type="button"
          aria-label={t.change}
          aria-haspopup="menu"
          aria-expanded={menu}
          onClick={() => setMenu((o) => !o)}
          onKeyDown={(e) => e.key === "Escape" && setMenu(false)}
          // Nhìn 32px, vùng chạm mở rộng vô hình ≈ 44px
          className="absolute right-0 bottom-0 grid size-8 place-items-center rounded-full bg-surface text-foreground shadow-card before:absolute before:-inset-1.5 hover:bg-primary-softer focus-ring"
        >
          <svg viewBox="0 0 20 20" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
            <path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h1.6l1-1.5h5.8l1 1.5h1.6A1.5 1.5 0 0 1 17 7.5v7a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 14.5z" />
            <circle cx="10" cy="10.5" r="2.6" />
          </svg>
        </button>
        {menu ? (
          <div role="menu" className="absolute top-full left-0 z-20 mt-2 w-44 rounded-card bg-surface p-1.5 text-sm text-foreground shadow-card ring-1 ring-border">
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenu(false);
                input.current?.click();
              }}
              className="w-full rounded-lg px-3 py-2 text-left hover:bg-primary-softer focus-ring"
            >
              Tải ảnh lên
            </button>
            {hasImage ? (
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenu(false);
                  setConfirmDelete(true);
                }}
                className="w-full rounded-lg px-3 py-2 text-left hover:bg-primary-softer hover:text-danger focus-ring"
              >
                {t.removeItem}
              </button>
            ) : null}
          </div>
        ) : null}
          </>
        )}
        <input
          ref={input}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={(e) => {
            pick(e.target.files?.[0]);
            e.target.value = ""; // chọn lại cùng tệp vẫn nhận
          }}
        />
      </div>

      {file ? (
        <CropDialog
          file={file}
          upload={upload}
          shape={shape}
          title={t.cropTitle}
          savedText={t.saved}
          onClose={() => setFile(null)}
          onSaved={(url) => {
            onChange(url);
            setMenu(false);
            setFile(null);
          }}
        />
      ) : null}
      <Modal
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t.confirmTitle}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmDelete(false)} disabled={busy}>
              Hủy
            </Button>
            <Button onClick={() => void confirmRemove()} loading={busy}>
              {busy ? "Đang xóa…" : t.confirmRemove}
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">{t.confirmBody}</p>
      </Modal>
    </>
  );
}
