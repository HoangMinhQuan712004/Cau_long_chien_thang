"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { hrefOf, type ParamPatch, patchParams } from "@/lib/url-params";

/**
 * Bộ lọc danh sách nằm trên URL (F5 / gửi link không mất, nút Back dùng được).
 * `param`: khóa logic ⇒ tên tham số URL; `pageKey`: khóa của số trang.
 */
export function useUrlFilters<K extends string>(param: Record<K, string>, pageKey: NoInfer<K>) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Link sang URL đã áp patch (dùng cho <Link>, phân trang)
  const hrefWith = (patch: ParamPatch<K>) => hrefOf(pathname, patchParams(searchParams, param, pageKey, patch));
  // Đổi URL tại chỗ: replace để không chất lịch sử, không cuộn lên đầu
  const set = (patch: ParamPatch<K>) => router.replace(hrefWith(patch), { scroll: false });

  return { searchParams, hrefWith, set };
}
