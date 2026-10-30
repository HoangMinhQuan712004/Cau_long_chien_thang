// DỮ LIỆU GIẢ cho màn Hội viên (T-015) – chỉ chạy khi NEXT_PUBLIC_MEMBERS_MOCK=1. Xóa khi nối API thật.
import type { ApiError, WriteResult } from "@/lib/api/write";
import { normalizePhone, isValidPhone } from "@/lib/phone";
import type { Read } from "./requests";
import {
  fold,
  type MemberDetail,
  type MemberEdit,
  type MemberInput,
  type MemberPatch,
  PAGE_SIZE,
  type ProfileItem,
  type ProfileList,
  type ProfileQuery,
  type RacketGroup,
  TIERS,
  type TempInput,
} from "./types";

type Rec = ProfileItem & { phone: string; racket_id: number | null; version: number; total_hours: number };

const rackets: { id: number; brand: string; name: string }[] = [
  { id: 1, brand: "YONEX", name: "Astrox 88D Pro" },
  { id: 2, brand: "YONEX", name: "Astrox 100ZZ" },
  { id: 3, brand: "YONEX", name: "Astrox 77 Pro" },
  { id: 4, brand: "YONEX", name: "Nanoflare 800" },
  { id: 5, brand: "VICTOR", name: "Thruster K 9900" },
  { id: 6, brand: "VICTOR", name: "Auraspeed 90K II" },
  { id: 7, brand: "LI-NING", name: "Axforce 90" },
  { id: 8, brand: "MIZUNO", name: "Fortius 30" },
];

const NAMES = ["Nguyễn Văn A", "Trần Thị Bình", "Lê Hoàng Cường", "Phạm Quang Minh", "Đỗ Minh Tuấn", "Võ Thu Trang", "Bùi Đức Anh", "Hoàng Gia Huy", "Đặng Thanh Hà", "Ngô Bảo Long"];

const store: Rec[] = [];
let seq = 0;
let lastCode = 0;
const iso = (d: number) => new Date(Date.now() - d * 86400000).toISOString().slice(0, 10);
const mask = (p: string) => `${p.slice(0, 4)} xxx ${p.slice(-3)}`;
const wait = (ms = 250) => new Promise((r) => setTimeout(r, ms));

function add(partial: Partial<Rec> & { full_name: string; phone: string; kind: "member" | "temp" }): Rec {
  seq += 1;
  const isMember = partial.kind === "member";
  if (isMember) lastCode += 1;
  const rec: Rec = {
    id: seq,
    member_code: isMember ? `HV${String(lastCode).padStart(4, "0")}` : null,
    gender: seq % 5 === 0 ? null : seq % 2 ? "M" : "F",
    tier: isMember ? TIERS[seq % TIERS.length] : null,
    booking_count: (seq * 7) % 40,
    is_active: isMember ? seq % 9 !== 0 : null,
    created_at: iso(seq),
    phone_masked: mask(partial.phone),
    racket_id: isMember && seq % 3 === 0 ? 1 : null,
    version: 1,
    total_hours: ((seq * 7) % 40) * 2,
    ...partial,
  };
  rec.phone_masked = mask(rec.phone);
  store.push(rec);
  return rec;
}

function seed() {
  if (store.length) return;
  for (let i = 0; i < 64; i++) {
    const phone = `09${String(10000000 + i * 137).padStart(8, "0")}`;
    add({ full_name: `${NAMES[i % NAMES.length]}${i >= NAMES.length ? ` ${i}` : ""}`, phone, kind: i % 4 === 3 ? "temp" : "member" });
  }
}

const strip = ({ phone: _p, racket_id: _r, version: _v, total_hours: _t, ...item }: Rec): ProfileItem => item;

const err = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): { ok: false; error: ApiError } => ({
  ok: false,
  error: { status, code, message, extra },
});

export async function listProfiles(q: ProfileQuery): Promise<Read<ProfileList>> {
  seed();
  await wait();
  const counts = { all: store.length, member: store.filter((r) => r.kind === "member").length, temp: store.filter((r) => r.kind === "temp").length };
  const needle = fold(q.q.trim());
  const digits = q.q.replace(/[\s.]/g, "");
  const memberFilter = q.type !== "temp" && (q.status !== "all" || q.tier !== "");
  let rows = store.filter((r) => {
    if (q.type !== "all" && r.kind !== q.type) return false;
    if (needle && !match(r, needle, digits)) return false;
    if (r.kind === "temp") return !memberFilter;
    if (q.type === "temp") return true;
    if (q.status === "active" && r.is_active !== true) return false;
    if (q.status === "inactive" && r.is_active !== false) return false;
    return !q.tier || r.tier === q.tier;
  });
  const byDefault = (a: Rec, b: Rec) => (a.kind === b.kind ? (a.kind === "member" ? a.id - b.id : b.id - a.id) : a.kind === "member" ? -1 : 1);
  rows = rows.sort((a, b) => {
    if (q.sort === "bookings_desc" && a.booking_count !== b.booking_count) return b.booking_count - a.booking_count;
    if (q.sort === "bookings_asc" && a.booking_count !== b.booking_count) return a.booking_count - b.booking_count;
    return byDefault(a, b);
  });
  const start = (q.page - 1) * PAGE_SIZE;
  return { ok: true, data: { counts, total: rows.length, page: q.page, page_size: PAGE_SIZE, items: rows.slice(start, start + PAGE_SIZE).map(strip) } };
}

function match(r: Rec, needle: string, digits: string) {
  return fold(r.member_code ?? "").includes(needle) || fold(r.full_name).includes(needle) || (digits !== "" && r.phone.includes(digits));
}

const racketOf = (id: number | null) => rackets.find((r) => r.id === id) ?? null;

function detail(r: Rec): MemberDetail {
  const recent = Array.from({ length: Math.min(5, r.booking_count) }, (_, i) => ({
    code: `BK-2026${String(10 - i).padStart(2, "0")}${String(20 - i).padStart(2, "0")}-0${10 + i}`,
    play_date: iso(7 * (i + 1)),
    start_time: "18:00",
    end_time: "20:00",
    resources: ["S02"],
    amount: 400000,
  }));
  return { ...strip(r), racket: racketOf(r.racket_id), total_hours: r.total_hours, recent, version: r.version };
}

export async function getDetail(id: number): Promise<Read<MemberDetail>> {
  seed();
  await wait();
  const r = store.find((x) => x.id === id && x.kind === "member");
  return r ? { ok: true, data: detail(r) } : err(404, "E-HV-5", "Không tìm thấy hội viên.");
}

export async function getEdit(id: number): Promise<Read<MemberEdit>> {
  seed();
  await wait();
  const r = store.find((x) => x.id === id && x.kind === "member");
  return r ? { ok: true, data: { ...detail(r), phone: r.phone } } : err(404, "E-HV-5", "Không tìm thấy hội viên.");
}

export async function getNextCode(): Promise<Read<{ code: string }>> {
  seed();
  return { ok: true, data: { code: `HV${String(lastCode + 1).padStart(4, "0")}` } };
}

export async function listRackets(): Promise<Read<RacketGroup[]>> {
  const brands = [...new Set(rackets.map((r) => r.brand))];
  return { ok: true, data: brands.map((brand) => ({ brand, items: rackets.filter((r) => r.brand === brand).map(({ id, name }) => ({ id, name })) })) };
}

export async function createRacket(name: string): Promise<WriteResult<{ id: number; brand: string; name: string }>> {
  await wait();
  const hit = rackets.find((r) => r.name.toLowerCase() === name.trim().toLowerCase());
  if (hit) return { ok: true, status: 201, data: hit };
  const r = { id: rackets.length + 1, brand: "Khác", name: name.trim() };
  rackets.push(r);
  return { ok: true, status: 201, data: r };
}

/** Kiểm như server: bắt buộc → định dạng → trùng; trả mọi ô sai một lần. */
function check(input: { full_name: string; phone: string }, selfId?: number) {
  const fields: { field: string; code: string; message: string }[] = [];
  if (!input.full_name.trim()) fields.push({ field: "full_name", code: "E-HV-1", message: "Vui lòng nhập Họ tên." });
  const phone = normalizePhone(input.phone);
  if (!input.phone.trim()) fields.push({ field: "phone", code: "E-HV-1", message: "Vui lòng nhập Số điện thoại." });
  else if (!isValidPhone(phone)) fields.push({ field: "phone", code: "E-HV-2", message: "Số điện thoại không hợp lệ." });
  else {
    const dup = store.find((r) => r.phone === phone && r.id !== selfId);
    if (dup?.kind === "member") fields.push({ field: "phone", code: "E-HV-3", message: `Số điện thoại đã thuộc hội viên ${dup.member_code} · ${dup.full_name}` });
    if (dup?.kind === "temp") {
      const d = dup.created_at;
      fields.push({ field: "phone", code: "E-HV-4", message: `Số điện thoại đã có hồ sơ tạm: ${dup.full_name} (tạo ${d.slice(8, 10)}/${d.slice(5, 7)}/${d.slice(0, 4)})` });
    }
  }
  return { fields, phone };
}

function failFields(fields: { field: string; code: string; message: string }[]) {
  const onlyDup = fields.length === 1 && (fields[0].code === "E-HV-3" || fields[0].code === "E-HV-4");
  return err(onlyDup ? 409 : 422, fields[0].code, fields[0].message, { fields });
}

export async function createMember(body: MemberInput): Promise<WriteResult<ProfileItem>> {
  seed();
  await wait(500);
  const { fields, phone } = check(body);
  if (fields.length) return failFields(fields);
  const r = add({ full_name: body.full_name.trim(), gender: body.gender, phone, tier: body.tier, racket_id: body.racket_id, kind: "member", is_active: true, booking_count: 0, total_hours: 0, created_at: iso(0) });
  return { ok: true, status: 201, data: strip(r) };
}

export async function patchMember(id: number, body: MemberPatch): Promise<WriteResult<ProfileItem | { unchanged: true }>> {
  seed();
  await wait(500);
  const r = store.find((x) => x.id === id && x.kind === "member");
  if (!r) return err(404, "E-HV-5", "Không tìm thấy hội viên.");
  if (r.version !== body.version) return err(409, "E-HV-9", "Hội viên này vừa được cập nhật ở máy khác. Tải lại để xem bản mới nhất.");
  const { fields, phone } = check(body, id);
  if (fields.length) return failFields(fields);
  const same = r.full_name === body.full_name.trim() && r.gender === body.gender && r.phone === phone && r.tier === body.tier && r.racket_id === body.racket_id && r.is_active === body.is_active;
  if (same) return { ok: true, status: 200, data: { unchanged: true } };
  Object.assign(r, { full_name: body.full_name.trim(), gender: body.gender, phone, phone_masked: mask(phone), tier: body.tier, racket_id: body.racket_id, is_active: body.is_active, version: r.version + 1 });
  return { ok: true, status: 200, data: strip(r) };
}

export async function createTemp(body: TempInput): Promise<WriteResult<ProfileItem>> {
  seed();
  await wait(500);
  const { fields, phone } = check(body);
  if (fields.length) return failFields(fields);
  const r = add({ full_name: body.full_name.trim(), gender: body.gender, phone, kind: "temp", tier: null, is_active: null, booking_count: 0, total_hours: 0, created_at: iso(0) });
  return { ok: true, status: 201, data: strip(r) };
}
