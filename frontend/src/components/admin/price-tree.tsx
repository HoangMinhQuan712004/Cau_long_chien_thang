import type { ReactNode } from "react";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";

// Trình bày bảng giá: cây gia phả từ trên xuống ở tiêu đề (Loại ngày → Thấp / Cao), loại sân là nhãn hàng.
// Tiêu đề và các hàng nằm chung một lưới nên ô giá thẳng cột nút tiêu đề. Theo bề rộng khung (không theo màn hình,
// vì thanh bên có thể mở / thu): khung hẹp chuyển sang mỗi loại sân một nhóm.

export const DAY_TYPES = ["weekday", "weekend", "holiday"] as const;
export const BANDS = ["offpeak", "peak"] as const;
export type DayType = (typeof DAY_TYPES)[number];
export type BandKey = (typeof BANDS)[number];
export const cellKey = (type: string, day: string, band: string) => `${type}|${day}|${band}`;

export type PriceType = { code: string; name: string };
type Props = {
  types: readonly PriceType[];
  courtCount: (type: string) => string;
  renderInput: (type: PriceType, day: DayType, band: BandKey) => ReactNode;
  t: Dictionary["prices"];
};

// Cột nhãn, rồi 3 nhóm "cột đệm + 2 cột giá bằng nhau": cột đệm làm khoảng cách giữa nhóm lớn hơn trong nhóm
const GRID = "grid grid-cols-[9rem_repeat(3,0.75rem_minmax(0,1fr)_minmax(0,1fr))] gap-x-1.5";
const DAY_COLUMN = ["col-span-2 col-start-3", "col-span-2 col-start-6", "col-span-2 col-start-9"];
const BAND_COLUMN = [
  ["col-start-3", "col-start-4"],
  ["col-start-6", "col-start-7"],
  ["col-start-9", "col-start-10"],
];
const LINE_V = "after:absolute after:left-1/2 after:h-3 after:w-px after:bg-border-strong";
// Nhánh ngang: nối tâm cột Thấp qua khe (bằng gap-x-1.5) tới tâm cột Cao, gặp đường dọc của nút cha ở giữa khe
const LINE_H = ["before:left-1/2 before:-right-1.5", "before:right-1/2 before:left-0"];

// Khung hẹp: tên + 2 cột giá 6.25rem, thẳng với cột giá của từng dòng ngày
const GROUP_COLUMNS = "grid grid-cols-[minmax(0,1fr)_6.25rem_6.25rem] items-end gap-x-2";
const GROUP_BRANCH = cn(
  "relative before:absolute before:inset-y-0 before:left-3 before:w-px before:bg-border-strong last:before:bottom-1/2",
  "after:absolute after:top-1/2 after:left-3 after:h-px after:w-3 after:bg-border-strong",
);

export function PriceTree({ types, courtCount, renderInput, t }: Props) {
  const label = (type: PriceType) => (
    <>
      <span className="truncate text-sm font-semibold" title={type.name}>{type.name}</span>
      <span className="text-xs text-muted">{courtCount(type.code)}</span>
    </>
  );

  return (
    <div className="@container">
      <div className={cn(GRID, "hidden items-center @3xl:grid")}>
        {DAY_TYPES.map((d, i) => (
          <div key={d} className={cn(DAY_COLUMN[i], LINE_V, "relative flex justify-center pb-3 after:bottom-0")}>
            <span className="rounded-lg bg-primary-soft px-3 py-1 text-sm font-semibold whitespace-nowrap">{t.dayTypes[d]}</span>
          </div>
        ))}
        {DAY_TYPES.flatMap((d, i) =>
          BANDS.map((b, j) => (
            <div
              key={`${d}-${b}`}
              className={cn(BAND_COLUMN[i][j], LINE_H[j], LINE_V, "relative flex justify-center pt-3 pb-2 after:top-0 before:absolute before:top-0 before:h-px before:bg-border-strong")}
            >
              <span className="text-xs font-medium whitespace-nowrap">{t.bands[b]}</span>
            </div>
          )),
        )}
        {types.map((type) => [
          <div key={type.code} className="col-start-1 flex min-w-0 flex-col py-1.5">{label(type)}</div>,
          ...DAY_TYPES.flatMap((d, i) =>
            BANDS.map((b, j) => (
              <div key={`${type.code}-${d}-${b}`} className={cn(BAND_COLUMN[i][j], "min-w-0 py-1.5")}>{renderInput(type, d, b)}</div>
            )),
          ),
        ])}
      </div>

      <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,20rem),1fr))] gap-x-4 gap-y-6 @3xl:hidden">
        {types.map((type) => (
          <section key={type.code} aria-label={type.name} className="flex min-w-0 flex-col">
            <div className={GROUP_COLUMNS}>
              <div className="flex min-w-0 flex-col pb-1">{label(type)}</div>
              {BANDS.map((b) => (
                <span key={b} aria-hidden className="pb-1 text-right text-xs font-medium text-muted">{t.bands[b]}</span>
              ))}
            </div>
            <ul className="flex flex-col">
              {DAY_TYPES.map((d) => (
                <li key={d} className={cn(GROUP_BRANCH, "flex items-center justify-between gap-1 py-1 pl-7")}>
                  <span className="min-w-0 text-sm">{t.dayTypes[d]}</span>
                  <span className="grid w-52 shrink-0 grid-cols-2 gap-2">
                    {BANDS.map((b) => (
                      <span key={b} className="block min-w-0">{renderInput(type, d, b)}</span>
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
