"use client";

import { useId } from "react";
import { TIERS } from "@/app/admin/hoi-vien/_components/member-params";

// Phần nhỏ của luồng đặt sân: chú thích màu của lưới, khối "Khoảng hạng của phòng".

function Legend({ swatch, text }: { swatch: string; text: string }) {
  return (
    <li className="inline-flex items-center gap-1 lg:gap-1.5">
      <span aria-hidden className={`inline-block size-3 shrink-0 rounded-sm lg:size-4 lg:rounded-[5px] ${swatch}`} />
      {text}
    </li>
  );
}

/** Các mục chú thích màu (đặt trong `<ul>` của khung lịch); hội viên có thêm "Sân của bạn". */
export function LegendItems({ member }: { member: boolean }) {
  return (
    <>
      <Legend swatch="border border-border-strong bg-surface" text="Trống" />
      <Legend swatch="bg-cell-booked" text="Đã đặt" />
      <Legend swatch="border border-dashed border-blk-hold-fg bg-surface" text="Đang giữ chỗ" />
      {member ? <Legend swatch="bg-blk-mine" text="Sân của bạn" /> : null}
      <Legend swatch="bg-blk-session" text="Sự kiện" />
      <Legend swatch="bg-cell-off" text="Không bán / Quá giờ" />
      <Legend swatch="border-2 border-sel-edge bg-sel" text="Đang chọn" />
    </>
  );
}

type Tier = (typeof TIERS)[number];

/** Hạng "từ" cao hơn hạng "đến" ⇒ sai thứ tự. */
export const tierOrderWrong = (min: string, max: string) => Boolean(min && max && TIERS.indexOf(min as Tier) > TIERS.indexOf(max as Tier));

/** "Khoảng hạng của phòng" (T-031 AC1): hai ô Hạng từ / đến, mặc định không giới hạn, báo ngay khi sai thứ tự. */
export function TierRangeBlock({ min, max, onChange }: { min: string; max: string; onChange: (v: { min: string; max: string }) => void }) {
  const idMin = useId();
  const idMax = useId();
  const wrong = tierOrderWrong(min, max);
  const sel = "h-11 w-full rounded-lg border bg-surface px-3 text-sm focus-ring";
  return (
    <section className="rounded-xl bg-surface p-4 shadow-card sm:p-5" aria-labelledby="tier-title">
      <h3 id="tier-title" className="text-sm font-bold text-primary">
        Khoảng hạng của phòng
      </h3>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor={idMin} className="mb-1 block text-sm font-medium">
            Hạng từ
          </label>
          <select id={idMin} value={min} onChange={(e) => onChange({ min: e.target.value, max })} aria-invalid={wrong || undefined} aria-describedby="tier-note" className={`${sel} ${wrong ? "border-danger" : "border-border"}`}>
            <option value="">Không giới hạn</option>
            {TIERS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={idMax} className="mb-1 block text-sm font-medium">
            Hạng đến
          </label>
          <select id={idMax} value={max} onChange={(e) => onChange({ min, max: e.target.value })} aria-invalid={wrong || undefined} aria-describedby="tier-note" className={`${sel} ${wrong ? "border-danger" : "border-border"}`}>
            <option value="">Không giới hạn</option>
            {TIERS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
      </div>
      {wrong ? (
        <p role="alert" className="mt-2 text-xs text-danger">
          Hạng “từ” phải thấp hơn hoặc bằng hạng “đến”.
        </p>
      ) : null}
      <p id="tier-note" className="mt-2 text-xs text-muted">
        Chỉ hội viên trong khoảng này mới vào được phòng của bạn. Chỉ chọn được lúc đặt, không sửa sau.
      </p>
    </section>
  );
}
