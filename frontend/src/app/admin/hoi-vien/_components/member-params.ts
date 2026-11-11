import type { SortDir } from "@/components/ui/data-table";
import type { MemberTier } from "@/lib/api/server";

// Bộ lọc danh sách hội viên nằm trên URL (?loai=&q=&trang-thai=&hang=&vot=&sap-xep=&trang=&so-dong=) – F5 / gửi link không mất

/** Số dòng mỗi trang được chọn; phần tử đầu là mặc định (không ghi lên URL). */
export const PAGE_SIZES = [20, 50, 100] as const;
/** Độ dài tối đa ô tìm (khớp `max_length` của BE). */
export const SEARCH_MAX = 50;
/** Ngày sinh sớm nhất (khớp ràng buộc DB); muộn nhất là hôm nay – form quản trị và Hồ sơ của tôi dùng chung. */
export const BIRTH_MIN = "1900-01-01";
// Hạng = trình độ chơi, theo thứ tự thấp ⇒ cao. Kiểu Record bắt buộc đủ đúng các hạng trong schema.d.ts:
// BE thêm/bớt/đổi tên hạng ⇒ tsc báo lỗi ở đây (danh sách chỉ viết một nơi, form và bộ lọc dùng chung)
const TIER_ORDER: Record<MemberTier, true> = {
  Yếu: true,
  "Trung bình yếu": true,
  "Trung bình -": true,
  "Trung bình": true,
  "Trung bình +": true,
  Khá: true,
  "Bán chuyên": true,
  "Chuyên nghiệp": true,
};
export const TIERS = Object.keys(TIER_ORDER) as MemberTier[];
/** Giá trị lọc "Chưa xếp hạng" trên URL và API. */
export const TIER_NONE = "none";

/** Các tab Loại, theo thứ tự hiện. */
export const MEMBER_KINDS = ["all", "member", "temp"] as const;
type MemberKind = (typeof MEMBER_KINDS)[number];
type MemberStatus = "all" | "active" | "inactive";
/** `racket` rỗng = mọi vợt. */
export type MemberFilter = { kind: MemberKind; q: string; status: MemberStatus; tier: string; racket: string };

type MemberParamKey = keyof MemberFilter | "sort" | "page" | "size";

/** Tên tham số URL của từng khóa (dùng với useUrlFilters / patchParams). */
export const PARAM: Record<MemberParamKey, string> = {
  kind: "loai",
  q: "q",
  status: "trang-thai",
  tier: "hang",
  racket: "vot",
  sort: "sap-xep",
  page: "trang",
  size: "so-dong",
};

/** Patch "Xóa lọc": bỏ mọi bộ lọc, giữ sắp xếp và số dòng. */
export const CLEAR_FILTERS = { kind: null, q: null, status: null, tier: null, racket: null } as const;

/** Có bộ lọc nào khác mặc định không (câu rỗng chọn "lọc không ra" hay "chưa có hồ sơ"). */
export function isFiltered(f: MemberFilter): boolean {
  return f.kind !== "all" || f.q !== "" || f.status !== "all" || f.tier !== "all" || f.racket !== "";
}

// Giá trị lạ trên URL ⇒ bỏ qua (về "Tất cả")
function oneOf<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
}

/** Giá trị `?sap-xep=` ⇒ chiều sắp xếp "Số lần đặt"; `so-lan-dat` (link cũ) = giảm dần. */
const SORT_DIR: Record<string, SortDir> = { "so-lan-dat": "desc", "so-lan-dat-giam": "desc", "so-lan-dat-tang": "asc" };
/** Bấm tiêu đề cột: mặc định ⇒ giảm ⇒ tăng ⇒ mặc định. */
export const NEXT_SORT: Record<SortDir | "none", string | null> = {
  none: "so-lan-dat-giam",
  desc: "so-lan-dat-tang",
  asc: null,
};

/** Dùng chung cho trang server (gọi API) và client (đổi URL). */
export function readMemberParams(params: URLSearchParams) {
  const filter: MemberFilter = {
    kind: oneOf(params.get(PARAM.kind), ["member", "temp"], "all"),
    q: (params.get(PARAM.q) ?? "").slice(0, SEARCH_MAX),
    status: oneOf(params.get(PARAM.status), ["active", "inactive"], "all"),
    tier: oneOf(params.get(PARAM.tier), [...TIERS, TIER_NONE], "all"),
    racket: (params.get(PARAM.racket) ?? "").trim().slice(0, 100),
  };
  const page = Math.min(10_000, Math.max(1, Math.trunc(Number(params.get(PARAM.page))) || 1));
  // Giá trị lạ ⇒ mặc định 20
  const size = PAGE_SIZES.find((n) => String(n) === params.get(PARAM.size)) ?? PAGE_SIZES[0];
  return { filter, page, size, bookingsSort: SORT_DIR[params.get(PARAM.sort) ?? ""] ?? null };
}
