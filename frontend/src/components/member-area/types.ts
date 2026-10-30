// Khu hội viên (T-016). Contract theo board/tasks/T-016-khu-hoi-vien.md; đổi sang type sinh từ schema.d.ts khi BE handoff.

export type MemberMe = {
  member_code: string;
  full_name: string;
  /** Từ cuối của Họ tên. */
  short_name: string;
  nickname: string | null;
  email: string | null;
  /** Đầy đủ – chỉ chính chủ thấy. */
  phone: string;
  joined_at: string;
  /** Chưa xếp hạng ⇒ null (ô Trình độ để trống). */
  tier: string | null;
  /** Tên vợt (chuỗi) hoặc null. */
  racket: string | null;
  show_on_records: boolean;
  avatar_url: string | null;
  record_kmh: number | null;
  version: number;
};

export type MeInput = {
  full_name: string;
  nickname: string | null;
  email: string | null;
  /** Phải là một trong 8 bậc; null chỉ khi chưa từng có và không đổi. */
  tier: string | null;
  /** Gõ tên chưa có thì BE tự thêm vào danh mục. */
  racket: string | null;
  show_on_records: boolean;
  version: number;
};

/** Khung cắt theo pixel của ảnh gốc. */
export type Crop = { x: number; y: number; size: number };

export const NICKNAME_MAX = 20;

/** "0912345678" → "0912 345 678". */
export const formatPhone = (p: string) => (p.length === 10 ? `${p.slice(0, 4)} ${p.slice(4, 7)} ${p.slice(7)}` : p);

/** "0912345678" → "0912 xxx 678". */
export const maskPhone = (p: string) => (p.length >= 7 ? `${p.slice(0, 4)} xxx ${p.slice(-3)}` : p);
