"use client";

import type { ReactNode } from "react";
import type { PaymentMethod, PaymentStatus } from "./types";

// Mảnh giao diện nhỏ dùng chung trong các hộp thoại đặt sân.
// Màu/khoảng cách theo token Tailwind chung; chỉnh theo Figma ở `globals.css`, không sửa từng chỗ.

export const STATUS_LABEL: Record<PaymentStatus, string> = {
  unpaid: "Chưa thanh toán",
  paid: "Đã thanh toán",
  uncollectible: "Không thu được",
};

export const METHOD_LABEL: Record<PaymentMethod, string> = {
  cash: "Tiền mặt",
  transfer: "Chuyển khoản",
  online_transfer: "Chuyển khoản",
};

const BADGE_STYLE: Record<PaymentStatus, string> = {
  unpaid: "bg-blk-unpaid text-blk-unpaid-fg",
  paid: "bg-free text-success",
  uncollectible: "bg-blk-bad text-blk-bad-fg",
};

export function StatusBadge({ status }: { status: PaymentStatus }) {
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${BADGE_STYLE[status]}`}>{STATUS_LABEL[status]}</span>;
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
  return <p className="rounded-md bg-free p-2.5 text-xs text-muted">{children}</p>;
}

export const inputCls = "w-full rounded-md border border-border bg-background px-3 py-2 text-sm";
export const btnCls = "rounded-md border border-border px-4 py-2 text-sm disabled:opacity-60";
export const btnPrimaryCls = "rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-fg disabled:opacity-60";
export const btnDangerCls = "rounded-md bg-danger px-4 py-2 text-sm font-medium text-primary-fg disabled:opacity-60";
export const btnDangerOutlineCls = "mr-auto rounded-md border border-danger px-4 py-2 text-sm text-danger disabled:opacity-60";

/** "S01 · Sân 1, S02 · Sân 2" */
export const resourceLabels = (codes: string[], names: string[]) => codes.map((c, i) => `${c} · ${names[i] ?? ""}`).join(", ");
