import type { MonitorPerson } from "./types";

/** "Nguyễn Văn A" + "lolo" ⇒ `Nguyễn Văn A (lolo)`. */
export const personName = (p: MonitorPerson) => (p.nickname ? `${p.full_name} (${p.nickname})` : p.full_name);

/** Dòng phụ: mã HV · hạng (bỏ phần thiếu). */
export const personMeta = (p: MonitorPerson) => [p.member_code, p.tier ? `Hạng ${p.tier}` : null].filter(Boolean).join(" · ");

export const teamNames = (t: MonitorPerson[]) => t.map((p) => p.nickname || p.full_name).join(" · ") || "–";
