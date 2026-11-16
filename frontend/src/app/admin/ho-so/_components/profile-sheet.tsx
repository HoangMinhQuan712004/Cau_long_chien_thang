"use client";

import { createContext, useContext, useEffect, useId, useRef, useState } from "react";
import { ChevronLeftIcon, ChevronRightIcon, CloseIcon } from "@/components/ui/icons";
import { cn } from "@/lib/cn";

// Dòng "›" trong thẻ hồ sơ + "bảng con" kiểu Meta: đầu bảng có ‹ quay lại, × đóng, dòng nhỏ "Tên · Hồ sơ", tiêu đề lớn, mô tả.
// Modal/BottomSheet của ui/ có đầu bảng cố định (chỉ tiêu đề) nên bảng này dựng trên <dialog> gốc theo cùng cách:
// cao theo nội dung: điện thoại = bám đáy, tối đa 85dvh (có tay nắm); từ sm = hộp giữa màn rộng ~512px, tối đa 80dvh.
// Vượt thì chỉ thân bảng cuộn, đầu bảng đứng yên. Esc/×/‹ đóng, focus về dòng vừa bấm.

// Nút ‹ / × đầu bảng: vùng chạm 44px, icon 20px
const HEAD_BTN = "grid size-11 place-items-center rounded-full text-muted transition-colors hover:bg-primary-softer hover:text-foreground focus-ring";

/** Nhóm nút form trong màn Hồ sơ: điện thoại 44px chia đôi, từ sm 38px (= ô nhập); selector con thắng cỡ gọn mặc định của Button. */
export const FORM_ACTIONS = cn(
  "flex gap-2 [&>button]:h-11 [&>button]:flex-1 [&>button]:text-ui",
  "sm:[&>button]:h-9.5 sm:[&>button]:flex-none",
);

const CloseCtx = createContext<() => void>(() => {});

/** Nội dung trong bảng gọi để tự đóng bảng (vd đổi mật khẩu xong). */
export const useCloseSheet = () => useContext(CloseCtx);

type Props = {
  icon: React.ReactNode;
  label: string;
  sub?: string | null;
  /** Dòng nhỏ trên tiêu đề bảng ("Chủ sân · Hồ sơ"). */
  kicker: string;
  description: string;
  backLabel: string;
  closeLabel: string;
  children: React.ReactNode;
};

export function ProfileRow({ icon, label, sub, kicker, description, backLabel, closeLabel, children }: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const close = () => ref.current?.close(); // sự kiện close của <dialog> sẽ đặt lại state + trả focus

  useEffect(() => {
    const el = ref.current;
    if (el && isOpen && !el.open) el.showModal();
  }, [isOpen]);

  return (
    <div>
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        aria-haspopup="dialog"
        className={cn(
          // Vùng hover nằm trong lề, thẳng mép với đường kẻ; không nền/bóng khi không tương tác
          "flex min-h-14 w-full items-center gap-3 rounded-lg py-3 pr-1 text-left",
          "focus-ring transition-colors hover:bg-primary-softer active:bg-primary-soft/60",
        )}
      >
        <span aria-hidden className={cn(`
          grid size-9 shrink-0 place-items-center rounded-full bg-primary-softer text-primary
        `)}>{icon}</span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="text-sm font-semibold">{label}</span>
          {sub ? <span className="text-ui wrap-anywhere text-muted">{sub}</span> : null}
        </span>
        <ChevronRightIcon size={18} className="shrink-0 text-muted" />
      </button>

      <dialog
        ref={ref}
        aria-labelledby={titleId}
        // Chỉ nhận "close" của chính bảng này: React truyền close của hộp con (ConfirmDialog) lên đây theo cây React
        onClose={(e) => e.target === e.currentTarget && setIsOpen(false)}
        onClick={(e) => e.target === e.currentTarget && close()} // chỉ bấm vùng tối của chính bảng này
        className={cn(
          `
            m-0 mt-auto max-h-[85dvh] w-full max-w-none overflow-hidden rounded-t-[20px] border-0
            bg-surface p-0
          `,
          "animate-slide-up text-foreground shadow-xl backdrop:animate-fade-in backdrop:bg-black/45",
          `
            sm:m-auto sm:max-h-[80dvh] sm:w-[calc(100vw-2rem)] sm:max-w-lg sm:animate-scale-in
            sm:rounded-2xl
          `,
        )}
      >
        {isOpen ? (
          <div className={cn(`
            flex max-h-[85dvh] flex-col pb-[env(safe-area-inset-bottom)]
            sm:max-h-[80dvh]
          `)}>
            <div aria-hidden className={cn(`
              mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-border-strong
              sm:hidden
            `)} />
            <div className="flex shrink-0 items-center justify-between px-3 pt-2 sm:pt-3">
              <button type="button" aria-label={backLabel} title={backLabel} onClick={close} className={HEAD_BTN}><ChevronLeftIcon size={20} /></button>
              <button type="button" aria-label={closeLabel} title={closeLabel} onClick={close} className={HEAD_BTN}><CloseIcon size={20} /></button>
            </div>
            <div className="flex shrink-0 flex-col gap-1 px-5 pb-4 sm:px-6">
              <p className={cn(`truncate text-ui text-muted [@media(max-height:30rem)]:hidden`)}>{kicker}</p>
              <h2 id={titleId} className="text-xl font-bold">{label}</h2>
              {/* Màn thấp (điện thoại xoay ngang): bỏ dòng phụ để chừa chỗ cho nội dung */}
              <p className="text-ui text-muted [@media(max-height:30rem)]:hidden">{description}</p>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-8 sm:px-6">
              <CloseCtx.Provider value={close}>{children}</CloseCtx.Provider>
            </div>
          </div>
        ) : null}
      </dialog>
    </div>
  );
}
