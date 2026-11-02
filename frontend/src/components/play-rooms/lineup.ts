import type { CurrentMatch, Format } from "./types";

// Đội hình do Host xếp (T-027): bản nháp cục bộ gồm id dòng thành viên phòng theo từng ô. Hàm thuần, không đụng React.

export type Team = "a" | "b";
export type SlotRef = { team: Team; idx: number };
/** `null` = ô trống. `format` để bỏ bản nháp cũ khi Host đổi thể thức. */
export type Draft = { format: Format; a: (number | null)[]; b: (number | null)[] };

/** Số ô mỗi đội: 2 vs 2 → 2, 1 vs 1 → 1. */
export const teamSize = (format: Format) => (format === "2v2" ? 2 : 1);

export const emptyDraft = (format: Format): Draft => ({
  format,
  a: Array<number | null>(teamSize(format)).fill(null),
  b: Array<number | null>(teamSize(format)).fill(null),
});

/** Đội hình đã lưu trên server (trận `drawn`) → bản nháp. */
export function fromMatch(format: Format, cur: CurrentMatch | null | undefined): Draft {
  const d = emptyDraft(format);
  if (!cur || cur.status !== "drawn") return d;
  cur.team_a.slice(0, d.a.length).forEach((p, i) => (d.a[i] = p.member_id));
  cur.team_b.slice(0, d.b.length).forEach((p, i) => (d.b[i] = p.member_id));
  return d;
}

export const slotsOf = (d: Draft): { ref: SlotRef; id: number | null }[] => [
  ...d.a.map((id, idx) => ({ ref: { team: "a" as const, idx }, id })),
  ...d.b.map((id, idx) => ({ ref: { team: "b" as const, idx }, id })),
];

export const idsOf = (d: Draft): number[] => slotsOf(d).flatMap((s) => (s.id === null ? [] : [s.id]));
export const isFull = (d: Draft) => slotsOf(d).every((s) => s.id !== null);
export const isEmpty = (d: Draft) => idsOf(d).length === 0;
export const sameLineup = (x: Draft, y: Draft) => JSON.stringify([x.a, x.b]) === JSON.stringify([y.a, y.b]);

const read = (d: Draft, r: SlotRef) => d[r.team][r.idx] ?? null;
function write(d: Draft, r: SlotRef, id: number | null): Draft {
  const side = [...d[r.team]];
  side[r.idx] = id;
  return { ...d, [r.team]: side };
}

/** Đặt người (đang ở ngoài sân hoặc ở ô khác) vào ô; ô đang có người thì người đó ra ngoài. */
export function place(d: Draft, id: number, to: SlotRef): Draft {
  let next = d;
  for (const s of slotsOf(d)) if (s.id === id) next = write(next, s.ref, null);
  return write(next, to, id);
}

/** Kéo ô này sang ô kia: ô kia trống thì chuyển, có người thì đổi chỗ. */
export function swap(d: Draft, from: SlotRef, to: SlotRef): Draft {
  const a = read(d, from);
  const b = read(d, to);
  return write(write(d, from, b), to, a);
}

export const remove = (d: Draft, r: SlotRef): Draft => write(d, r, null);

/** "Chuyển sang đội kia": vào ô trống đầu tiên của đội kia, hết ô trống thì đổi chỗ với người ở ô đầu. */
export function switchTeam(d: Draft, r: SlotRef): Draft {
  const other: Team = r.team === "a" ? "b" : "a";
  const free = d[other].findIndex((x) => x === null);
  return swap(d, r, { team: other, idx: free >= 0 ? free : 0 });
}
