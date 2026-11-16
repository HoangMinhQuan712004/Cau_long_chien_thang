import type { SortDir } from "@/components/ui/data-table";
import type { AuditActorKind } from "@/lib/api/server";
import type { ParamPatch } from "@/lib/url-params";

// Bộ lọc nằm trên URL (?tu=&den=&nguoi-lam=&loai=&sap-xep=&trang=&so-dong=): đổi là áp ngay, về trang 1; F5 / Back không mất.
// Menu mở link sạch ⇒ về mặc định 7 ngày, nên bộ lọc không "lưu" khi rời màn (BR-012).

export type AuditFilter = { from: string; to: string; actor: string; action: string };

type AuditParamKey = keyof AuditFilter | "sort" | "page" | "size";

export const PARAM: Record<AuditParamKey, string> = {
  from: "tu",
  to: "den",
  actor: "nguoi-lam",
  action: "loai",
  sort: "sap-xep",
  page: "trang",
  size: "so-dong",
};

/** Patch đổi URL (null / "" / "all" ⇒ bỏ tham số; không có trang ⇒ về trang 1). */
export type AuditPatch = ParamPatch<AuditParamKey>;

/** Số dòng mỗi trang được chọn (như màn Hội viên). */
export const PAGE_SIZES = [20, 50, 100] as const;
/** Mặc định 50 dòng (BR-015), không ghi lên URL. */
export const DEFAULT_SIZE = 50;

/** Giá trị `?sap-xep=` ⇒ chiều cột Thời điểm; không có = mới trước (mặc định). */
const SORT_DIR: Record<string, SortDir> = { "thoi-gian-giam": "desc", "thoi-gian-tang": "asc" };
/** Bấm tiêu đề cột Thời điểm: mới trước ⇔ cũ trước (mặc định không ghi lên URL). */
export const NEXT_SORT: Record<SortDir, string | null> = { desc: "thoi-gian-tang", asc: null };

/** Patch "Xóa lọc": về mặc định (7 ngày gần nhất, Tất cả); giữ sắp xếp và số dòng như màn Hội viên. */
export const CLEAR_FILTERS = { from: null, to: null, actor: null, action: null } as const;

const ACTORS: readonly AuditActorKind[] = ["admin", "staff", "customer", "system"];
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Toàn bộ tham số đã đọc: bộ lọc + sắp xếp + trang + số dòng. */
export type AuditParams = AuditFilter & { sort: SortDir; page: number; size: number };

/** Đọc URL; giá trị lạ ⇒ bỏ (ngày sai định dạng, người làm lạ). Loại thao tác lạ do backend báo 422. */
export function readAuditParams(sp: URLSearchParams): AuditParams {
  const date = (key: string) => {
    const v = sp.get(key) ?? "";
    return ISO_DATE.test(v) ? v : "";
  };
  const actor = sp.get(PARAM.actor) ?? "";
  const page = Number(sp.get(PARAM.page));
  return {
    from: date(PARAM.from),
    to: date(PARAM.to),
    actor: (ACTORS as readonly string[]).includes(actor) ? actor : "all",
    action: sp.get(PARAM.action) || "all",
    sort: SORT_DIR[sp.get(PARAM.sort) ?? ""] ?? "desc",
    page: Number.isInteger(page) && page > 1 ? page : 1,
    // Giá trị lạ ⇒ mặc định 50
    size: PAGE_SIZES.find((n) => String(n) === sp.get(PARAM.size)) ?? DEFAULT_SIZE,
  };
}

/** Tham số gửi API (bỏ "Tất cả" / rỗng). */
export function auditQuery(f: AuditParams) {
  return {
    from: f.from || undefined,
    to: f.to || undefined,
    actor: f.actor === "all" ? undefined : (f.actor as AuditActorKind),
    action: f.action === "all" ? undefined : f.action,
    sort: f.sort === "asc" ? ("at_asc" as const) : undefined,
    page: f.page,
    size: f.size === DEFAULT_SIZE ? undefined : (f.size as (typeof PAGE_SIZES)[number]),
  };
}
