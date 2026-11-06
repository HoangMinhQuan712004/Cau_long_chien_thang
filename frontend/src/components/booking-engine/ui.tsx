"use client";

import type { ReactNode } from "react";
import type { PaymentMethod, PaymentStatus } from "./types";

// Mảnh giao diện nhỏ dùng chung trong các hộp thoại đặt sân.
// Màu/khoảng cách theo token Tailwind chung; chỉnh theo Figma ở `globals.css`, không sửa từng chỗ.

export const STATUS_LABEL: Record<PaymentStatus, string> = {
  unpaid: "Chưa thanh toán",
  paid: "Đã thanh toán",
  uncollectible: "Không thu được",
  cancelled: "Đã hủy",
};

export const METHOD_LABEL: Record<PaymentMethod, string> = {
  cash: "Tiền mặt",
  transfer: "Chuyển khoản",
  online_transfer: "Chuyển khoản",
};

/** Màu nhãn trạng thái thanh toán (như khối trên lưới); dùng cho StatusBadge và nhãn lớn ở popup Thông tin booking. */
export const STATUS_TONE: Record<PaymentStatus, string> = {
  unpaid: "bg-blk-unpaid text-blk-unpaid-fg",
  paid: "bg-primary-softer text-primary",
  uncollectible: "bg-blk-bad text-blk-bad-fg",
  cancelled: "bg-danger-soft text-danger",
};

export function StatusBadge({ status }: { status: PaymentStatus }) {
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_TONE[status]}`}>{STATUS_LABEL[status]}</span>;
}

export function Kv({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1.5 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="border-b border-border pb-1 text-xs font-semibold tracking-wide text-muted uppercase">{title}</h3>
      {children}
    </section>
  );
}

export function SummaryBox({ children }: { children: ReactNode }) {
  return <div className="space-y-1 rounded-lg border border-border bg-background p-3 text-sm">{children}</div>;
}

export function ErrorBanner({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="rounded-md border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
      {children}
    </div>
  );
}

export function Hint({ children }: { children: ReactNode }) {
  return <p className="rounded-md bg-primary-softer p-2.5 text-xs text-muted">{children}</p>;
}

/** Nút công cụ màn Đặt sân: điện thoại cao 32px như Button primitive (vùng chạm ẩn 44px qua before), từ sm 36px. */
export const toolBtnCls =
  "relative inline-flex h-8 items-center justify-center rounded-lg border border-border bg-surface px-2.5 text-sm hover:bg-primary-softer focus-ring before:absolute before:inset-x-0 before:-inset-y-1.5 disabled:opacity-50 sm:h-9 sm:px-3";
/**
 * Chân hộp thoại "nổi" (hộp Đặt sân định kỳ): nền surface, viền trên mảnh như cũ, bóng xám trung tính hướng LÊN
 * tách khỏi nội dung đang cuộn (màu từ token foreground, không mã màu cứng). Truyền vào `footerClassName` của Modal.
 */
/** Cụm nút ở chân hộp thoại, các nút rộng bằng nhau (nơi dùng thêm số cột / bề rộng). */
export const btnRowCls = "grid w-full gap-2";
export const raisedFooterCls = "shadow-[0_-8px_20px_-12px_color-mix(in_srgb,var(--foreground)_18%,transparent)]";

// Ô nhập / nút trong các hộp thoại đặt sân (khu quản trị) – cùng cỡ, bo góc, viền focus với primitive (Input, Dropdown, Button).
// Ô: chữ 14px, cao 36px điện thoại / 38px từ sm – gọn như Input `compact` của quản trị (người dùng chốt; đánh đổi: Safari iOS
// có thể tự phóng to khi chạm ô chữ < 16px). Nút: cao 38px, vùng chạm ẩn ≥ 44px qua before.
/** Ô nhập nhiều dòng: như `inputCls` nhưng không đặt chiều cao tối thiểu (nơi dùng tự thêm `min-h-*`). */
export const textareaCls = "w-full rounded-lg border border-border-strong bg-surface px-3 py-1.5 text-sm focus-ring placeholder:text-subtle aria-invalid:border-danger";
export const inputCls = `${textareaCls} min-h-9 sm:min-h-9.5`;
const btnBase = "relative inline-flex min-h-9.5 items-center justify-center gap-1.5 rounded-lg px-4 py-1.5 text-sm focus-ring transition-colors before:absolute before:inset-x-0 before:-inset-y-1 disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none";
export const btnCls = `${btnBase} border border-border bg-surface enabled:hover:bg-primary-softer`;
export const btnPrimaryCls = `${btnBase} bg-primary font-semibold text-white enabled:hover:bg-primary-hover`;
export const btnDangerCls = `${btnBase} bg-danger font-semibold text-white enabled:hover:bg-danger/90`;
export const btnDangerOutlineCls = `${btnBase} mr-auto border border-danger text-danger enabled:hover:bg-danger/10`;
/** Dropdown (primitive) trong hộp thoại: cao bằng `inputCls` – 36px điện thoại / 38px từ sm (mặc định Dropdown 32px trên điện thoại). */
export const dropdownCls = "[&>button]:h-9 [&>button]:text-sm sm:[&>button]:h-9.5";

/** "S01 · Sân 1, S02 · Sân 2" */
export const resourceLabels = (codes: string[], names: string[]) => codes.map((c, i) => `${c} · ${names[i] ?? ""}`).join(", ");
