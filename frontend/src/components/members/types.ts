// Màn Hội viên (T-015). Contract theo board/tasks/T-015-quan-ly-hoi-vien.md; đổi sang type sinh từ schema.d.ts khi BE handoff.

/** 8 bậc trình độ, thấp → cao (BR-011). */
export const TIERS = ["Yếu", "Trung bình yếu", "Trung bình -", "Trung bình", "Trung bình +", "Khá", "Bán chuyên", "Chuyên nghiệp"] as const;
export const DEFAULT_TIER = "Trung bình";

export type Gender = "M" | "F" | null;
export const GENDER_LABEL: Record<"M" | "F", string> = { M: "Nam", F: "Nữ" };

export type ProfileKind = "member" | "temp";
export type ProfileType = "all" | ProfileKind;
export type StatusFilter = "all" | "active" | "inactive";
export type ProfileSort = "default" | "bookings_desc" | "bookings_asc";

export type ProfileItem = {
  id: number;
  kind: ProfileKind;
  member_code: string | null;
  full_name: string;
  gender: Gender;
  phone_masked: string;
  tier: string | null;
  booking_count: number;
  is_active: boolean | null;
  created_at: string;
};

export type ProfileList = {
  counts: { all: number; member: number; temp: number };
  total: number;
  page: number;
  page_size: number;
  items: ProfileItem[];
};

export type ProfileQuery = {
  type: ProfileType;
  q: string;
  status: StatusFilter;
  tier: string; // "" = Tất cả
  sort: ProfileSort;
  page: number;
};

export type RacketRef = { id: number; brand: string; name: string };

export type RecentBooking = {
  code: string;
  play_date: string;
  start_time: string;
  end_time: string;
  resources: string[];
  amount: number;
};

export type MemberDetail = ProfileItem & {
  racket: RacketRef | null;
  total_hours: number;
  recent: RecentBooking[];
  version: number;
};

/** Cho hộp Sửa: có SĐT đầy đủ (chỉ endpoint /edit trả). */
export type MemberEdit = MemberDetail & { phone: string };

export type RacketGroup = { brand: string; items: { id: number; name: string }[] };

export type MemberInput = {
  full_name: string;
  gender: Gender;
  phone: string;
  tier: string;
  racket_id: number | null;
};

export type MemberPatch = MemberInput & { is_active: boolean; version: number };
export type TempInput = { full_name: string; gender: Gender; phone: string };

export const PAGE_SIZE = 20;

/** "Yonex Astrox 88D Pro": tên hãng (chữ hoa trong danh sách) viết hoa chữ đầu + tên vợt; nhóm "Khác" chỉ có tên. */
export function racketLabel(r: { brand: string; name: string }): string {
  if (r.brand.toLowerCase() === "khác") return r.name;
  const brand = r.brand
    .toLowerCase()
    .replace(/(^|[\s-])(\p{L})/gu, (_, sep: string, c: string) => sep + c.toUpperCase());
  return `${brand} ${r.name}`;
}

/** Bỏ dấu + hạ chữ thường để tìm không phân biệt dấu (chỉ dùng cho dữ liệu giả và lọc vợt ở máy khách). */
export const fold = (s: string) =>
  s
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase();
