import type { CSSProperties } from "react";

/** Style cho phần tử thứ `index` trong danh sách dùng class `stagger` (đặt biến --i). */
export function staggerStyle(index: number): CSSProperties {
  return { "--i": index } as CSSProperties;
}
