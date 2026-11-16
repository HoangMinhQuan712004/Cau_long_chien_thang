// Đọc/ghi bộ lọc trên URL, hàm thuần (không React) ⇒ server lẫn client dùng được

/** Patch theo khóa logic; null / "" / "all" ⇒ xóa tham số. */
export type ParamPatch<K extends string> = Partial<Record<K, string | null>>;

/** Áp patch lên query hiện tại; patch không có trang ⇒ xóa tham số trang (về trang 1 khi đổi lọc). */
export function patchParams<K extends string>(
  current: URLSearchParams,
  param: Record<K, string>,
  pageKey: K,
  patch: ParamPatch<K>,
): URLSearchParams {
  const next = new URLSearchParams(current);
  for (const [key, value] of Object.entries(patch) as [K, string | null | undefined][]) {
    if (value === null || value === undefined || value === "" || value === "all") next.delete(param[key]);
    else next.set(param[key], value);
  }
  if (!(pageKey in patch)) next.delete(param[pageKey]);
  return next;
}

/** Đường dẫn đầy đủ từ pathname + query (rỗng ⇒ không có "?"). */
export function hrefOf(pathname: string, params: URLSearchParams): string {
  const qs = params.toString();
  return qs ? `${pathname}?${qs}` : pathname;
}
