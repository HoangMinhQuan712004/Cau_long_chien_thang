"use client";

import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useActiveTooltipCoordinate, useActiveTooltipDataPoints, useIsTooltipActive } from "recharts";
import { ChartTip } from "./chart-parts";

// Hộp chú thích của biểu đồ cuộn ngang: vẽ ở lớp ngoài khung cuộn (không bị cắt ở mép khung),
// nguồn là điểm / cột recharts đang rê, hoặc nhãn trục (rê / chạm tên sân)

/** Vị trí theo tọa độ phần vẽ (chưa trừ phần đã cuộn). */
export type Tip = { x: number; y: number; text: string };

type SetTip = (tip: Tip | null) => void;
/** 2 nguồn riêng: `hover` = recharts đang rê điểm / cột; `pin` = rê / chạm tên sân. Hiện `hover` trước. */
const TipContext = createContext<{ hover: SetTip; pin: SetTip }>({ hover: () => {}, pin: () => {} });
export const TipProvider = TipContext.Provider;
/** Hiện / ẩn hộp chú thích từ nhãn trục ngang (rê / chạm tên sân). */
export const usePinTip = () => useContext(TipContext).pin;

/**
 * Đặt trong biểu đồ recharts (cạnh `<Tooltip content={() => null} />`): điểm / cột đang rê ⇒ hộp chú thích.
 */
export function TipBridge<Row>({ text }: { text: (row: Row) => string }) {
  const setTip = useContext(TipContext).hover;
  const isActive = useIsTooltipActive();
  const coord = useActiveTooltipCoordinate();
  const row = useActiveTooltipDataPoints<Row>()?.[0];
  const label = isActive && row ? text(row) : null;
  const x = coord?.x;
  const y = coord?.y;

  useEffect(() => {
    setTip(label && x !== undefined && y !== undefined ? { x, y, text: label } : null);
  }, [label, x, y, setTip]);

  return null;
}

/** Lớp hộp chú thích: trừ phần đã cuộn, giữ trọn trong khung (sát mép thì dịch vào), nằm trên điểm. */
export function TipOverlay({ tip, scrollLeft, frameWidth }: { tip: Tip | null; scrollLeft: number; frameWidth: number }) {
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    if (box.current) setSize({ w: box.current.offsetWidth, h: box.current.offsetHeight });
  }, [tip?.text]);
  if (!tip) return null;

  const left = Math.min(Math.max(tip.x - scrollLeft - size.w / 2, 0), Math.max(frameWidth - size.w, 0));
  // Ưu tiên phía trên điểm; sát đỉnh thì xuống dưới
  const top = tip.y - size.h - 10 >= 0 ? tip.y - size.h - 10 : tip.y + 14;
  return (
    <div ref={box} aria-hidden className="pointer-events-none absolute z-10 w-max" style={{ left, top }}>
      <ChartTip text={tip.text} />
    </div>
  );
}
