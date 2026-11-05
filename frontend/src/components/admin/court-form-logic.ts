import type { components } from "@/lib/api/schema";
import { errorText, type ApiError } from "@/lib/api/write";

// Phần thuần của form sân (thêm / sửa): kiểu dữ liệu, kiểm lỗi, đổi giờ. Dùng chung cho popup "Thêm sân" và ngăn chi tiết.

type Schedule = Omit<components["schemas"]["ScheduleOut"], "peak_bands"> & { peak_bands: string[][] };
/** Sân như API trả về (khung cao điểm là mảng [từ, đến]; OpenAPI sinh kiểu tuple nên khai báo lại cho lỏng hơn). */
export type Resource = Omit<components["schemas"]["ResourceOut"], "schedule" | "pending_schedule"> & {
  schedule: Schedule | null;
  pending_schedule: Schedule | null;
};
export type ResourceType = components["schemas"]["ResourceTypeOut"];
export type PriceCell = components["schemas"]["PriceCellOut"];
export type Band = [string, string];

export const hhmm = (min: number) => `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
export const TIMES = Array.from({ length: 49 }, (_, i) => hhmm(i * 30)); // 00:00 -> 24:00, bước 30 phút
export const toMin = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));
export const sortBands = (b: Band[]): Band[] => [...b].sort((x, y) => toMin(x[0]) - toMin(y[0]));
/** Backend có thể trả "HH:MM:SS"; chỉ lấy HH:MM. */
export const t5 = (t: string) => t.slice(0, 5);
export const bandsOf = (s: Schedule) => sortBands(s.peak_bands.map((p) => [t5(p[0]), t5(p[1])] as Band));

export type Form = {
  mode: "add" | "edit";
  code?: string;
  version?: number;
  name: string;
  type: string;
  open: string;
  close: string;
  peaks: Band[];
  active: boolean;
};

export type Errors = { name?: string; close?: string; peaks: Record<number, string>; overlap?: string; overlapIdx?: number[] };

/** Form trống cho "Thêm sân" (giờ mặc định 05:00–22:00, 2 khung cao điểm). */
export const emptyForm = (types: ResourceType[]): Form => ({
  mode: "add",
  name: "",
  type: types[0]?.code ?? "thuong",
  open: "05:00",
  close: "22:00",
  peaks: [
    ["05:00", "07:00"],
    ["17:00", "21:00"],
  ],
  active: true,
});

/** Form sửa từ sân đã có: lấy giờ đã lưu gần nhất (kể cả giờ chờ áp dụng). */
export function formOf(r: Resource): Form {
  const s = r.pending_schedule ?? r.schedule;
  return {
    mode: "edit",
    code: r.code,
    version: r.version,
    name: r.name,
    type: r.resource_type_code,
    open: s ? t5(s.open_time) : "05:00",
    close: s ? t5(s.close_time) : "22:00",
    peaks: s ? bandsOf(s) : [],
    active: r.is_active,
  };
}

export function validate(f: Form, others: Resource[]): Errors {
  const e: Errors = { peaks: {} };
  const name = f.name.trim();
  if (!name) e.name = "Vui lòng nhập Tên sân.";
  else if (name.length > 50) e.name = "Tên sân tối đa 50 ký tự.";
  else if (others.some((r) => r.code !== f.code && r.name.trim().toLowerCase() === name.toLowerCase())) {
    e.name = "Tên sân đã có. Vui lòng đặt tên khác.";
  }
  const o = toMin(f.open);
  const c = toMin(f.close);
  if (c - o < 60) e.close = "Giờ đóng cửa phải sau giờ mở cửa ít nhất 1 tiếng.";
  f.peaks.forEach((p, i) => {
    const from = toMin(p[0]);
    const to = toMin(p[1]);
    if (to - from < 30 || from < o || to > c) {
      e.peaks[i] = `Khung cao điểm phải dài ít nhất 30 phút và nằm trong giờ mở cửa (${f.open} – ${f.close}).`;
    }
  });
  for (let i = 0; i < f.peaks.length && !e.overlap; i++) {
    for (let j = i + 1; j < f.peaks.length; j++) {
      const a = f.peaks[i];
      const b = f.peaks[j];
      if (toMin(a[0]) < toMin(b[1]) && toMin(b[0]) < toMin(a[1])) {
        e.overlap = `Khung ${a[0]} – ${a[1]} và khung ${b[0]} – ${b[1]} bị chồng nhau.`;
        e.overlapIdx = [i, j];
        break;
      }
    }
  }
  return e;
}

export const hasErrors = (e: Errors) => Boolean(e.name || e.close || e.overlap || Object.keys(e.peaks).length);

type Conflict = { code: string; date: string; start_time: string; end_time: string };

/** Lỗi từ server hiện ở đầu form (E-CFG-3/4 kèm danh sách khung vướng; E-CFG-7 = dữ liệu đã đổi, cần tải lại). */
export type Banner = { text: string; items?: Conflict[]; more?: number; reload?: boolean };

export function bannerFrom(error: ApiError): Banner {
  const items = Array.isArray(error.extra.items) ? (error.extra.items as Conflict[]) : undefined;
  const more = typeof error.extra.more === "number" ? error.extra.more : 0;
  return { text: errorText(error), items, more, reload: error.code === "E-CFG-7" };
}
