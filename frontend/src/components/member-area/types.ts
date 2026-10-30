// Khu hội viên (T-016). Contract theo board/tasks/T-016-khu-hoi-vien.md; đổi sang type sinh từ schema.d.ts khi BE handoff.

import type { components } from "@/lib/api/schema";

export type MemberMe = components["schemas"]["MemberMeOut"];
/** Body PUT /member-area/me: `tier` null chỉ khi hồ sơ chưa từng có hạng; `racket` là tên vợt (BE tự thêm vào danh mục). */
export type MeInput = components["schemas"]["MemberMeIn"];

/** Khung cắt theo pixel của ảnh gốc. */
export type Crop = { x: number; y: number; size: number };

export const NICKNAME_MAX = 20;

/** "0912345678" → "0912 345 678". */
export const formatPhone = (p: string) => (p.length === 10 ? `${p.slice(0, 4)} ${p.slice(4, 7)} ${p.slice(7)}` : p);

/** "0912345678" → "0912 xxx 678". */
export const maskPhone = (p: string) => (p.length >= 7 ? `${p.slice(0, 4)} xxx ${p.slice(-3)}` : p);
