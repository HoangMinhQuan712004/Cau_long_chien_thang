import { connection } from "next/server";
import type { ReactNode } from "react";
import { getPublicPrices, type PublicPrices } from "@/lib/api/server";

/**
 * Đọc bảng giá công khai LÚC CHẠY (sau `connection()`), không lúc build: build (CI, Docker) không có backend,
 * nên vỏ tĩnh của trang chỉ chứa phần không phụ thuộc dữ liệu; phần này nằm trong <Suspense> và được stream khi có dữ liệu.
 * Bản thân `getPublicPrices()` vẫn được cache 1–5 phút ở runtime. `data` là null khi backend không trả lời.
 *
 * Luôn bọc trong <Suspense> với fallback không chứa số liệu (ẩn dòng / khung chờ).
 */
export async function WithPublicPrices({ children }: { children: (data: PublicPrices | null) => ReactNode }) {
  await connection();
  return children(await getPublicPrices());
}

/** Giờ mở cửa dạng "05:00 – 22:00"; null khi chưa có sân hoạt động hoặc chưa tải được dữ liệu. */
export function openingText(data: PublicPrices | null): string | null {
  const open = data?.opening_hours.earliest_open?.slice(0, 5);
  const close = data?.opening_hours.latest_close?.slice(0, 5);
  return open && close ? `${open} – ${close}` : null;
}
