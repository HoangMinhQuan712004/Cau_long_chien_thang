"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";
import { PageBanner } from "./page-banner";

// /hoi-vien/video-ky-luc (T-017 AC24): chỉ giao diện – bộ lọc kỳ đổi được nhưng không gọi API, trạng thái trống.

const PERIODS = ["Tuần", "Tháng", "Năm", "Mọi thời gian"] as const;

export function VideoScreen() {
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("Mọi thời gian");
  return (
    <>
      <PageBanner title="Video & kỷ lục" subtitle="Cú cầu nhanh nhất cụm sân · video chỉ đăng khi có kỷ lục mới" />
      <div className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Kỳ kỷ lục">
          {PERIODS.map((p) => (
            <button
              key={p}
              type="button"
              aria-pressed={period === p}
              onClick={() => setPeriod(p)}
              className={cn("h-9 rounded-full border px-4 text-sm font-medium focus-ring", period === p ? "border-primary-hover bg-primary-hover text-surface" : "border-border-strong bg-surface hover:bg-primary-softer")}
            >
              {p}
            </button>
          ))}
        </div>
        <div className="mt-6 grid place-items-center rounded-card bg-surface px-6 py-16 text-center shadow-card">
          <svg viewBox="0 0 48 48" className="size-12 text-subtle" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <rect x="5" y="12" width="28" height="24" rx="4" />
            <path d="m33 21 10-6v18l-10-6M6 6l36 36" />
          </svg>
          <h2 className="mt-4 text-lg font-bold">Chưa có video</h2>
          <p className="mt-1 max-w-sm text-sm text-muted">Video sẽ hiện ở đây khi cụm sân bắt đầu ghi nhận.</p>
        </div>
      </div>
    </>
  );
}
