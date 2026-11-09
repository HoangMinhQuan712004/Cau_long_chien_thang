"use client";

import { useEffect, useRef, useState } from "react";
import { useDragScroll } from "@/hooks/use-drag-scroll";
import { cn } from "@/lib/cn";
import { CHART_HEIGHT, dragScrollClass, millionAxisLabel } from "./chart-parts";
import { type Tip, TipOverlay, TipProvider } from "./chart-tip-layer";

type Props = {
  /** Số cột / ngày và bề rộng tối thiểu mỗi cái (px, đổi ra rem để màn lớn phóng theo): không đủ chỗ ⇒ cuộn ngang, không bóp nhỏ cột. */
  count: number;
  minStep: number;
  /** Mốc trục dọc (đồng), mốc cuối = đỉnh trục. */
  ticks: number[];
  /** Lề trên và chiều cao trục ngang của biểu đồ bên trong (px) ⇒ mốc trục dọc khớp lưới. */
  plotTop: number;
  axisHeight: number;
  /** Tên biểu đồ cho trình đọc màn hình. */
  label: string;
  /** Tên vùng cuộn khi biểu đồ rộng hơn khung (bàn phím: Tab vào rồi ← →). */
  scrollLabel: string;
  children: React.ReactNode;
};

/**
 * Khung biểu đồ cuộn ngang: trục dọc vẽ riêng bên trái (đứng yên khi cuộn), phần vẽ rộng tối thiểu
 * `count × minStep`; còn phần bị che ⇒ bóng mờ ở mép đó; máy tính bấm giữ chuột kéo để cuộn.
 * Hộp chú thích vẽ ở lớp ngoài khung cuộn (biểu đồ con đặt `TipBridge`) nên không bị cắt ở mép.
 */
export function ScrollChart({ count, minStep, ticks, plotTop, axisHeight, label, scrollLabel, children }: Props) {
  const { ref, edges, isScrollable, isDragging, scrollLeft, width } = useDragScroll<HTMLDivElement>();
  const top = ticks[ticks.length - 1] || 1;
  const [hoverTip, setHoverTip] = useState<Tip | null>(null);
  const [pinTip, setPinTip] = useState<Tip | null>(null);
  const [setters] = useState(() => ({ hover: setHoverTip, pin: setPinTip }));
  const frame = useRef<HTMLDivElement>(null);

  // Hộp do chạm tên sân (điện thoại) ⇒ chạm ra ngoài biểu đồ thì đóng
  useEffect(() => {
    if (!pinTip) return;
    const close = (e: PointerEvent) => {
      if (!frame.current?.contains(e.target as Node)) setPinTip(null);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [pinTip]);

  return (
    <div className={cn("flex w-full", CHART_HEIGHT)}>
      {/* Trục dọc: cùng lề trên / trục ngang với biểu đồ nên mốc nằm đúng đường lưới */}
      <div aria-hidden className="relative w-11 shrink-0 text-xs text-muted tabular-nums">
        <div className="absolute inset-x-0" style={{ top: plotTop, bottom: axisHeight }}>
          {ticks.map((v) => (
            <span
              key={v}
              className="absolute right-2 -translate-y-1/2 leading-none whitespace-nowrap"
              style={{ top: `${(1 - v / top) * 100}%` }}
            >
              {millionAxisLabel(v)}
            </span>
          ))}
        </div>
      </div>
      <div ref={frame} className="relative min-w-0 flex-1">
        <div
          ref={ref}
          tabIndex={isScrollable ? 0 : undefined}
          role={isScrollable ? "region" : undefined}
          aria-label={isScrollable ? scrollLabel : undefined}
          className={cn(
            "h-full overflow-x-auto overflow-y-hidden overscroll-x-contain rounded-sm focus-ring",
            dragScrollClass(isScrollable, isDragging),
          )}
        >
          <div role="img" aria-label={label} className="h-full" style={{ minWidth: `${(count * minStep) / 16}rem` }}>
            <TipProvider value={setters}>{children}</TipProvider>
          </div>
        </div>
        <TipOverlay tip={isDragging ? null : (hoverTip ?? pinTip)} scrollLeft={scrollLeft} frameWidth={width} />
        {/* Gợi ý còn phần ẩn: bóng mờ mép phải (chưa cuộn hết) / mép trái (đã cuộn) */}
        <div
          aria-hidden
          className={cn(
            `
              pointer-events-none absolute inset-y-0 left-0 w-6 bg-linear-to-r from-surface
              transition-opacity
            `,
            edges.left ? "opacity-100" : "opacity-0",
          )}
        />
        <div
          aria-hidden
          className={cn(
            `
              pointer-events-none absolute inset-y-0 right-0 w-10 bg-linear-to-l from-surface
              transition-opacity
            `,
            edges.right ? "opacity-100" : "opacity-0",
          )}
        />
      </div>
    </div>
  );
}
